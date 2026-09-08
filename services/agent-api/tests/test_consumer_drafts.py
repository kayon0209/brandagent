"""Consumer draft tests (upgrade plan task 8): revision CAS, autosave,
generation with revision guard, and adopt snapshot semantics.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from agent_api.api.security import Principal
from agent_api.application.consumer_projects import ConsumerProjectService
from agent_api.application.drafts import DraftService
from agent_api.application.draft_generation import DraftGenerationService
from agent_api.domain.errors import ConflictError, NotFoundError


def principal_for(workspace_id: str) -> Principal:
    return Principal(user_id="consumer-1", workspace_id=workspace_id, role="admin", experience="personal")


class MemoryProjectStore:
    def __init__(self) -> None:
        self.projects: dict[str, dict] = {}
        self.material_links: dict[str, list[str]] = {}
        self.excerpts: dict[str, list[dict]] = {}
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
            "linked_excerpt_ids": list(self.material_links.get(task_id, [])),
        }
        return dict(self.projects[task_id])

    async def get_project(self, workspace_id: str, task_id: str) -> dict | None:
        project = self.projects.get(task_id)
        return dict(project) if project and project["workspace_id"] == workspace_id else None

    async def update_project(self, workspace_id: str, task_id: str, *, title, core_idea, intent, preferred_style_report_id=None) -> dict | None:
        project = self.projects.get(task_id)
        if not project or project["workspace_id"] != workspace_id:
            return None
        for key, value in (("title", title), ("core_idea", core_idea), ("writing_intent", intent)):
            if value is not None:
                project[key] = value
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
        available = self.excerpts.setdefault(workspace_id, [])
        return [dict(e) for e in available if e["excerpt_id"] in excerpt_ids]

    async def append_event(self, event: dict) -> None:
        self.events.append(event)


class MemoryDraftStore:
    """In-memory ConsumerDraftStore: revision compare-and-swap semantics."""

    def __init__(self) -> None:
        self.drafts: dict[str, dict] = {}
        self.versions: dict[str, dict] = {}
        self.blocks: dict[str, list[dict]] = {}

    async def ensure_draft(self, workspace_id: str, task_id: str) -> dict:
        if task_id not in self.drafts:
            self.drafts[task_id] = {
                "task_id": task_id,
                "workspace_id": workspace_id,
                "revision": 0,
                "document": {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": ""}]},
                "plain_text": "",
                "last_snapshot_version_id": None,
            }
        return dict(self.drafts[task_id])

    async def get_draft(self, workspace_id: str, task_id: str) -> dict | None:
        draft = self.drafts.get(task_id)
        return dict(draft) if draft and draft["workspace_id"] == workspace_id else None

    async def save_draft(self, workspace_id: str, task_id: str, document: dict, plain_text: str, expected_revision: int) -> dict:
        draft = self.drafts.get(task_id)
        if not draft or draft["workspace_id"] != workspace_id:
            raise NotFoundError("draft")
        if draft["revision"] != expected_revision:
            raise ConflictError("draft revision changed elsewhere")
        draft["revision"] = expected_revision + 1
        draft["document"] = document
        draft["plain_text"] = plain_text
        draft["updated_by"] = "consumer"
        return dict(draft)

    async def insert_candidate_version(self, workspace_id: str, task_id: str, plain_text: str, document: dict, *, prompt_version: str) -> dict:
        version_id = str(uuid4())
        self.versions[version_id] = {
            "content_version_id": version_id,
            "task_id": task_id,
            "workspace_id": workspace_id,
            "content_type": "master_revised",
            "version_number": len(self.versions) + 1,
            "content": plain_text,
            "structured_blocks": document.get("blocks", []),
            "created_by_type": "model",
            "approval_status": "not_required",
            "immutable_hash": "hash-" + version_id[:8],
            "prompt_version": prompt_version,
        }
        return dict(self.versions[version_id])

    async def get_version(self, workspace_id: str, version_id: str) -> dict | None:
        version = self.versions.get(version_id)
        return dict(version) if version and version["workspace_id"] == workspace_id else None

    async def insert_snapshot_version(self, workspace_id: str, task_id: str, document: dict, plain_text: str, revision: int) -> dict:
        version_id = str(uuid4())
        self.blocks[version_id] = [dict(b) for b in document.get("blocks", [])]
        self.versions[version_id] = {
            "content_version_id": version_id,
            "task_id": task_id,
            "workspace_id": workspace_id,
            "content_type": "master_draft",
            "version_number": len(self.versions) + 1,
            "content": plain_text,
            "structured_blocks": [dict(b) for b in document.get("blocks", [])],
            "created_by_type": "human",
            "approval_status": "not_required",
            "immutable_hash": "hash-" + version_id[:8],
            "base_revision": revision,
        }
        return dict(self.versions[version_id])

    async def set_active_version(self, workspace_id: str, task_id: str, version_id: str, revision: int) -> None:
        self.drafts.setdefault(task_id, {"workspace_id": workspace_id})["last_snapshot_version_id"] = version_id

    async def get_draft_snapshot_version(self, workspace_id: str, task_id: str, revision: int) -> dict | None:
        for version in self.versions.values():
            if (
                version["workspace_id"] == workspace_id
                and version["task_id"] == task_id
                and version["content_type"] == "master_draft"
                and version.get("base_revision") == revision
            ):
                return dict(version)
        return None

    async def append_event(self, event: dict) -> None:
        pass


class StubCandidateGenerator:
    """Deterministic candidate producer standing in for the LLM workflow."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(self, *, core_idea: str, intent: str, excerpts: list[dict], base_revision: int, usage_out: dict | None = None) -> dict:
        self.calls.append({"core_idea": core_idea, "excerpts": excerpts, "base_revision": base_revision})
        if usage_out is not None:
            usage_out.update({"input_tokens": 100, "output_tokens": 100, "model": "stub"})
        return {
            "blocks": [
                {"block_id": "b1", "block_type": "heading", "text": core_idea},
                {"block_id": "b2", "block_type": "paragraph", "text": "开头。"},
                {"block_id": "b3", "block_type": "paragraph", "text": (excerpts[0]["excerpt_text"] + " ") if excerpts else "正文。"},
            ],
            "plain_text": core_idea + "\n开头。\n正文。",
        }


