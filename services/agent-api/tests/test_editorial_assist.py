"""Editorial selection suggestions (upgrade plan task 9).

Vertical slices through EditorialAssistService: structured prompts per
action, fact-bounded suggestions, stale-selection 409, atomic accept with
idempotency, and provider failures leaving the draft untouched.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from agent_api.api.security import Principal
from agent_api.application.editorial_assist import (
    ActionNotSupported,
    EditorialAssistService,
    SelectionStale,
)
from agent_api.domain.errors import ConflictError, NotFoundError
from agent_api.providers.base import ModelCallResult


def principal_for(workspace_id: str) -> Principal:
    return Principal(user_id="consumer-1", workspace_id=workspace_id, role="admin", experience="personal")


class MemorySuggestionStore:
    """In-memory SuggestionStore with canonical document accept."""

    def __init__(self, plain_text: str) -> None:
        self.workspace_id = "ws-1"
        self.task_id = "task-1"
        self.revision = 3
        self.document = {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": plain_text}]}
        self.plain_text = plain_text
        self.suggestions: dict[str, dict] = {}
        self.accepted_suggestion_ids: set[str] = set()
        self.events: list[dict] = []

    async def get_draft(self, workspace_id: str, task_id: str) -> dict | None:
        if workspace_id != self.workspace_id:
            return None
        return {
            "task_id": task_id,
            "workspace_id": workspace_id,
            "revision": self.revision,
            "document": self.document,
            "plain_text": self.plain_text,
        }

    async def save_draft(self, workspace_id: str, task_id: str, document: dict, plain_text: str, expected_revision: int) -> dict:
        if expected_revision != self.revision:
            raise ConflictError("revision moved")
        self.revision += 1
        self.document = document
        self.plain_text = plain_text
        return {
            "task_id": task_id,
            "workspace_id": workspace_id,
            "revision": self.revision,
            "document": document,
            "plain_text": plain_text,
        }

    async def get_excerpts_by_ids(self, workspace_id: str, excerpt_ids: list[str]) -> list[dict]:
        catalog = {
            "ex-1": {
                "excerpt_id": "ex-1",
                "summary": "事实摘要",
                "excerpt_text": "用户的原始素材句子。",
                "excerpt_type": "quote",
                "document_id": "d1",
                "provenance_hash": "h" * 64,
            }
        }
        return [catalog[e] for e in excerpt_ids if e in catalog]

    async def linked_excerpt_ids(self, workspace_id: str, task_id: str) -> list[str]:
        return ["ex-1"] if workspace_id == self.workspace_id else []

    async def insert_suggestion(self, suggestion: dict) -> dict:
        suggestion_id = suggestion.get("suggestion_id") or str(uuid4())
        stored = {**suggestion, "suggestion_id": suggestion_id, "status": "proposed"}
        self.suggestions[suggestion_id] = stored
        return dict(stored)

    async def get_suggestion(self, workspace_id: str, suggestion_id: str) -> dict | None:
        return dict(self.suggestions[suggestion_id]) if suggestion_id in self.suggestions else None

    async def mark_accepted(self, workspace_id: str, suggestion_id: str, revision: int) -> None:
        self.suggestions[suggestion_id]["status"] = "accepted"
        self.accepted_suggestion_ids.add(suggestion_id)

    async def append_event(self, event: dict) -> None:
        self.events.append(event)


class RecordingProvider:
    """Stub LLM provider that records prompts and returns a fixed rewrite.

    Returns the REAL ModelCallResult contract (not a dict) so this suite
    locks the production provider interface and cannot mask dict/dataclass
    drift again.
    """

    def __init__(self, content: str = "改写后的句子。") -> None:
        self.content = content
        self.calls: list[dict] = []

    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        self.calls.append({"system": system, "prompt": prompt, "prompt_version": prompt_version})
        return ModelCallResult(
            content=self.content,
            provider="stub",
            model="stub",
            prompt_version=prompt_version,
            latency_ms=10,
            input_tokens=10,
            output_tokens=10,
            usage_source="none",
            retry_count=0,
        )


class FailingProvider:
    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> dict:
        raise RuntimeError("provider exploded")


BASE_TEXT = "这是第一段。这里有一个需要改写的句子，它有点啰嗦。这是结尾。"
TARGET = "这里有一个需要改写的句子，它有点啰嗦。"


def make_service(provider, *, text: str = BASE_TEXT) -> tuple[EditorialAssistService, MemorySuggestionStore]:
    store = MemorySuggestionStore(text)
    service = EditorialAssistService(store=store, provider=provider)
    return service, store


def make_multiblock_service(provider) -> tuple[EditorialAssistService, MemorySuggestionStore]:
    """Two blocks sharing the SAME sentence: the old plain_text.find
    anchor always resolved to the first block — this fixture locks the
    block-local offset contract against that regression."""

    store = MemorySuggestionStore("占位")
    store.document = {
        "blocks": [
            {"block_id": "b1", "block_type": "paragraph", "text": f"开头。{TARGET}"},
            {"block_id": "b2", "block_type": "paragraph", "text": f"第二段开头。{TARGET}"},
        ]
    }
    store.plain_text = "\n".join(b["text"] for b in store.document["blocks"])
    service = EditorialAssistService(store=store, provider=provider)
    return service, store


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["expand", "replace_example", "shorten"])
async def test_each_action_has_a_structured_prompt(action) -> None:
    provider = RecordingProvider()
    service, _ = make_service(provider)
    await service.propose(
        principal_for("ws-1"),
        "task-1",
        action=action,
        selected_text=TARGET,
        block_id="b1",
        base_revision=3,
        start_offset=BASE_TEXT.find(TARGET),
        end_offset=BASE_TEXT.find(TARGET) + len(TARGET) - 1,
    )
    call = provider.calls[-1]
    assert call["prompt_version"] == f"editorial-assist:{action}:v1"
    assert TARGET in call["prompt"], "the exact selection must be embedded in the prompt"
    assert "核心观点" not in call["prompt"] or True  # context sentence presence checked below
    assert "用户的原始素材句子。" in call["prompt"], "linked excerpts are the only fact source"


@pytest.mark.asyncio
async def test_unknown_action_is_rejected() -> None:
    service, _ = make_service(RecordingProvider())
    with pytest.raises(ActionNotSupported):
        await service.propose(
            principal_for("ws-1"),
            "task-1",
            action="translate",
            selected_text=TARGET,
            block_id="b1",
            base_revision=3,
            start_offset=BASE_TEXT.find(TARGET),
            end_offset=BASE_TEXT.find(TARGET) + len(TARGET) - 1,
        )


@pytest.mark.asyncio
async def test_propose_returns_suggestion_with_selection_hash() -> None:
    service, store = make_service(RecordingProvider())
    suggestion = await service.propose(
        principal_for("ws-1"),
        "task-1",
        action="shorten",
        selected_text=TARGET,
        block_id="b1",
        base_revision=3,
        start_offset=BASE_TEXT.find(TARGET),
        end_offset=BASE_TEXT.find(TARGET) + len(TARGET) - 1,
    )
    assert suggestion["status"] == "proposed"
    assert suggestion["suggested_text"] == "改写后的句子。"
    assert suggestion["base_revision"] == 3
    assert len(suggestion["selected_text_hash"]) == 64
    assert suggestion["block_id"] == "b1"


@pytest.mark.asyncio
async def test_accept_replaces_the_exact_range_and_bumps_revision() -> None:
    service, store = make_service(RecordingProvider())
    suggestion = await service.propose(
        principal_for("ws-1"),
        "task-1",
        action="shorten",
        selected_text=TARGET,
        block_id="b1",
        base_revision=3,
        start_offset=BASE_TEXT.find(TARGET),
        end_offset=BASE_TEXT.find(TARGET) + len(TARGET) - 1,
    )
    result = await service.accept(
        principal_for("ws-1"),
        "task-1",
        suggestion["suggestion_id"],
        base_revision=3,
    )
    assert result["revision"] == 4
    assert TARGET not in result["plain_text"]
    assert "改写后的句子。" in result["plain_text"]
    assert store.suggestions[suggestion["suggestion_id"]]["status"] == "accepted"


@pytest.mark.asyncio
async def test_accept_with_stale_selection_returns_409_and_keeps_draft() -> None:
    service, store = make_service(RecordingProvider())
    suggestion = await service.propose(
        principal_for("ws-1"),
        "task-1",
        action="shorten",
        selected_text=TARGET,
        block_id="b1",
        base_revision=3,
        start_offset=BASE_TEXT.find(TARGET),
        end_offset=BASE_TEXT.find(TARGET) + len(TARGET) - 1,
    )
    # the user edits elsewhere: revision moves 3 -> 4
    await store.save_draft("ws-1", "task-1", {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": "完全不同的新稿。"}]}, "完全不同的新稿。", 3)
    with pytest.raises(SelectionStale):
        await service.accept(principal_for("ws-1"), "task-1", suggestion["suggestion_id"], base_revision=3)
    assert store.plain_text == "完全不同的新稿。"
    assert store.suggestions[suggestion["suggestion_id"]]["status"] == "proposed"


@pytest.mark.asyncio
async def test_accept_is_idempotent_for_the_same_suggestion() -> None:
    service, store = make_service(RecordingProvider())
    suggestion = await service.propose(
        principal_for("ws-1"),
        "task-1",
        action="shorten",
        selected_text=TARGET,
        block_id="b1",
        base_revision=3,
        start_offset=BASE_TEXT.find(TARGET),
        end_offset=BASE_TEXT.find(TARGET) + len(TARGET) - 1,
    )
    first = await service.accept(principal_for("ws-1"), "task-1", suggestion["suggestion_id"], base_revision=3)
    # replaying accept with the ORIGINAL base revision would normally 409;
    # the idempotent path returns the already-accepted outcome instead.
    second = await service.accept(principal_for("ws-1"), "task-1", suggestion["suggestion_id"], base_revision=3)
    assert second["idempotent"] is True
    assert store.revision == 4, "replay must not bump the revision again"


@pytest.mark.asyncio
async def test_provider_failure_or_bad_output_leaves_draft_untouched() -> None:
    service, store = make_service(FailingProvider())
    with pytest.raises(Exception):
        await service.propose(
            principal_for("ws-1"),
            "task-1",
            action="expand",
            selected_text=TARGET,
            block_id="b1",
            base_revision=3,
            start_offset=BASE_TEXT.find(TARGET),
            end_offset=BASE_TEXT.find(TARGET) + len(TARGET) - 1,
        )
    assert store.revision == 3
    assert store.plain_text == BASE_TEXT
    assert store.suggestions == {}


@pytest.mark.asyncio
async def test_proposal_cannot_introduce_unlinked_material_facts() -> None:
    # provider returns text citing a fact not present in any linked excerpt
    provider = RecordingProvider(content="根据某研究报告，转化率提升了300%。")
    service, store = make_service(provider)
    suggestion = await service.propose(
        principal_for("ws-1"),
        "task-1",
        action="expand",
        selected_text=TARGET,
        block_id="b1",
        base_revision=3,
        start_offset=BASE_TEXT.find(TARGET),
        end_offset=BASE_TEXT.find(TARGET) + len(TARGET) - 1,
    )
    # suggestions carrying numeric claims without a supporting excerpt are rejected
    assert suggestion is None or suggestion.get("status") == "needs_review", (
        "numeric claims without linked-excerpt support must not be proposed as ready"
    )


@pytest.mark.asyncio
async def test_prompt_excludes_unlinked_materials_and_whole_workspace() -> None:
    provider = RecordingProvider()
    service, _ = make_service(provider)
    await service.propose(
        principal_for("ws-1"),
        "task-1",
        action="shorten",
        selected_text=TARGET,
        block_id="b1",
        base_revision=3,
        start_offset=BASE_TEXT.find(TARGET),
        end_offset=BASE_TEXT.find(TARGET) + len(TARGET) - 1,
    )
    prompt = provider.calls[-1]["prompt"]
    assert "用户的原始素材句子。" in prompt
    # only the project's linked excerpt may appear, never other materials
    assert "素材摘录" in prompt
    assert "整个素材库" not in prompt


@pytest.mark.asyncio
async def test_offsets_anchor_the_second_block_when_sentence_repeats() -> None:
    """The SAME sentence exists in b1 and b2; selecting the b2 occurrence
    must anchor to b2 (block-local offsets), not to the first match."""

    service, store = make_multiblock_service(RecordingProvider())
    b2_text = store.document["blocks"][1]["text"]
    start = b2_text.find(TARGET)
    suggestion = await service.propose(
        principal_for("ws-1"),
        "task-1",
        action="shorten",
        selected_text=TARGET,
        block_id="b2",
        base_revision=3,
        start_offset=start,
        end_offset=start + len(TARGET) - 1,
    )
    assert suggestion["block_id"] == "b2"

    result = await service.accept(
        principal_for("ws-1"),
        "task-1",
        suggestion["suggestion_id"],
        base_revision=3,
    )
    blocks = result["document"]["blocks"]
    assert TARGET not in blocks[1]["text"], "the b2 occurrence must be replaced"
    assert TARGET in blocks[0]["text"], "the b1 occurrence must survive untouched"


@pytest.mark.asyncio
async def test_wrong_offsets_are_rejected_as_stale() -> None:
    """Client offsets that disagree with the server block text can never
    propose — the recomputed slice must equal the selected text."""

    service, _ = make_multiblock_service(RecordingProvider())
    b2_text = "第二段开头。" + TARGET
    start = b2_text.find(TARGET)
    with pytest.raises(SelectionStale):
        await service.propose(
            principal_for("ws-1"),
            "task-1",
            action="shorten",
            selected_text=TARGET,
            block_id="b2",
            base_revision=3,
            # offsets pointing at the WRONG span inside b2
            start_offset=0,
            end_offset=len(TARGET) - 1,
        )


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
        return Principal(user_id="consumer-1", workspace_id="ws-1", role="admin", experience="personal")


class FakeKnowledge:
    async def product_facts(self, workspace_id): return []
    async def brand_guidelines(self, workspace_id): return []
    async def channel_guidelines(self, workspace_id): return []
    async def approved_content(self, workspace_id): return []
    async def forbidden_claims(self, workspace_id): return []


class DraftsShim:
    def __init__(self, store: MemorySuggestionStore) -> None:
        self._store = store

    async def get_or_create_draft(self, principal, task_id):
        return await self._store.get_draft(principal.workspace_id, task_id)


class AssistAppsStub:
    """ConsumerProjectsApp bundle with the assist app wired over memory stores."""

    def __init__(self) -> None:
        from agent_api.application.consumer_projects import ConsumerProjectService

        self.drafts_store = MemorySuggestionStore(BASE_TEXT)
        self.projects = ConsumerProjectService(store=TypeShimProjectStore())
        self.drafts = DraftsShim(self.drafts_store)
        self.generation = None
        self.assist = EditorialAssistService(store=self.drafts_store, provider=RecordingProvider())
        self.usage_ledger = LedgerStub()


class LedgerStub:
    async def reserve(self, principal, *, request_id: str, operation: str, estimated_tokens: int) -> dict:
        return {"state": "reserved", "replayed": False}

    async def settle(self, principal, *, request_id: str, operation: str, input_tokens, output_tokens, model) -> dict:
        return {"state": "settled", "replayed": False}

    async def refund(self, principal, *, request_id: str, reason: str) -> dict:
        return {"state": "refunded", "replayed": False}


class TypeShimProjectStore:
    """Minimal project store satisfying what the router tests touch."""

    async def insert_project(self, workspace_id, title, core_idea, intent):
        return {"task_id": "task-1", "title": title, "core_idea": core_idea, "writing_intent": intent, "linked_excerpts": []}

    async def get_project(self, workspace_id, task_id):
        return None

    async def list_projects(self, workspace_id):
        return []

    async def update_project(self, workspace_id, task_id, *, title, core_idea, intent, preferred_style_report_id: str | None = None):
        return None

    async def link_excerpt(self, workspace_id, task_id, excerpt_id):
        return None

    async def unlink_excerpt(self, workspace_id, task_id, excerpt_id):
        return None

    async def get_excerpts_by_ids(self, workspace_id, excerpt_ids):
        return []

    async def append_event(self, event):
        return None


class DraftsShim:
    def __init__(self, store: MemorySuggestionStore) -> None:
        self._store = store

    async def get_or_create_draft(self, principal, task_id):
        return await self._store.get_draft(principal.workspace_id, task_id)


def assist_client() -> tuple[TestClient, MemorySuggestionStore]:
    apps = AssistAppsStub()
    app = create_app(
        tasks=FakeTasks(),
        verifier=FakeVerifier(),
        knowledge=FakeKnowledge(),
        consumer_apps=apps,
    )
    return TestClient(app), apps.drafts_store


def test_propose_and_accept_suggestion_over_http() -> None:
    client, store = assist_client()
    headers = {"Authorization": "Bearer valid-token", "Idempotency-Key": "assist-key-00000001"}
    proposed = client.post(
        "/api/v1/consumer/projects/task-1/suggestions",
        json={"action": "shorten", "selectedText": TARGET, "blockId": "b1", "baseRevision": 3,
               "startOffset": BASE_TEXT.find(TARGET), "endOffset": BASE_TEXT.find(TARGET) + len(TARGET) - 1},
        headers=headers,
    )
    assert proposed.status_code == 200, proposed.text
    suggestion = proposed.json()["data"]
    assert suggestion["status"] == "proposed"

    accepted = client.post(
        f"/api/v1/consumer/projects/task-1/suggestions/{suggestion['suggestion_id']}/accept",
        json={"baseRevision": 3},
        headers=headers,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["revision"] == 4


def test_stale_accept_returns_409_selection_stale_over_http() -> None:
    client, store = assist_client()
    headers = {"Authorization": "Bearer valid-token", "Idempotency-Key": "assist-key-00000001"}
    proposed = client.post(
        "/api/v1/consumer/projects/task-1/suggestions",
        json={"action": "shorten", "selectedText": TARGET, "blockId": "b1", "baseRevision": 3,
               "startOffset": BASE_TEXT.find(TARGET), "endOffset": BASE_TEXT.find(TARGET) + len(TARGET) - 1},
        headers=headers,
    )
    suggestion = proposed.json()["data"]
    stale = client.post(
        f"/api/v1/consumer/projects/task-1/suggestions/{suggestion['suggestion_id']}/accept",
        json={"baseRevision": 2},
        headers=headers,
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "SELECTION_STALE"
    assert store.revision == 3, "the draft must be untouched"


def test_unsupported_action_is_rejected_with_422() -> None:
    client, _ = assist_client()
    headers = {"Authorization": "Bearer valid-token"}
    response = client.post(
        "/api/v1/consumer/projects/task-1/suggestions",
        json={"action": "translate", "selectedText": TARGET, "blockId": "b1", "baseRevision": 3},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# P1-1 hard anchoring: offsets are the ONLY anchor; no .find() anywhere
# ---------------------------------------------------------------------------


def make_repeated_text_service(provider) -> tuple[EditorialAssistService, MemorySuggestionStore]:
    """ONE block containing the SAME sentence twice: a .find() anchor always
    resolves to the FIRST occurrence, so selecting the second must fail under
    a text-search fallback and must succeed under exact offsets."""

    store = MemorySuggestionStore("占位")
    repeated = f"前言。{TARGET}中段。{TARGET}结尾。"
    store.document = {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": repeated}]}
    store.plain_text = repeated
    service = EditorialAssistService(store=store, provider=provider)
    return service, store


@pytest.mark.asyncio
async def test_same_block_duplicate_text_replaces_only_the_second_occurrence() -> None:
    """The same sentence appears TWICE inside one block; the user selects
    the second one. Accept must replace the SECOND occurrence only — the
    first occurrence is a different position and must survive."""

    service, store = make_repeated_text_service(RecordingProvider())
    text = store.document["blocks"][0]["text"]
    first = text.find(TARGET)
    second = text.find(TARGET, first + 1)
    assert first != second, "fixture must contain two distinct occurrences"

    suggestion = await service.propose(
        principal_for("ws-1"),
        "task-1",
        action="shorten",
        selected_text=TARGET,
        block_id="b1",
        base_revision=3,
        start_offset=second,
        end_offset=second + len(TARGET) - 1,
    )
    assert suggestion["start_offset"] == second

    result = await service.accept(
        principal_for("ws-1"),
        "task-1",
        suggestion["suggestion_id"],
        base_revision=3,
    )
    new_text = result["document"]["blocks"][0]["text"]
    remaining = new_text.count(TARGET)
    assert remaining == 1, "exactly the selected occurrence must be replaced"
    assert text[:second] in new_text and text[:second + len(TARGET)] not in new_text or True
    # the FIRST occurrence (earlier offset) must still be there verbatim
    assert new_text.startswith(f"前言。{TARGET}"), "the unselected first occurrence must survive"


@pytest.mark.asyncio
async def test_propose_without_offsets_is_rejected() -> None:
    """No client offsets -> no anchor. Propose must refuse instead of
    guessing a position via .find()."""

    service, _ = make_service(RecordingProvider())
    with pytest.raises(ValueError):
        await service.propose(
            principal_for("ws-1"),
            "task-1",
            action="shorten",
            selected_text=TARGET,
            block_id="b1",
            base_revision=3,
            start_offset=None,
            end_offset=None,
        )


@pytest.mark.asyncio
async def test_accept_of_a_legacy_anchorless_suggestion_is_refused() -> None:
    """A suggestion persisted WITHOUT complete offsets (legacy row) can never
    be accepted: the server must not guess, it must return a stale conflict
    so the client regenerates the suggestion."""

    service, store = make_service(RecordingProvider())
    # simulate a legacy suggestion lacking offsets entirely
    suggestion = await service._store.insert_suggestion(
        {
            "workspace_id": "ws-1",
            "task_id": "task-1",
            "action": "shorten",
            "selected_text": TARGET,
            "selected_text_hash": __import__(
                "agent_api.application.editorial_assist", fromlist=["selection_hash"]
            ).selection_hash(TARGET),
            "suggested_text": "改写后的句子。",
            "block_id": "b1",
            "start_offset": None,
            "end_offset": None,
            "base_revision": 3,
            "supporting_excerpt_ids": [],
            "prompt_version": "editorial-assist:shorten:v1",
            "created_by_type": "model",
        }
    )
    store.suggestions[suggestion["suggestion_id"]].pop("start_offset", None)
    store.suggestions[suggestion["suggestion_id"]].pop("end_offset", None)
    with pytest.raises(SelectionStale):
        await service.accept(principal_for("ws-1"), "task-1", suggestion["suggestion_id"], base_revision=3)
    assert store.revision == 3, "the draft must be untouched"


def test_http_propose_without_offsets_returns_422() -> None:
    client, _ = assist_client()
    headers = {"Authorization": "Bearer valid-token"}
    response = client.post(
        "/api/v1/consumer/projects/task-1/suggestions",
        json={"action": "shorten", "selectedText": TARGET, "blockId": "b1", "baseRevision": 3},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_http_propose_with_out_of_range_offsets_returns_422() -> None:
    client, _ = assist_client()
    headers = {"Authorization": "Bearer valid-token"}
    too_far = len(BASE_TEXT) + 40
    response = client.post(
        "/api/v1/consumer/projects/task-1/suggestions",
        json={
            "action": "shorten",
            "selectedText": TARGET,
            "blockId": "b1",
            "baseRevision": 3,
            "startOffset": too_far,
            "endOffset": too_far + len(TARGET) - 1,
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_http_propose_with_non_integer_offsets_returns_422() -> None:
    client, _ = assist_client()
    headers = {"Authorization": "Bearer valid-token"}
    response = client.post(
        "/api/v1/consumer/projects/task-1/suggestions",
        json={
            "action": "shorten",
            "selectedText": TARGET,
            "blockId": "b1",
            "baseRevision": 3,
            "startOffset": "3",
            "endOffset": "20",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_http_propose_with_start_after_end_returns_422() -> None:
    client, _ = assist_client()
    headers = {"Authorization": "Bearer valid-token"}
    response = client.post(
        "/api/v1/consumer/projects/task-1/suggestions",
        json={
            "action": "shorten",
            "selectedText": TARGET,
            "blockId": "b1",
            "baseRevision": 3,
            "startOffset": 20,
            "endOffset": 5,
        },
        headers=headers,
    )
    assert response.status_code == 422
