from uuid import uuid4

from fastapi.testclient import TestClient

from agent_api.api.main import create_app
from agent_api.api.bootstrap import RuntimeTasks
from agent_api.api.security import Principal
from agent_api.domain.errors import ForbiddenError


class FakeVerifier:
    async def verify(self, token: str) -> Principal:
        if token != "valid-token":
            raise ValueError("invalid token")
        return Principal(user_id="operator-1", workspace_id="00000000-0000-0000-0000-000000000001", role="content_operator")


class FakeTasks:
    async def bootstrap_workspace(self, principal):
        return {"workspace_id": principal.workspace_id, "role": principal.role}

    async def list_tasks(self, principal): return []
    async def create_task(self, principal: Principal, request, idempotency_key: str):
        assert idempotency_key == "1234567890abcdef"
        return {
            "task_id": str(uuid4()),
            "workspace_id": principal.workspace_id,
            "user_id": principal.user_id,
            "title": request.title,
            "status": "draft",
            "selected_channels": request.selected_channels,
            "current_node": None,
        }

    async def get_task(self, principal: Principal, task_id: str):
        if task_id == "forbidden":
            raise ForbiddenError("Approval role is required")
        return {"task_id": task_id, "workspace_id": principal.workspace_id, "user_id": principal.user_id, "title": "Task", "status": "draft", "selected_channels": [], "current_node": None}

    async def cancel_task(self, principal: Principal, task_id: str, idempotency_key: str):
        return {"task_id": task_id, "status": "cancelled"}

    async def retry_task(self, principal: Principal, task_id: str, idempotency_key: str):
        return {"task_id": task_id, "status": "researching"}

    async def get_events(self, principal: Principal, task_id: str, after_event_id: int):
        assert after_event_id == 4
        return [{"event_id": 5, "event_type": "outline_ready", "public_payload": {"version_id": "v1"}, "workflow_node": "generate_master_outline", "created_at": "2026-07-14T00:00:00Z"}]

    async def answer_clarification(self, principal, task_id, answers, idempotency_key):
        return {"task_id": task_id, "status": "researching"}

    async def decide(self, principal, task_id, scope, request, idempotency_key):
        return {"task_id": task_id, "status": "waiting_for_master_approval"}

    async def decide_channel(self, principal, task_id, channel, request, idempotency_key):
        return {"task_id": task_id, "status": "reviewing_channels"}


def client() -> TestClient:
    return TestClient(create_app(tasks=FakeTasks(), verifier=FakeVerifier()))


def test_health_is_public_but_readiness_is_explicit() -> None:
    response = client().get("/api/v1/health")
    assert response.json() == {"success": True, "data": {"status": "alive"}}


def test_readiness_is_unavailable_before_runtime_dependencies_initialize() -> None:
    response = TestClient(create_app(tasks=RuntimeTasks(), verifier=FakeVerifier())).get("/api/v1/readiness")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


def test_readiness_becomes_ready_only_after_delegate_is_installed() -> None:
    runtime = RuntimeTasks()
    runtime.delegate = FakeTasks()
    response = TestClient(create_app(tasks=runtime, verifier=FakeVerifier())).get("/api/v1/readiness")
    assert response.status_code == 200
    assert response.json() == {"success": True, "data": {"status": "ready"}}


def test_task_api_rejects_missing_authentication() -> None:
    response = client().get("/api/v1/tasks/task-1")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_workspace_bootstrap_uses_verified_organization_identity() -> None:
    response = client().post(
        "/api/v1/workspaces/bootstrap",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert response.status_code == 200
    assert response.json()["data"] == {
        "workspace_id": "00000000-0000-0000-0000-000000000001",
        "role": "content_operator",
    }


def test_create_task_uses_verified_principal_not_request_identity() -> None:
    response = client().post(
        "/api/v1/tasks",
        headers={"Authorization": "Bearer valid-token", "Idempotency-Key": "1234567890abcdef"},
        json={
            "title": "Nova launch",
            "selected_channels": ["wechat_website"],
            "brief": {
                "topic": "Nova launch",
                "brand_id": "20000000-0000-0000-0000-000000000001",
                "product_id": "30000000-0000-0000-0000-000000000001",
                "target_audience": "Enterprise IT",
                "publishing_objective": "Explain verified value",
                "primary_channel": "wechat_website",
                "desired_audience_action": "Request demo"
            },
        },
    )
    assert response.status_code == 201
    assert response.json()["data"]["user_id"] == "operator-1"


def test_sse_resumes_after_last_event_id_without_hidden_reasoning() -> None:
    response = client().get(
        "/api/v1/tasks/task-1/events?follow=false",
        headers={"Authorization": "Bearer valid-token", "Last-Event-ID": "4"},
    )
    assert response.status_code == 200
    assert "id: 5" in response.text
    assert "outline_ready" in response.text
    assert "reasoning" not in response.text


def test_missing_idempotency_key_uses_public_validation_envelope() -> None:
    response = client().post(
        "/api/v1/tasks/task-1/cancel",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert response.status_code == 422
    assert response.json() == {
        "success": False,
        "error": {"code": "VALIDATION_ERROR", "message": "Request validation failed"},
    }


def test_decision_endpoint_rejects_mismatched_action() -> None:
    response = client().post(
        "/api/v1/tasks/task-1/outline/approve",
        headers={"Authorization": "Bearer valid-token", "Idempotency-Key": "decision-key-1234"},
        json={
            "content_version_id": "version-1",
            "target_snapshot_hash": "a" * 64,
            "decision": "reject",
            "comment": "The evidence is incomplete",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "HTTP_422"


def test_clarification_is_a_focused_request_not_a_chat_payload() -> None:
    response = client().post(
        "/api/v1/tasks/task-1/clarification",
        headers={"Authorization": "Bearer valid-token", "Idempotency-Key": "clarification-1234"},
        json={"answers": {"product_id": "30000000-0000-0000-0000-000000000001"}},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "researching"


def test_application_errors_do_not_expose_raw_exceptions() -> None:
    response = client().get(
        "/api/v1/tasks/forbidden",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert response.status_code == 403
    assert response.json() == {
        "success": False,
        "error": {"code": "FORBIDDEN", "message": "Approval role is required"},
    }
