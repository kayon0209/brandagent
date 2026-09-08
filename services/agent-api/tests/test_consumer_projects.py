"""Consumer project application tests (upgrade plan task 8).

Vertical slice through the public service interface: create project with
core idea, update title/core idea independently, cross-workspace 404, and
material linking — all backed by an in-memory store implementing the
ConsumerProjectStore protocol.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from agent_api.api.security import Principal
from agent_api.application.consumer_projects import ConsumerProjectService
from agent_api.domain.errors import ConflictError, NotFoundError


def principal_for(workspace_id: str) -> Principal:
    return Principal(user_id="consumer-1", workspace_id=workspace_id, role="admin", experience="personal")


class MemoryConsumerProjectStore:
    """In-memory implementation of the ConsumerProjectStore protocol."""

    def __init__(self) -> None:
        self.projects: dict[str, dict] = {}
        self.material_links: dict[str, set[str]] = {}
        self.excerpts_by_workspace: dict[str, list[dict]] = {}
        self.events: list[dict] = []

    async def insert_project(self, workspace_id: str, title: str, core_idea: str, intent: str) -> dict:
        task_id = str(uuid4())
        self.projects[task_id] = {
            "task_id": task_id,
            "workspace_id": workspace_id,
            "title": title,
            "core_idea": core_idea,
            "writing_intent": intent,
            "active_master_version_id": None,
            "linked_excerpt_ids": [],
        }
        return dict(self.projects[task_id])

    async def get_project(self, workspace_id: str, task_id: str) -> dict | None:
        project = self.projects.get(task_id)
        if project and project["workspace_id"] == workspace_id:
            return dict(project)
        return None

    async def list_projects(self, workspace_id: str) -> list[dict]:
        return [dict(p) for p in self.projects.values() if p["workspace_id"] == workspace_id]

    async def update_project(self, workspace_id: str, task_id: str, *, title: str | None, core_idea: str | None, intent: str | None, preferred_style_report_id: str | None = None) -> dict | None:
        project = self.projects.get(task_id)
        if not project or project["workspace_id"] != workspace_id:
            return None
        if title is not None:
            project["title"] = title
        if core_idea is not None:
            project["core_idea"] = core_idea
        if intent is not None:
            project["writing_intent"] = intent
        return dict(project)

    async def link_excerpt(self, workspace_id: str, task_id: str, excerpt_id: str) -> dict | None:
        project = self.projects.get(task_id)
        if not project or project["workspace_id"] != workspace_id:
            return None
        if excerpt_id not in project["linked_excerpt_ids"]:
            project["linked_excerpt_ids"].append(excerpt_id)
        return dict(project)

    async def unlink_excerpt(self, workspace_id: str, task_id: str, excerpt_id: str) -> dict | None:
        project = self.projects.get(task_id)
        if not project or project["workspace_id"] != workspace_id:
            return None
        project["linked_excerpt_ids"] = [e for e in project["linked_excerpt_ids"] if e != excerpt_id]
        return dict(project)

    async def get_excerpts_by_ids(self, workspace_id: str, excerpt_ids: list[str]) -> list[dict]:
        available = self.excerpts_by_workspace.setdefault(workspace_id, [])
        return [dict(e) for e in available if e["excerpt_id"] in excerpt_ids]

    async def append_event(self, event: dict) -> None:
        self.events.append(event)

    async def list_events(self, workspace_id: str, task_id: str, *, after_event_id: int = 0, limit: int = 100) -> list[dict]:
        rows = [
            {**e, "event_id": index + 1, "event_version": "1.0", "workflow_node": "consumer_projects", "created_at": "2026-09-03T00:00:00+00:00"}
            for index, e in enumerate(self.events)
            if e["task_id"] == task_id and e["workspace_id"] == workspace_id
        ]
        return [r for r in rows if r["event_id"] > after_event_id][:limit]


    async def get_style_report(self, workspace_id: str, report_id: str) -> dict | None:
        return None


def make_service() -> tuple[ConsumerProjectService, MemoryConsumerProjectStore]:
    store = MemoryConsumerProjectStore()
    service = ConsumerProjectService(store=store)
    return service, store


@pytest.mark.asyncio
async def test_create_project_persists_title_core_idea_and_intent() -> None:
    service, store = make_service()
    created = await service.create_project(
        principal_for("ws-1"), title="Nova 发布", core_idea="讲清楚 Nova 的价值", intent="公众号文章"
    )
    assert created["title"] == "Nova 发布"
    assert created["core_idea"] == "讲清楚 Nova 的价值"
    assert created["writing_intent"] == "公众号文章"
    assert created["task_id"]
    assert any(e["event_type"] == "consumer.project.created.v1" for e in store.events)


@pytest.mark.asyncio
async def test_list_project_events_returns_stream_in_order_with_cursor() -> None:
    service, _ = make_service()
    principal = principal_for("ws-1")
    created = await service.create_project(principal, title="事件流", core_idea="观点", intent="")
    task_id = created["task_id"]
    await service.update_project(principal, task_id, title="新标题", core_idea=None, intent=None)

    all_events = await service.list_project_events(principal, task_id)
    assert [e["event_type"] for e in all_events] == [
        "consumer.project.created.v1",
        "consumer.project.updated.v1",
    ]
    # cursor semantics: only strictly-after events come back
    tail = await service.list_project_events(principal, task_id, after_event_id=all_events[0]["event_id"])
    assert [e["event_type"] for e in tail] == ["consumer.project.updated.v1"]
    # beyond the last event id: empty, not an error
    assert await service.list_project_events(principal, task_id, after_event_id=all_events[-1]["event_id"]) == []


@pytest.mark.asyncio
async def test_list_project_events_is_workspace_scoped() -> None:
    service, _ = make_service()
    created = await service.create_project(principal_for("ws-1"), title="A", core_idea="a", intent="")
    other = principal_for("ws-2")
    with pytest.raises(NotFoundError):
        # cross-tenant id must not reveal stream contents
        await service.list_project_events(other, created["task_id"])


@pytest.mark.asyncio
async def test_title_and_core_idea_update_independently() -> None:
    service, _ = make_service()
    principal = principal_for("ws-1")
    created = await service.create_project(principal, title="旧标题", core_idea="旧观点", intent="周更")
    updated = await service.update_project(principal, created["task_id"], title="新标题", core_idea=None, intent=None)
    assert updated["title"] == "新标题"
    assert updated["core_idea"] == "旧观点"
    updated_again = await service.update_project(principal, created["task_id"], title=None, core_idea="新观点", intent=None)
    assert updated_again["title"] == "新标题"
    assert updated_again["core_idea"] == "新观点"


@pytest.mark.asyncio
async def test_cross_workspace_project_id_returns_404() -> None:
    service, _ = make_service()
    created = await service.create_project(principal_for("ws-1"), title="p", core_idea="c", intent="i")
    with pytest.raises(NotFoundError):
        await service.get_project(principal_for("ws-2"), created["task_id"])


@pytest.mark.asyncio
async def test_link_and_unlink_excerpt_keeps_project_view_consistent() -> None:
    service, store = make_service()
    store.excerpts_by_workspace["ws-1"] = [
        {"excerpt_id": "ex-1", "summary": "s", "excerpt_text": "t", "excerpt_type": "quote", "document_id": "d1", "provenance_hash": "h" * 64}
    ]
    principal = principal_for("ws-1")
    created = await service.create_project(principal, title="p", core_idea="c", intent="i")
    linked = await service.link_excerpt(principal, created["task_id"], "ex-1")
    assert linked["linked_excerpts"][0]["excerpt_id"] == "ex-1"
    unlinked = await service.unlink_excerpt(principal, created["task_id"], "ex-1")
    assert unlinked["linked_excerpts"] == []


@pytest.mark.asyncio
async def test_linking_an_excerpt_from_another_workspace_fails() -> None:
    service, store = make_service()
    store.excerpts_by_workspace["ws-2"] = [
        {"excerpt_id": "ex-foreign", "summary": "s", "excerpt_text": "t", "excerpt_type": "quote", "document_id": "d1", "provenance_hash": "h" * 64}
    ]
    principal = principal_for("ws-1")
    created = await service.create_project(principal, title="p", core_idea="c", intent="i")
    with pytest.raises(NotFoundError):
        await service.link_excerpt(principal, created["task_id"], "ex-foreign")
