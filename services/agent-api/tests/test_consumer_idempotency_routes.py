"""P1-2 idempotency contract at the ROUTE layer.

Every consumer model-costing endpoint (draft generate, suggestion propose,
variants generate, variant regenerate) must:

- REJECT requests without an Idempotency-Key header (422) — the server
  never invents a request id, because a network retry under a fresh random
  id would double-call the provider and double-charge the ledger;
- reuse the ledger entry for a replayed key: the provider runs ONCE, the
  ledger keeps ONE row, the replay returns the first outcome.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_api.api.main import create_app
from agent_api.api.security import Principal
from agent_api.providers.base import ModelCallResult


AUTH = {"Authorization": "Bearer valid-token"}

TASK_ID = "00000000-0000-0000-0000-00000000task"


class FakeVerifier:
    async def verify(self, token: str) -> Principal:
        if token != "valid-token":
            raise ValueError("invalid token")
        return Principal(user_id="consumer-1", workspace_id="ws-1", role="admin", experience="personal")


class FakeTasks:
    async def bootstrap_workspace(self, principal):
        return {"workspace_id": principal.workspace_id, "role": principal.role}

    async def list_tasks(self, principal):
        return []

    async def ready(self):
        return True


class FakeKnowledge:
    async def product_facts(self, workspace_id): return []
    async def brand_guidelines(self, workspace_id): return []
    async def channel_guidelines(self, workspace_id): return []
    async def approved_content(self, workspace_id): return []
    async def forbidden_claims(self, workspace_id): return []


class RecordingLedger:
    """Ledger stub that records (request_id, phase) — replays must not
    re-reserve, re-settle or re-refund the same key."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self._entries: dict[str, str] = {}

    async def reserve(self, principal, *, request_id, operation, estimated_tokens) -> dict:
        self.events.append((request_id, "reserve"))
        if request_id in self._entries:
            return {"state": self._entries[request_id], "replayed": True}
        self._entries[request_id] = "reserved"
        return {"state": "reserved", "replayed": False}

    async def settle(self, principal, *, request_id, operation, input_tokens, output_tokens, model) -> dict:
        self.events.append((request_id, "settle"))
        self._entries[request_id] = "settled"
        return {"state": "settled", "replayed": False}

    async def refund(self, principal, *, request_id, reason) -> dict:
        self.events.append((request_id, "refund"))
        self._entries[request_id] = "refunded"
        return {"state": "refunded", "replayed": False}


