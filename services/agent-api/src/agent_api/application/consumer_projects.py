"""Consumer project application service (upgrade plan task 8).

A consumer project is the personal aggregate over content_tasks: title,
core idea, writing intent, linked material excerpts, and the active
adopted snapshot. The service orchestrates the ConsumerProjectStore port
and emits consumer-scoped events; it never touches SQL directly.
"""

from __future__ import annotations

from typing import Protocol

from agent_api.api.security import Principal
from agent_api.domain.errors import NotFoundError


class ConsumerProjectStore(Protocol):
    """Persistence port for consumer projects."""

    async def insert_project(self, workspace_id: str, title: str, core_idea: str, intent: str) -> dict: ...
    async def get_project(self, workspace_id: str, task_id: str) -> dict | None: ...
    async def list_projects(self, workspace_id: str) -> list[dict]: ...
    async def update_project(self, workspace_id: str, task_id: str, *, title: str | None, core_idea: str | None, intent: str | None, preferred_style_report_id: str | None = None) -> dict | None: ...
    async def link_excerpt(self, workspace_id: str, task_id: str, excerpt_id: str) -> dict | None: ...
    async def unlink_excerpt(self, workspace_id: str, task_id: str, excerpt_id: str) -> dict | None: ...
    async def get_excerpts_by_ids(self, workspace_id: str, excerpt_ids: list[str]) -> list[dict]: ...
    async def append_event(self, event: dict) -> None: ...


_EVENT_PROJECT_CREATED = "consumer.project.created.v1"
_EVENT_PROJECT_UPDATED = "consumer.project.updated.v1"
_EVENT_EXCERPT_LINKED = "consumer.project.excerpt.linked.v1"
_EVENT_EXCERPT_UNLINKED = "consumer.project.excerpt.unlinked.v1"


class ConsumerProjectService:
    def __init__(self, *, store: ConsumerProjectStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _require_project(self, principal: Principal, task_id: str) -> dict:
        project = await self._store.get_project(principal.workspace_id, task_id)
        if project is None:
            raise NotFoundError(f"project {task_id} not found in this workspace")
        return project

    async def _emit(self, principal: Principal, task_id: str, event_type: str, data: dict) -> None:
        await self._store.append_event(
            {
                "workspace_id": principal.workspace_id,
                "task_id": task_id,
                "event_type": event_type,
                "data": data,
            }
        )

    async def _project_view(self, project: dict, principal: Principal) -> dict:
        excerpt_ids = project.get("linked_excerpt_ids") or []
        excerpts = await self._store.get_excerpts_by_ids(principal.workspace_id, excerpt_ids)
        return {
            "task_id": project["task_id"],
            "title": project["title"],
            "core_idea": project["core_idea"],
            "writing_intent": project["writing_intent"],
            "active_master_version_id": project.get("active_master_version_id"),
            "preferred_style_report_id": str(project["preferred_style_report_id"]) if project.get("preferred_style_report_id") else None,
            "linked_excerpts": excerpts,
            "updated_at": str(project["updated_at"]) if project.get("updated_at") else None,
        }

    # ------------------------------------------------------------------
    # public interface
    # ------------------------------------------------------------------

    async def create_project(self, principal: Principal, *, title: str, core_idea: str, intent: str) -> dict:
        if not title or not title.strip():
            raise ValueError("title is required")
        if not core_idea or not core_idea.strip():
            raise ValueError("core_idea is required")
        project = await self._store.insert_project(principal.workspace_id, title.strip(), core_idea.strip(), (intent or "").strip())
        await self._emit(principal, project["task_id"], _EVENT_PROJECT_CREATED, {"project_id": project["task_id"], "title": project["title"]})
        return await self._project_view(project, principal)

    async def get_project(self, principal: Principal, task_id: str) -> dict:
        return await self._project_view(await self._require_project(principal, task_id), principal)

    async def list_project_events(
        self, principal: Principal, task_id: str, *, after_event_id: int = 0, limit: int = 100
    ) -> list[dict]:
        """SSE read side of the project event stream (plan §7.4: long tasks
        surface progress via task_events + SSE; the same stream is also the
        cross-tab invalidation source). 404 semantics match get_project so a
        cross-tenant id never reveals existence."""
        await self._require_project(principal, task_id)
        return await self._store.list_events(
            principal.workspace_id, task_id, after_event_id=after_event_id, limit=limit
        )

    async def list_projects(self, principal: Principal) -> list[dict]:
        projects = await self._store.list_projects(principal.workspace_id)
        return [await self._project_view(project, principal) for project in projects]

    async def update_project(
        self,
        principal: Principal,
        task_id: str,
        *,
        title: str | None,
        core_idea: str | None,
        intent: str | None,
        preferred_style_report_id: str | None = None,
    ) -> dict:
        await self._require_project(principal, task_id)
        if title is not None and not title.strip():
            raise ValueError("title cannot be empty")
        if core_idea is not None and not core_idea.strip():
            raise ValueError("core_idea cannot be empty")
        # 007: bind a distilled style report to the project. The report
        # must exist in THIS workspace before binding (cross-workspace
        # style ids are rejected, not silently linked).
        if preferred_style_report_id is not None:
            report = await self._store.get_style_report(principal.workspace_id, preferred_style_report_id)
            if report is None:
                raise NotFoundError(f"style report {preferred_style_report_id} not found in this workspace")
        updated = await self._store.update_project(
            principal.workspace_id,
            task_id,
            title=title.strip() if title is not None else None,
            core_idea=core_idea.strip() if core_idea is not None else None,
            intent=intent.strip() if intent is not None else None,
            preferred_style_report_id=preferred_style_report_id,
        )
        await self._emit(principal, task_id, _EVENT_PROJECT_UPDATED, {"project_id": task_id})
        return await self._project_view(updated, principal)

    async def link_excerpt(self, principal: Principal, task_id: str, excerpt_id: str) -> dict:
        await self._require_project(principal, task_id)
        # the excerpt must already exist in the same workspace before linking
        excerpts = await self._store.get_excerpts_by_ids(principal.workspace_id, [excerpt_id])
        if not excerpts:
            raise NotFoundError(f"excerpt {excerpt_id} not found in this workspace")
        await self._store.link_excerpt(principal.workspace_id, task_id, excerpt_id)
        await self._emit(principal, task_id, _EVENT_EXCERPT_LINKED, {"excerpt_id": excerpt_id})
        return await self.get_project(principal, task_id)

    async def unlink_excerpt(self, principal: Principal, task_id: str, excerpt_id: str) -> dict:
        await self._require_project(principal, task_id)
        await self._store.unlink_excerpt(principal.workspace_id, task_id, excerpt_id)
        await self._emit(principal, task_id, _EVENT_EXCERPT_UNLINKED, {"excerpt_id": excerpt_id})
        return await self.get_project(principal, task_id)
