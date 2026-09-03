"""Workspace-dynamic consumer channels (agentization P2-3).

The channel surface for preview/regenerate is data, not an enum:
supported_channels comes from the MCP spec table (built-ins plus custom
rows) via the channel listing gateway. These route tests pin: preview
carries the channel list, regenerate accepts a custom channel, and
unknown channels stay 404 (never revealing other workspaces' customs).
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from agent_api.api.main import create_app
from agent_api.api.security import Principal


AUTH = {"Authorization": "Bearer valid-token"}
TASK_ID = str(uuid4())


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


class ChannelListingStub:
    def __init__(self, channels: tuple[str, ...]) -> None:
        self.channels = channels
        self.calls: list[str] = []

    async def supported_consumer_channels(self, *, workspace_id: str) -> tuple[str, ...]:
        self.calls.append(workspace_id)
        return self.channels


class VariantsApp:
    def __init__(self, preview_payload: dict) -> None:
        self._payload = preview_payload

    async def preview(self, principal, task_id):
        return self._payload

    async def generate_variants(self, principal, task_id, *, usage_out=None):
        return {"channels": {}}

    async def regenerate(self, principal, task_id, channel, *, usage_out=None):
        return {"channel": channel, "content_version_id": f"v-{channel}", "status": "ready"}

    async def prepare_export(self, principal, task_id):
        return {"published": False}


class ProjectsApp:
    @staticmethod
    async def get_project(principal, task_id):
        return {"task_id": task_id, "title": "t", "core_idea": "c"}


class UsageLedgerStub:
    async def reserve(self, principal, *, request_id, operation, estimated_tokens):
        return {"state": "reserved", "replayed": False}

    async def settle(self, principal, *, request_id, operation, input_tokens, output_tokens, model):
        return {"state": "settled"}

    async def refund(self, principal, *, request_id, reason):
        return {"state": "refunded"}


def make_client(channels: tuple[str, ...]) -> tuple[TestClient, ChannelListingStub]:
    listing = ChannelListingStub(channels)

    class Apps:
        projects = ProjectsApp()
        drafts = None
        generation = None
        assist = None
        variants = VariantsApp({"channels": {}, "master_content_version_id": "m-1"})
        usage_ledger = UsageLedgerStub()

        class usage:  # noqa: N801
            @staticmethod
            async def usage_summary(principal):
                return {"used": 0, "quota": 30000}

        channel_validator = listing

    app = create_app(tasks=FakeTasks(), verifier=FakeVerifier(), knowledge=FakeKnowledge(), consumer_apps=Apps)
    return TestClient(app), listing


def test_preview_carries_the_workspace_channel_list():
    client, listing = make_client(("wechat_website", "xiaohongshu", "video_script_60s", "custom_zhihu"))
    response = client.get(f"/api/v1/consumer/projects/{TASK_ID}/variants/preview", headers=AUTH)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["supported_channels"] == ["wechat_website", "xiaohongshu", "video_script_60s", "custom_zhihu"]
    assert listing.calls == ["ws-1"]  # scoped to the CALLER's workspace


def test_regenerate_accepts_a_custom_channel():
    client, _ = make_client(("wechat_website", "custom_zhihu"))
    response = client.post(
        f"/api/v1/consumer/projects/{TASK_ID}/variants/custom_zhihu/regenerate",
        headers={**AUTH, "Idempotency-Key": "key-custom-0123456789"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["channel"] == "custom_zhihu"


def test_regenerate_404s_unknown_channels():
    client, _ = make_client(("wechat_website",))
    response = client.post(
        f"/api/v1/consumer/projects/{TASK_ID}/variants/telegram_broadcast/regenerate",
        headers={**AUTH, "Idempotency-Key": "key-unknown-0123456789"},
    )
    assert response.status_code == 404