class CountingProvider:
    """Provider stub counting model invocations per operation."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        self.calls.append(prompt_version)
        return ModelCallResult(
            content="生成结果。",
            provider="stub",
            model="stub",
            prompt_version=prompt_version,
            latency_ms=5,
            input_tokens=10,
            output_tokens=10,
            usage_source="none",
            retry_count=0,
        )


DRAFT_DOCUMENT = {
    "task_id": TASK_ID,
    "revision": 2,
    "document": {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": "这里有一个需要改写的句子。"}]},
    "plain_text": "这里有一个需要改写的句子。",
}


class DraftsShim:
    def __init__(self, draft: dict) -> None:
        self._draft = draft

    async def get_or_create_draft(self, principal, task_id):
        return self._draft

    async def autosave(self, principal, task_id, document, plain_text, *, expected_revision):
        return self._draft


def make_client():
    ledger = RecordingLedger()
    provider = CountingProvider()

    class GenerationApp:
        @staticmethod
        async def generate(principal, task_id, *, usage_out=None):
            await provider.generate(system="s", prompt="p", prompt_version="draft-generation")
            candidate = {"content_version_id": "cv-1", "task_id": task_id, "content": "初稿", "base_revision": 2}
            GenerationApp._generated["candidate"] = candidate
            return {"candidate": candidate, "base_revision": 2}

        @staticmethod
        async def apply_candidate(principal, task_id, content_version_id, *, base_revision):
            return None

        # replay-recovery store: returns the SAME candidate the first call
        # generated (P1-9 contract)
        _generated: dict = {"candidate": None}

        @staticmethod
        async def latest_candidate(principal, task_id):
            return GenerationApp._generated["candidate"]

    class AssistApp:
        @staticmethod
        async def propose(principal, task_id, *, action, selected_text, block_id, base_revision, start_offset, end_offset, usage_out=None):
            await provider.generate(system="s", prompt="p", prompt_version="editorial-assist")
            return {
                "suggestion_id": "sg-1", "action": action, "suggested_text": "改写后。",
                "block_id": block_id, "base_revision": base_revision,
                "selected_text_hash": "h" * 64, "status": "proposed",
            }

        @staticmethod
        async def accept(principal, task_id, suggestion_id, *, base_revision):
            return {"idempotent": False, "suggestion_id": suggestion_id, "revision": base_revision + 1}

    class VariantsApp:
        @staticmethod
        async def preview(principal, task_id):
            return {"channels": {}, "master_content_version_id": "m-1"}

        @staticmethod
        async def generate_variants(principal, task_id, *, usage_out=None):
            await provider.generate(system="s", prompt="p", prompt_version="variants")
            return {"channels": {"wechat_website": {"status": "ready", "content_version_id": "v-1"}}}

        @staticmethod
        async def regenerate(principal, task_id, channel, *, usage_out=None):
            await provider.generate(system="s", prompt="p", prompt_version="regen")
            return {"channel": channel, "content_version_id": "v-2", "status": "ready"}

        @staticmethod
        async def prepare_export(principal, task_id):
            return {"published": False}

    class Apps:
        projects = None
        drafts = DraftsShim(DRAFT_DOCUMENT)
        generation = GenerationApp()
        assist = AssistApp()
        variants = VariantsApp()

        class usage:  # noqa: N801
            @staticmethod
            async def usage_summary(principal):
                return {"used": 0, "quota": 30000}

        usage_ledger = None  # injected below

    Apps.usage_ledger = ledger
    app = create_app(tasks=FakeTasks(), verifier=FakeVerifier(), knowledge=FakeKnowledge(), consumer_apps=Apps)
    return TestClient(app), ledger, provider


KEY = "idem-key-0000000000000001"


def test_draft_generate_without_idempotency_key_is_422():
    client, _, provider = make_client()
    response = client.post(f"/api/v1/consumer/projects/{TASK_ID}/draft/generate", headers=AUTH)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert provider.calls == [], "the model must never run without an idempotency key"


def test_suggestion_without_idempotency_key_is_422():
    client, _, provider = make_client()
    response = client.post(
        f"/api/v1/consumer/projects/{TASK_ID}/suggestions",
        json={
            "action": "shorten",
            "selectedText": "句子。",
            "blockId": "b1",
            "baseRevision": 2,
            "startOffset": 3,
            "endOffset": 4,
        },
        headers=AUTH,
    )
    assert response.status_code == 422, response.text
    assert provider.calls == []


def test_variants_generate_without_idempotency_key_is_422():
    client, _, provider = make_client()
    response = client.post(f"/api/v1/consumer/projects/{TASK_ID}/variants/generate", headers=AUTH)
    assert response.status_code == 422, response.text
    assert provider.calls == []


def test_variant_regenerate_without_idempotency_key_is_422():
    client, _, provider = make_client()
    response = client.post(
        f"/api/v1/consumer/projects/{TASK_ID}/variants/wechat_website/regenerate", headers=AUTH
    )
    assert response.status_code == 422, response.text
    assert provider.calls == []


def test_same_key_draft_generate_replay_runs_the_model_once():
    client, ledger, provider = make_client()
    first = client.post(f"/api/v1/consumer/projects/{TASK_ID}/draft/generate", headers={**AUTH, "Idempotency-Key": KEY})
    assert first.status_code == 200, first.text
    replay = client.post(f"/api/v1/consumer/projects/{TASK_ID}/draft/generate", headers={**AUTH, "Idempotency-Key": KEY})
    assert replay.status_code == 200, replay.text
    assert provider.calls.count("draft-generation") == 1, "a replayed key must not re-invoke the provider"
    reserves = [phase for key, phase in ledger.events if key == KEY and phase == "reserve"]
    assert len(reserves) == 2  # replayed reserve is answered from the ledger, not re-booked
    settles = [phase for key, phase in ledger.events if key == KEY and phase == "settle"]
    assert settles == ["settle"], "a replayed call must not settle twice"


def test_same_key_variants_generate_replay_runs_the_model_once():
    client, ledger, provider = make_client()
    first = client.post(f"/api/v1/consumer/projects/{TASK_ID}/variants/generate", headers={**AUTH, "Idempotency-Key": KEY})
    assert first.status_code == 200, first.text
    replay = client.post(f"/api/v1/consumer/projects/{TASK_ID}/variants/generate", headers={**AUTH, "Idempotency-Key": KEY})
    assert replay.status_code == 200, replay.text
    assert provider.calls.count("variants") == 1
    settles = [phase for key, phase in ledger.events if key == KEY and phase == "settle"]
    assert settles == ["settle"]


def test_different_keys_are_independent_calls():
    client, _, provider = make_client()
    a = client.post(f"/api/v1/consumer/projects/{TASK_ID}/variants/generate", headers={**AUTH, "Idempotency-Key": "key-aaaaaaaaaaaaaaaaaa"})
    b = client.post(f"/api/v1/consumer/projects/{TASK_ID}/variants/generate", headers={**AUTH, "Idempotency-Key": "key-bbbbbbbbbbbbbbbbbb"})
    assert a.status_code == 200 and b.status_code == 200
    assert provider.calls.count("variants") == 2, "distinct keys are distinct user actions"


def test_draft_generate_replay_returns_the_existing_candidate():
    """P1-9: a replayed draft-generate key must return the EXISTING
    candidate (recoverable), never {replayed: true, candidate: None} —
    a network retry after a lost response must not strand the user."""
    client, ledger, provider = make_client()
    first = client.post(f"/api/v1/consumer/projects/{TASK_ID}/draft/generate", headers={**AUTH, "Idempotency-Key": KEY})
    assert first.status_code == 200, first.text
    candidate_id = first.json()["data"]["candidate"]["content_version_id"]

    replay = client.post(f"/api/v1/consumer/projects/{TASK_ID}/draft/generate", headers={**AUTH, "Idempotency-Key": KEY})
    assert replay.status_code == 200, replay.text
    data = replay.json()["data"]
    # the replay contract: the SAME candidate is returned so the front end
    # can adopt it without re-invoking the model
    assert data.get("candidate") is not None, "replay must return the existing candidate"
    assert data["candidate"]["content_version_id"] == candidate_id
    assert data.get("replayed") is True
    assert provider.calls.count("draft-generation") == 1
