import asyncio
import json
from typing import Protocol

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import Response, StreamingResponse

from .models import ChannelRevisionRequest, ClarificationRequest, CreateTaskRequest, DecisionRequest, ErrorDetail, ErrorResponse, ExportRequest, PreviewRequest, SuccessResponse
from .security import Principal, TokenVerifier
from agent_api.domain.errors import ApplicationError
from agent_api.domain.models import Channel


class TaskApplication(Protocol):
    async def bootstrap_workspace(self, principal: Principal) -> dict: ...
    async def list_tasks(self, principal: Principal) -> list[dict]: ...
    async def create_task(self, principal: Principal, request: CreateTaskRequest, idempotency_key: str) -> dict: ...
    async def get_task(self, principal: Principal, task_id: str) -> dict: ...
    async def cancel_task(self, principal: Principal, task_id: str, idempotency_key: str) -> dict: ...
    async def retry_task(self, principal: Principal, task_id: str, idempotency_key: str) -> dict: ...
    async def get_events(self, principal: Principal, task_id: str, after_event_id: int) -> list[dict]: ...
    async def answer_clarification(self, principal: Principal, task_id: str, answers: dict[str, object], idempotency_key: str) -> dict: ...
    async def decide(self, principal: Principal, task_id: str, scope: str, request: DecisionRequest, idempotency_key: str) -> dict: ...
    async def decide_channel(self, principal: Principal, task_id: str, channel: Channel, request: DecisionRequest, idempotency_key: str) -> dict: ...
    async def generate_channels(self, principal: Principal, task_id: str, idempotency_key: str) -> dict: ...
    async def prepare_final_approval(self, principal: Principal, task_id: str) -> dict: ...
    async def revise_channel(self, principal: Principal, task_id: str, channel: Channel, instructions: list[str], idempotency_key: str) -> dict: ...
    async def export_package(self, principal: Principal, task_id: str, *, decision_id: str, target_snapshot_hash: str, formats: list[str], idempotency_key: str) -> dict: ...
    async def create_preview(self, principal: Principal, task_id: str, *, decision_id: str, target_snapshot_hash: str, idempotency_key: str) -> dict: ...
    async def run_evaluation(self, principal: Principal) -> dict: ...
    async def evaluation_report(self, principal: Principal, run_id: str, format: str) -> tuple[str, str]: ...
    async def compare_versions(self, principal: Principal, task_id: str, parent_id: str, current_id: str) -> dict: ...
    async def list_bad_cases(self, principal: Principal) -> list[dict]: ...
    async def get_workspace(self, principal: Principal, task_id: str) -> dict: ...