@pytest.mark.asyncio
async def test_new_project_creates_draft_with_revision_zero() -> None:
    project_store = MemoryProjectStore()
    draft_store = MemoryDraftStore()
    projects = ConsumerProjectService(store=project_store)
    drafts = DraftService(store=draft_store)
    principal = principal_for("ws-1")
    created = await projects.create_project(principal, title="t", core_idea="c", intent="i")
    draft = await drafts.get_or_create_draft(principal, created["task_id"])
    assert draft["revision"] == 0
    assert draft["document"]["blocks"]


@pytest.mark.asyncio
async def test_autosave_bumps_revision_and_never_creates_content_version() -> None:
    draft_store = MemoryDraftStore()
    drafts = DraftService(store=draft_store)
    principal = principal_for("ws-1")
    await draft_store.ensure_draft("ws-1", "task-1")
    saved = await drafts.autosave(principal, "task-1", {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": "新文本"}]}, "新文本", expected_revision=0)
    assert saved["revision"] == 1
    # autosave writes no content_version rows at all
    assert draft_store.versions == {}


@pytest.mark.asyncio
async def test_base_revision_mismatch_returns_409_without_overwriting() -> None:
    draft_store = MemoryDraftStore()
    drafts = DraftService(store=draft_store)
    principal = principal_for("ws-1")
    await draft_store.ensure_draft("ws-1", "task-1")
    first = await drafts.autosave(principal, "task-1", {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": "第一版"}]}, "第一版", expected_revision=0)
    assert first["revision"] == 1
    stale = await drafts.autosave(principal, "task-1", {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": "过期编辑"}]}, "过期编辑", expected_revision=0)
    # the stale write must be rejected, server draft untouched
    assert stale is None
    current = await drafts.get_or_create_draft(principal, "task-1")
    assert current["plain_text"] == "第一版"
    assert current["revision"] == 1


@pytest.mark.asyncio
async def test_generate_draft_uses_core_idea_excerpts_and_base_revision() -> None:
    project_store = MemoryProjectStore()
    draft_store = MemoryDraftStore()
    generator = StubCandidateGenerator()
    projects = ConsumerProjectService(store=project_store)
    service = DraftGenerationService(store=draft_store, generator=generator, projects=projects)
    principal = principal_for("ws-1")
    created = await projects.create_project(principal, title="t", core_idea="观点A", intent="i")
    await project_store.link_excerpt("ws-1", created["task_id"], "ex-1")
    project_store.excerpts["ws-1"] = [{"excerpt_id": "ex-1", "summary": "s", "excerpt_text": "素材原文", "excerpt_type": "quote", "document_id": "d1", "provenance_hash": "h" * 64}]
    await draft_store.ensure_draft("ws-1", created["task_id"])
    result = await service.generate(principal, created["task_id"])
    assert generator.calls[0]["core_idea"] == "观点A"
    assert generator.calls[0]["excerpts"][0]["excerpt_id"] == "ex-1"
    # candidate is persisted as a version, but the live draft is not yet touched
    assert result["candidate"]["content_type"] == "master_revised"
    draft = await draft_store.get_draft("ws-1", created["task_id"])
    assert draft["plain_text"] == ""


@pytest.mark.asyncio
async def test_generate_refuses_to_apply_when_revision_moved() -> None:
    project_store = MemoryProjectStore()
    draft_store = MemoryDraftStore()
    generator = StubCandidateGenerator()
    projects = ConsumerProjectService(store=project_store)
    service = DraftGenerationService(store=draft_store, generator=generator, projects=projects)
    principal = principal_for("ws-1")
    created = await projects.create_project(principal, title="t", core_idea="c", intent="i")
    await draft_store.ensure_draft("ws-1", created["task_id"])
    result = await service.generate(principal, created["task_id"])
    # user typed during generation: revision 0 -> 1
    await draft_store.save_draft("ws-1", created["task_id"], {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": "用户打断"}]}, "用户打断", 0)
    applied = await service.apply_candidate(principal, created["task_id"], result["candidate"]["content_version_id"], base_revision=result["base_revision"])
    assert applied is None, "apply must be rejected when the draft revision moved"
    draft = await draft_store.get_draft("ws-1", created["task_id"])
    assert draft["plain_text"] == "用户打断"


@pytest.mark.asyncio
async def test_apply_candidate_replaces_draft_via_compare_and_swap() -> None:
    project_store = MemoryProjectStore()
    draft_store = MemoryDraftStore()
    projects = ConsumerProjectService(store=project_store)
    service = DraftGenerationService(store=draft_store, generator=StubCandidateGenerator(), projects=projects)
    principal = principal_for("ws-1")
    created = await projects.create_project(principal, title="t", core_idea="观点A", intent="i")
    await draft_store.ensure_draft("ws-1", created["task_id"])
    result = await service.generate(principal, created["task_id"])
    applied = await service.apply_candidate(principal, created["task_id"], result["candidate"]["content_version_id"], base_revision=result["base_revision"])
    assert applied["revision"] == result["base_revision"] + 1
    assert applied["plain_text"] == result["candidate"]["content"]


@pytest.mark.asyncio
async def test_adopt_creates_immutable_snapshot_and_is_idempotent_per_revision() -> None:
    project_store = MemoryProjectStore()
    draft_store = MemoryDraftStore()
    drafts = DraftService(store=draft_store)
    principal = principal_for("ws-1")
    created = await ConsumerProjectService(store=project_store).create_project(principal, title="t", core_idea="c", intent="i")
    await draft_store.ensure_draft("ws-1", created["task_id"])
    saved = await drafts.autosave(principal, created["task_id"], {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": "定稿"}]}, "定稿", expected_revision=0)
    first = await drafts.adopt(principal, created["task_id"], base_revision=saved["revision"])
    assert first["version"]["content_type"] == "master_draft"
    assert first["version"]["created_by_type"] == "human"
    assert first["version"]["structured_blocks"][0]["text"] == "定稿"
    # adopting the same revision again is idempotent: no duplicate version
    second = await drafts.adopt(principal, created["task_id"], base_revision=saved["revision"])
    assert second["version"]["content_version_id"] == first["version"]["content_version_id"]
    assert len(draft_store.versions) == 1


@pytest.mark.asyncio
async def test_adopt_with_stale_revision_conflicts() -> None:
    project_store = MemoryProjectStore()
    draft_store = MemoryDraftStore()
    drafts = DraftService(store=draft_store)
    principal = principal_for("ws-1")
    created = await ConsumerProjectService(store=project_store).create_project(principal, title="t", core_idea="c", intent="i")
    await draft_store.ensure_draft("ws-1", created["task_id"])
    await drafts.autosave(principal, created["task_id"], {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": "v1"}]}, "v1", expected_revision=0)
    with pytest.raises(ConflictError):
        await drafts.adopt(principal, created["task_id"], base_revision=0)


# ---------------------------------------------------------------------------
# HTTP layer contract tests
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from agent_api.api.main import create_app  # noqa: E402


class FakeTasks:
    async def bootstrap_workspace(self, principal):
        return {"workspace_id": principal.workspace_id, "role": principal.role}

    async def list_tasks(self, principal):
        return []

    async def ready(self):
        return True


class FakeVerifier:
    async def verify(self, token: str) -> Principal:
        if token != "valid-token":
            raise ValueError("invalid token")
        return Principal(user_id="consumer-1", workspace_id="00000000-0000-0000-0000-000000000001", role="admin", experience="personal")


class FakeKnowledge:
    async def product_facts(self, workspace_id): return []
    async def brand_guidelines(self, workspace_id): return []
    async def channel_guidelines(self, workspace_id): return []
    async def approved_content(self, workspace_id): return []
    async def forbidden_claims(self, workspace_id): return []


class ConsumerAppsStub:
    """Bundle matching the ConsumerProjectsApp protocol, backed by memory stores."""

    def __init__(self) -> None:
        self.project_store = MemoryProjectStore()
        self.draft_store = MemoryDraftStore()
        self.projects = ConsumerProjectService(store=self.project_store)
        self.drafts = DraftService(store=self.draft_store)
        self.generation = DraftGenerationService(store=self.draft_store, generator=StubCandidateGenerator(), projects=self.projects)
        self.usage_ledger = MemoryLedgerStub()


class MemoryLedgerStub:
    """No-op usage ledger for HTTP tests; drafts never touch it."""

    def __init__(self) -> None:
        self.exhausted = False

    async def reserve(self, principal, *, request_id: str, operation: str, estimated_tokens: int) -> dict:
        if self.exhausted:
            from agent_api.application.usage import QuotaExceeded

            raise QuotaExceeded()
        return {"state": "reserved", "replayed": False}

    async def settle(self, principal, *, request_id: str, operation: str, input_tokens, output_tokens, model) -> dict:
        return {"state": "settled", "replayed": False}

    async def refund(self, principal, *, request_id: str, reason: str) -> dict:
        return {"state": "refunded", "replayed": False}

    async def usage_summary(self, principal) -> dict:
        return {"workspace_id": principal.workspace_id, "used": 0, "quota": 30000}


def http_client(apps: ConsumerAppsStub) -> TestClient:
    app = create_app(
        tasks=FakeTasks(),
        verifier=FakeVerifier(),
        knowledge=FakeKnowledge(),
        consumer_apps=apps,
    )
    return TestClient(app)


def test_projects_require_authentication() -> None:
    client = http_client(ConsumerAppsStub())
    response = client.get("/api/v1/consumer/projects")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_create_project_get_and_roundtrip() -> None:
    apps = ConsumerAppsStub()
    client = http_client(apps)
    created = client.post(
        "/api/v1/consumer/projects",
        json={"title": "Nova 发布", "core_idea": "讲清楚价值", "writing_intent": "公众号"},
        headers={"Authorization": "Bearer valid-token"},
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["data"]["task_id"]

    fetched = client.get(f"/api/v1/consumer/projects/{task_id}", headers={"Authorization": "Bearer valid-token"})
    assert fetched.status_code == 200
    assert fetched.json()["data"]["title"] == "Nova 发布"

    patched = client.patch(
        f"/api/v1/consumer/projects/{task_id}",
        json={"core_idea": "新观点"},
        headers={"Authorization": "Bearer valid-token"},
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["core_idea"] == "新观点"
    assert patched.json()["data"]["title"] == "Nova 发布"


def test_cross_workspace_project_returns_404() -> None:
    apps = ConsumerAppsStub()
    client = http_client(apps)
    created = client.post(
        "/api/v1/consumer/projects",
        json={"title": "t", "core_idea": "c", "writing_intent": ""},
        headers={"Authorization": "Bearer valid-token"},
    )
    task_id = created.json()["data"]["task_id"]
    # another principal (different workspace) must not see it
    class OtherVerifier(FakeVerifier):
        async def verify(self, token: str) -> Principal:
            return Principal(user_id="consumer-2", workspace_id="00000000-0000-0000-0000-000000000002", role="admin", experience="personal")

    other_app = create_app(tasks=FakeTasks(), verifier=OtherVerifier(), knowledge=FakeKnowledge(), consumer_apps=apps)
    other_client = TestClient(other_app)
    response = other_client.get(f"/api/v1/consumer/projects/{task_id}", headers={"Authorization": "Bearer valid-token"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_draft_autosave_conflict_returns_409_envelope() -> None:
    apps = ConsumerAppsStub()
    client = http_client(apps)
    created = client.post(
        "/api/v1/consumer/projects",
        json={"title": "t", "core_idea": "c", "writing_intent": ""},
        headers={"Authorization": "Bearer valid-token"},
    )
    task_id = created.json()["data"]["task_id"]
    headers = {"Authorization": "Bearer valid-token"}
    document = {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": "第一版"}]}
    first = client.put(f"/api/v1/consumer/projects/{task_id}/draft", json={"document": document, "plainText": "第一版", "baseRevision": 0}, headers=headers)
    assert first.status_code == 200
    assert first.json()["data"]["revision"] == 1
    stale = client.put(f"/api/v1/consumer/projects/{task_id}/draft", json={"document": document, "plainText": "过期", "baseRevision": 0}, headers=headers)
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "REVISION_CONFLICT"


def test_generate_and_apply_candidate_over_http() -> None:
    apps = ConsumerAppsStub()
    client = http_client(apps)
    created = client.post(
        "/api/v1/consumer/projects",
        json={"title": "t", "core_idea": "观点A", "writing_intent": ""},
        headers={"Authorization": "Bearer valid-token"},
    )
    task_id = created.json()["data"]["task_id"]
    headers = {"Authorization": "Bearer valid-token"}
    generated = client.post(f"/api/v1/consumer/projects/{task_id}/draft/generate", headers={**headers, "Idempotency-Key": "draft-gen-key-000001"})
    assert generated.status_code == 200, generated.text
    candidate_id = generated.json()["data"]["candidate"]["content_version_id"]
    applied = client.post(
        f"/api/v1/consumer/projects/{task_id}/draft/apply-candidate",
        json={"contentVersionId": candidate_id, "baseRevision": 0},
        headers=headers,
    )
    assert applied.status_code == 200
    assert applied.json()["data"]["revision"] == 1


def test_quota_exhausted_blocks_generation_but_not_saving() -> None:
    apps = ConsumerAppsStub()
    apps.usage_ledger.exhausted = True
    client = http_client(apps)
    created = client.post(
        "/api/v1/consumer/projects",
        json={"title": "t", "core_idea": "c", "writing_intent": ""},
        headers={"Authorization": "Bearer valid-token"},
    )
    task_id = created.json()["data"]["task_id"]
    headers = {"Authorization": "Bearer valid-token"}

    # AI generation is rejected BEFORE the model runs
    blocked = client.post(f"/api/v1/consumer/projects/{task_id}/draft/generate", headers={**headers, "Idempotency-Key": "draft-gen-key-000002"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "QUOTA_EXCEEDED"

    # manual draft saving is untouched by quota
    saved = client.put(
        f"/api/v1/consumer/projects/{task_id}/draft",
        json={"document": {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": "手工编辑"}]}, "plainText": "手工编辑", "baseRevision": 0},
        headers=headers,
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["revision"] == 1
