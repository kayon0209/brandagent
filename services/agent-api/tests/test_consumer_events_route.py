"""Consumer project SSE route tests (upgrade plan §7.4 event stream).

Wire-format contract of GET /api/v1/consumer/projects/{task_id}/events:
- 404 for unknown/cross-tenant ids before any stream byte is written
- follow=false returns the current snapshot once and closes
- each event carries an `id:` cursor and a versioned data envelope
- Last-Event-ID resumes strictly after the cursor
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from agent_api.api.main import create_app
from agent_api.api.security import Principal


AUTH = {"Authorization": "Bearer valid-token"}

TASK_ID = str(uuid4())

EVENTS = [
    {
        "event_id": 11,
        "event_type": "consumer.project.created.v1",
        "event_version": "1.0",
        "public_payload": {"project_id": TASK_ID},
        "workflow_node": "consumer_projects",
        "created_at": "2026-09-03T00:00:00+00:00",
    },
    {
        "event_id": 12,
        "event_type": "consumer.project.updated.v1",
        "event_version": "1.0",
        "public_payload": {"project_id": TASK_ID},
        "workflow_node": "consumer_projects",
        "created_at": "2026-09-03T00:01:00+00:00",
    },
]


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


class ProjectsApp:
    """Implements the two methods the events route touches."""

    @staticmethod
    async def get_project(principal, task_id):
        if task_id != TASK_ID:
            from agent_api.domain.errors import NotFoundError

            raise NotFoundError(f"project {task_id} not found")
        return {"task_id": task_id, "title": "t", "core_idea": "c"}

    @staticmethod
    async def list_project_events(principal, task_id, *, after_event_id=0, limit=100):
        if task_id != TASK_ID:
            from agent_api.domain.errors import NotFoundError

            raise NotFoundError(f"project {task_id} not found")
        return [e for e in EVENTS if e["event_id"] > after_event_id][:limit]


class Apps:
    projects = ProjectsApp()
    drafts = None
    generation = None
    assist = None
    variants = None
    usage_ledger = None

    class usage:  # noqa: N801
        @staticmethod
        async def usage_summary(principal):
            return {"used": 0, "quota": 30000}


def make_client() -> TestClient:
    app = create_app(tasks=FakeTasks(), verifier=FakeVerifier(), knowledge=FakeKnowledge(), consumer_apps=Apps)
    return TestClient(app)


def _parse_sse(text: str) -> list[dict]:
    """Parse the raw SSE body into (id, event, data) tuples."""
    parsed = []
    block: dict = {}
    for line in text.splitlines():
        if not line:
            if block:
                parsed.append(block)
                block = {}
            continue
        if line.startswith(":"):
            continue  # heartbeat comments
        field, _, value = line.partition(": ")
        block[field] = value
    if block:
        parsed.append(block)
    return parsed


def test_events_snapshot_follow_false_lists_stream_once():
    client = make_client()
    with client.stream(
        "GET", f"/api/v1/consumer/projects/{TASK_ID}/events", headers=AUTH, params={"follow": "false"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(chunk for chunk in response.iter_text())
    events = _parse_sse(body)
    assert [e["id"] for e in events] == ["11", "12"]
    assert [e["event"] for e in events] == ["consumer.project.created.v1", "consumer.project.updated.v1"]
    assert '"project_id"' in events[0]["data"]
    assert '"event_version"' in events[0]["data"]


def test_events_last_event_id_resumes_after_cursor():
    client = make_client()
    with client.stream(
        "GET",
        f"/api/v1/consumer/projects/{TASK_ID}/events",
        headers={**AUTH, "Last-Event-ID": "11"},
        params={"follow": "false"},
    ) as response:
        assert response.status_code == 200
        body = "".join(chunk for chunk in response.iter_text())
    events = _parse_sse(body)
    assert [e["id"] for e in events] == ["12"]


def test_events_unknown_project_is_404():
    client = make_client()
    missing = str(uuid4())
    response = client.get(f"/api/v1/consumer/projects/{missing}/events", headers=AUTH, params={"follow": "false"})
    assert response.status_code == 404


def test_events_invalid_cursor_is_400():
    client = make_client()
    response = client.get(
        f"/api/v1/consumer/projects/{TASK_ID}/events",
        headers={**AUTH, "Last-Event-ID": "not-a-number"},
        params={"follow": "false"},
    )
    assert response.status_code == 400


def test_events_require_auth():
    client = make_client()
    response = client.get(f"/api/v1/consumer/projects/{TASK_ID}/events", params={"follow": "false"})
    assert response.status_code in (401, 403)