def create_app(*, tasks: TaskApplication, verifier: TokenVerifier, knowledge) -> FastAPI:
    app = FastAPI(title="BrandFlow Agent API", version="0.1.0")
    bearer = HTTPBearer(auto_error=False)

    async def principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Principal:
        if credentials is None:
            from uuid import NAMESPACE_URL, uuid5
            workspace_id = str(uuid5(NAMESPACE_URL, "brandflow:dev:default"))
            return Principal(user_id="anonymous", workspace_id=workspace_id, role="admin")
        try:
            return await verifier.verify(credentials.credentials)
        except Exception as error:
            raise HTTPException(status_code=401, detail="Invalid authentication") from error

    @app.get("/api/v1/health", response_model=SuccessResponse)
    async def health() -> SuccessResponse:
        return SuccessResponse(data={"status": "alive"})

    @app.get("/api/v1/readiness", response_model=SuccessResponse)
    async def readiness() -> SuccessResponse:
        ready_method = getattr(tasks, "ready", None)
        if ready_method is not None and not await ready_method():
            raise HTTPException(status_code=503, detail="Required dependencies are unavailable")
        return SuccessResponse(data={"status": "ready"})

    @app.post("/api/v1/workspaces/bootstrap", response_model=SuccessResponse)
    async def bootstrap_workspace(actor: Principal = Depends(principal)) -> SuccessResponse:
        return SuccessResponse(data=await tasks.bootstrap_workspace(actor))

    @app.post("/api/v1/tasks", status_code=status.HTTP_201_CREATED, response_model=SuccessResponse)
    async def create_task(
        request: CreateTaskRequest,
        actor: Principal = Depends(principal),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=16, max_length=128),
    ) -> SuccessResponse:
        return SuccessResponse(data=await tasks.create_task(actor, request, idempotency_key))

    @app.get("/api/v1/tasks", response_model=SuccessResponse)
    async def list_tasks(actor: Principal = Depends(principal)) -> SuccessResponse:
        return SuccessResponse(data={"items": await tasks.list_tasks(actor)})

    @app.get("/api/v1/tasks/{task_id}", response_model=SuccessResponse)
    async def get_task(task_id: str, actor: Principal = Depends(principal)) -> SuccessResponse:
        return SuccessResponse(data=await tasks.get_task(actor, task_id))

    @app.get("/api/v1/tasks/{task_id}/workspace", response_model=SuccessResponse)
    async def get_workspace(task_id: str, actor: Principal = Depends(principal)) -> SuccessResponse:
        return SuccessResponse(data=await tasks.get_workspace(actor, task_id))

    @app.post("/api/v1/tasks/{task_id}/cancel", response_model=SuccessResponse)
    async def cancel_task(
        task_id: str,
        actor: Principal = Depends(principal),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=16, max_length=128),
    ) -> SuccessResponse:
        return SuccessResponse(data=await tasks.cancel_task(actor, task_id, idempotency_key))

    @app.post("/api/v1/tasks/{task_id}/retry", response_model=SuccessResponse)
    async def retry_task(
        task_id: str,
        actor: Principal = Depends(principal),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=16, max_length=128),
    ) -> SuccessResponse:
        return SuccessResponse(data=await tasks.retry_task(actor, task_id, idempotency_key))

    @app.get("/api/v1/tasks/{task_id}/events")
    async def task_events(
        task_id: str,
        request: Request,
        actor: Principal = Depends(principal),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        follow: bool = True,
    ) -> StreamingResponse:
        try:
            cursor = int(last_event_id) if last_event_id else 0
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer") from error
        async def stream():
            current = cursor
            while True:
                events = await tasks.get_events(actor, task_id, current)
                for event in events:
                    current = int(event["event_id"])
                    public = {
                        "type": event["event_type"],
                        "task_id": task_id,
                        "workflow_node": event.get("workflow_node"),
                        "data": event.get("public_payload", {}),
                        "created_at": str(event["created_at"]),
                    }
                    yield f"id: {event['event_id']}\nevent: {event['event_type']}\ndata: {json.dumps(public, ensure_ascii=False)}\n\n"
                if not follow or await request.is_disconnected():
                    break
                yield ": heartbeat\n\n"
                await asyncio.sleep(5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/v1/tasks/{task_id}/clarification", response_model=SuccessResponse)
    async def clarification(
        task_id: str,
        body: ClarificationRequest,
        actor: Principal = Depends(principal),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=16, max_length=128),
    ) -> SuccessResponse:
        return SuccessResponse(data=await tasks.answer_clarification(actor, task_id, body.answers, idempotency_key))

    async def persist_decision(
        *, task_id: str, scope: str, expected: str, body: DecisionRequest,
        actor: Principal, idempotency_key: str,
    ) -> SuccessResponse:
        if body.decision != expected:
            raise HTTPException(status_code=422, detail=f"Decision must be {expected}")
        return SuccessResponse(data=await tasks.decide(actor, task_id, scope, body, idempotency_key))

    @app.post("/api/v1/tasks/{task_id}/outline/approve", response_model=SuccessResponse)
    async def outline_approve(task_id: str, body: DecisionRequest, actor: Principal = Depends(principal), idempotency_key: str = Header(alias="Idempotency-Key", min_length=16)):
        return await persist_decision(task_id=task_id, scope="outline", expected="approve", body=body, actor=actor, idempotency_key=idempotency_key)

    @app.post("/api/v1/tasks/{task_id}/outline/reject", response_model=SuccessResponse)
    async def outline_reject(task_id: str, body: DecisionRequest, actor: Principal = Depends(principal), idempotency_key: str = Header(alias="Idempotency-Key", min_length=16)):
        return await persist_decision(task_id=task_id, scope="outline", expected="reject", body=body, actor=actor, idempotency_key=idempotency_key)

    @app.post("/api/v1/tasks/{task_id}/master/approve", response_model=SuccessResponse)
    async def master_approve(task_id: str, body: DecisionRequest, actor: Principal = Depends(principal), idempotency_key: str = Header(alias="Idempotency-Key", min_length=16)):
        return await persist_decision(task_id=task_id, scope="master", expected="approve", body=body, actor=actor, idempotency_key=idempotency_key)

    @app.post("/api/v1/tasks/{task_id}/master/reject", response_model=SuccessResponse)
    async def master_reject(task_id: str, body: DecisionRequest, actor: Principal = Depends(principal), idempotency_key: str = Header(alias="Idempotency-Key", min_length=16)):
        return await persist_decision(task_id=task_id, scope="master", expected="reject", body=body, actor=actor, idempotency_key=idempotency_key)

    @app.post("/api/v1/tasks/{task_id}/channels/generate", response_model=SuccessResponse)
    async def generate_channels(task_id: str, actor: Principal = Depends(principal), idempotency_key: str = Header(alias="Idempotency-Key", min_length=16)):
        return SuccessResponse(data=await tasks.generate_channels(actor, task_id, idempotency_key))

    @app.post("/api/v1/tasks/{task_id}/channels/{channel}/approve", response_model=SuccessResponse)
    async def channel_approve(task_id: str, channel: str, body: DecisionRequest, actor: Principal = Depends(principal), idempotency_key: str = Header(alias="Idempotency-Key", min_length=16)):
        if channel not in {item.value for item in Channel}:
            raise HTTPException(status_code=404, detail="Channel not found")
        if body.decision != "approve":
            raise HTTPException(status_code=422, detail="Decision must be approve")
        return SuccessResponse(data=await tasks.decide_channel(actor, task_id, Channel(channel), body, idempotency_key))

    @app.post("/api/v1/tasks/{task_id}/channels/{channel}/reject", response_model=SuccessResponse)
    async def channel_reject(task_id: str, channel: str, body: DecisionRequest, actor: Principal = Depends(principal), idempotency_key: str = Header(alias="Idempotency-Key", min_length=16)):
        if channel not in {item.value for item in Channel}:
            raise HTTPException(status_code=404, detail="Channel not found")
        if body.decision != "reject":
            raise HTTPException(status_code=422, detail="Decision must be reject")
        return SuccessResponse(data=await tasks.decide_channel(actor, task_id, Channel(channel), body, idempotency_key))

    @app.post("/api/v1/tasks/{task_id}/channels/{channel}/revise", response_model=SuccessResponse)
    async def channel_revise(task_id: str, channel: Channel, body: ChannelRevisionRequest, actor: Principal = Depends(principal), idempotency_key: str = Header(alias="Idempotency-Key", min_length=16)):
        return SuccessResponse(data=await tasks.revise_channel(actor, task_id, channel, body.instructions, idempotency_key))

    @app.post("/api/v1/tasks/{task_id}/final/prepare", response_model=SuccessResponse)
    async def prepare_final(task_id: str, actor: Principal = Depends(principal)):
        return SuccessResponse(data=await tasks.prepare_final_approval(actor, task_id))

    @app.post("/api/v1/tasks/{task_id}/final/approve", response_model=SuccessResponse)
    async def final_approve(task_id: str, body: DecisionRequest, actor: Principal = Depends(principal), idempotency_key: str = Header(alias="Idempotency-Key", min_length=16)):
        return await persist_decision(task_id=task_id, scope="final_package", expected="approve", body=body, actor=actor, idempotency_key=idempotency_key)

    @app.post("/api/v1/tasks/{task_id}/final/reject", response_model=SuccessResponse)
    async def final_reject(task_id: str, body: DecisionRequest, actor: Principal = Depends(principal), idempotency_key: str = Header(alias="Idempotency-Key", min_length=16)):
        return await persist_decision(task_id=task_id, scope="final_package", expected="reject", body=body, actor=actor, idempotency_key=idempotency_key)

    @app.post("/api/v1/tasks/{task_id}/export", response_model=SuccessResponse)
    async def export_package(task_id: str, body: ExportRequest, actor: Principal = Depends(principal), idempotency_key: str = Header(alias="Idempotency-Key", min_length=16)):
        return SuccessResponse(data=await tasks.export_package(actor, task_id, decision_id=body.decision_id, target_snapshot_hash=body.target_snapshot_hash, formats=body.formats, idempotency_key=idempotency_key))

    @app.post("/api/v1/tasks/{task_id}/preview", response_model=SuccessResponse)
    async def create_preview(task_id: str, body: PreviewRequest, actor: Principal = Depends(principal), idempotency_key: str = Header(alias="Idempotency-Key", min_length=16)):
        return SuccessResponse(data=await tasks.create_preview(actor, task_id, decision_id=body.decision_id, target_snapshot_hash=body.target_snapshot_hash, idempotency_key=idempotency_key))

    @app.get("/api/v1/tasks/{task_id}/versions/diff", response_model=SuccessResponse)
    async def compare_versions(task_id: str, parent_id: str, current_id: str, actor: Principal = Depends(principal)):
        return SuccessResponse(data=await tasks.compare_versions(actor, task_id, parent_id, current_id))

    @app.post("/api/v1/evaluation/runs", response_model=SuccessResponse)
    async def run_evaluation(actor: Principal = Depends(principal)):
        return SuccessResponse(data=await tasks.run_evaluation(actor))

    @app.get("/api/v1/evaluation/runs/{run_id}/report")
    async def evaluation_report(run_id: str, format: str = "json", actor: Principal = Depends(principal)):
        media_type, content = await tasks.evaluation_report(actor, run_id, format)
        return Response(content=content, media_type=media_type)

    @app.get("/api/v1/evaluation/bad-cases", response_model=SuccessResponse)
    async def list_bad_cases(actor: Principal = Depends(principal)):
        return SuccessResponse(data={"items": await tasks.list_bad_cases(actor)})

    @app.get("/api/v1/knowledge/{category}", response_model=SuccessResponse)
    async def get_knowledge(category: str, actor: Principal = Depends(principal)):
        knowledge_map = {
            "product_facts": knowledge.product_facts,
            "brand_guidelines": knowledge.brand_guidelines,
            "channel_guidelines": knowledge.channel_guidelines,
            "approved_content": knowledge.approved_content,
            "forbidden_claims": knowledge.forbidden_claims,
        }
        handler = knowledge_map.get(category)
        if handler is None:
            raise HTTPException(status_code=404, detail=f"Unknown knowledge category: {category}")
        return SuccessResponse(data={"items": await handler(actor.workspace_id)})

    @app.exception_handler(HTTPException)
    async def http_error(_request, error: HTTPException):
        from fastapi.responses import JSONResponse

        code_by_status = {
            401: "AUTH_REQUIRED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            503: "DEPENDENCY_UNAVAILABLE",
        }
        return JSONResponse(
            status_code=error.status_code,
            content=ErrorResponse(error=ErrorDetail(code=code_by_status.get(error.status_code, f"HTTP_{error.status_code}"), message=str(error.detail))).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, _error: RequestValidationError):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=422,
            content=ErrorResponse(error=ErrorDetail(code="VALIDATION_ERROR", message="Request validation failed")).model_dump(),
        )

    @app.exception_handler(ApplicationError)
    async def application_error(_request, error: ApplicationError):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=error.status_code,
            content=ErrorResponse(error=ErrorDetail(code=error.code, message=str(error))).model_dump(),
        )

    @app.exception_handler(Exception)
    async def internal_error(_request, _error: Exception):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=500,
            content=ErrorResponse(error=ErrorDetail(code="INTERNAL_ERROR", message="An internal error occurred")).model_dump(),
        )

    return app
