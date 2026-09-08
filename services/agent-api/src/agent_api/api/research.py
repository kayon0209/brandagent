"""Deep research API routes (Phase 6 product, user-approved 2026-09-08).

Mounted under /api/v1/consumer/research. Same envelope and auth
discipline as the other consumer routers; the SSE stream mirrors
project_events (id: cursor, Last-Event-ID resume, 5s heartbeat).
"""

from __future__ import annotations

import asyncio
import json
from typing import Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from agent_api.api.security import Principal


class DeepResearchApp(Protocol):
    research: "DeepResearchServiceProtocol"
    materials: "MaterialsLike"
    projects: "ProjectsLike"

    async def join_material(self, principal: Principal, run_id: str, card_index: int, task_id: str | None) -> dict: ...


class DeepResearchServiceProtocol(Protocol):
    async def start(self, principal: Principal, *, question: str, audience: str, scope_hint: str, request_id: str) -> dict: ...

    async def list(self, principal: Principal) -> list[dict]: ...
    async def get(self, principal: Principal, run_id: str) -> dict: ...
    async def cancel(self, principal: Principal, run_id: str) -> dict: ...
    async def events(self, principal: Principal, run_id: str, after_event_id: int) -> list[dict]: ...
    def estimated_tokens_preview(self) -> int: ...
    async def join_material(self, principal: Principal, run_id: str, card_index: int, task_id: str | None, *, materials, projects=None) -> dict: ...


class MaterialsLike(Protocol):
    async def import_research_card(self, principal: Principal, *, name: str, content: str, source_url: str, request_id: str) -> dict: ...

    async def get_document_view(self, principal: Principal, document_id: str) -> dict: ...


class ProjectsLike(Protocol):
    async def link_excerpt(self, principal: Principal, task_id: str, excerpt_id: str) -> dict: ...


def create_research_router(app: DeepResearchApp, *, principal) -> APIRouter:
    router = APIRouter(prefix="/api/v1/consumer/research", tags=["consumer-research"])

    @router.post("", status_code=202)
    async def start_research(
        body: dict,
        actor: Principal = Depends(principal),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ):
        from agent_api.application.deep_research import DeepResearchError
        from agent_api.domain.errors import ApplicationError

        question = str(body.get("question", "")).strip()
        audience = str(body.get("audience", "")).strip()
        scope_hint = str(body.get("scope", "") or body.get("scope_hint", "")).strip()
        try:
            run = await app.research.start(
                actor,
                question=question,
                audience=audience,
                scope_hint=scope_hint,
                request_id=idempotency_key,
            )
        except DeepResearchError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        except ApplicationError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        # no model call has happened yet: the preview is a static estimate
        estimated = app.research.estimated_tokens_preview()
        return {
            "success": True,
            "data": {**run, "estimated_tokens": estimated},
        }

    @router.get("")
    async def list_research(actor: Principal = Depends(principal)):
        from agent_api.application.deep_research import DeepResearchError

        try:
            runs = await app.research.list(actor)
        except DeepResearchError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        return {"success": True, "data": {"items": runs}}

    @router.get("/{run_id}")
    async def get_research(run_id: str, actor: Principal = Depends(principal)):
        from agent_api.application.deep_research import DeepResearchError

        try:
            run = await app.research.get(actor, run_id)
        except DeepResearchError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        return {"success": True, "data": run}

    @router.post("/{run_id}/cancel")
    async def cancel_research(
        run_id: str,
        actor: Principal = Depends(principal),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ):
        from agent_api.application.deep_research import DeepResearchError

        try:
            run = await app.research.cancel(actor, run_id)
        except DeepResearchError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        return {"success": True, "data": run}

    @router.get("/{run_id}/events")
    async def research_events(
        run_id: str,
        request: Request,
        actor: Principal = Depends(principal),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        follow: bool = True,
    ) -> StreamingResponse:
        """SSE progress stream; same wire contract as project events."""
        from agent_api.application.deep_research import DeepResearchError

        try:
            run = await app.research.get(actor, run_id)
        except DeepResearchError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        try:
            cursor = int(last_event_id) if last_event_id else 0
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer") from error

        async def stream():
            nonlocal run
            current = cursor
            while True:
                events = await app.research.events(actor, run_id, current)
                for event in events:
                    current = int(event["event_id"])
                    payload = {
                        "type": event["event_type"],
                        "run_id": run_id,
                        "event_version": event.get("event_version", "1.0"),
                        "data": event.get("public_payload", {}),
                        "created_at": str(event.get("created_at", "")),
                    }
                    yield (
                        f"id: {event['event_id']}\nevent: {event['event_type']}\n"
                        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    )
                terminal = run.get("status") in ("succeeded", "failed", "canceled")
                if not follow or terminal or await request.is_disconnected():
                    break
                yield ": heartbeat\n\n"
                await asyncio.sleep(5)
                # refresh the run so a terminal status observed while
                # streaming ends the loop even without new events
                try:
                    run = await app.research.get(actor, run_id)
                except Exception:  # noqa: BLE001 — stream keeps polling
                    pass

        return StreamingResponse(stream(), media_type="text/event-stream")

    @router.post("/{run_id}/cards/{card_index}/join")
    async def join_card(
        run_id: str,
        card_index: int,
        body: dict,
        actor: Principal = Depends(principal),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ):
        """Turn one candidate card into a traceable material excerpt.

        The card content becomes a link-kind source_document + one chunk +
        one excerpt (provenance bound to URL + retrieved_at), optionally
        linked to the current project when task_id is present.
        """
        from agent_api.application.deep_research import DeepResearchError
        from agent_api.domain.errors import ApplicationError

        task_id = body.get("task_id") or None
        try:
            result = await app.research.join_material(
                actor, run_id, card_index, task_id,
                materials=app.materials, projects=app.projects,
            )
        except DeepResearchError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        except ApplicationError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        return {"success": True, "data": result}

    return router
