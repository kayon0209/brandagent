from unittest.mock import AsyncMock

import pytest

from agent_api.api.models import BriefInput, CreateTaskRequest, DecisionRequest
from agent_api.api.security import Principal
from agent_api.application.tasks import TaskWorkflowService
from agent_api.domain.models import Channel
from agent_api.providers.base import LLMProvider, ModelCallResult
from agent_api.repositories.leases import WorkflowLease


class NoopProvider(LLMProvider):
    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        raise AssertionError("Provider must not run in service idempotency tests")


class FakeTasks:
    def __init__(self) -> None:
        self.create_calls = 0
        self.retry_calls = 0
        self.clarification_calls = 0
        self.status = "draft"

    async def create_task(self, principal, request, idempotency_key):
        self.create_calls += 1
        return {
            "task_id": "task-1",
            "workspace_id": principal.workspace_id,
            "user_id": principal.user_id,
            "title": request.title,
            "status": self.status,
            "selected_channels": ["wechat_website"],
            "current_node": None,
            "_dispatch_lease": WorkflowLease("create-owner", 1, 10) if self.create_calls == 1 else None,
        }

    async def get_task(self, principal, task_id):
        return {
            "task_id": task_id,
            "workspace_id": principal.workspace_id,
            "user_id": principal.user_id,
            "title": "Nova",
            "status": self.status,
            "selected_channels": ["wechat_website"],
            "current_node": None,
        }

    async def claim_retry(self, principal, task_id, idempotency_key):
        self.retry_calls += 1
        return WorkflowLease("retry-owner", 1, 10) if self.retry_calls == 1 else None

    async def persist_clarification(self, principal, task_id, answers, idempotency_key):
        self.clarification_calls += 1
        return WorkflowLease("clarify-owner", 1, 10) if self.clarification_calls == 1 else None

    async def complete_idempotency(self, principal, action, idempotency_key, response_body, lease):
        return None

    async def renew_idempotency_lease(self, principal, action, idempotency_key, lease):
        return True


class FakeWorkflow:
    def __init__(self) -> None:
        self.calls = 0

    async def record_decision(self, **kwargs):
        self.calls += 1
        return "decision-1", WorkflowLease("decision-owner", 1, 10) if self.calls == 1 else None

    async def complete_decision_idempotency(self, **kwargs):
        return None

    async def renew_decision_lease(self, **kwargs):
        return True


def service_fixture():
    tasks = FakeTasks()
    workflow = FakeWorkflow()
    service = TaskWorkflowService(tasks=tasks, workflow=workflow, provider=NoopProvider(), checkpointer=None)
    service._invoke = AsyncMock()
    principal = Principal(user_id="operator-1", workspace_id="workspace-1", role="content_operator")
    return service, tasks, workflow, principal


def create_request() -> CreateTaskRequest:
    return CreateTaskRequest(
        title="Nova",
        selected_channels=[Channel.WECHAT_WEBSITE],
        brief=BriefInput(
            topic="Nova",
            brand_id="brand-1",
            product_id="product-1",
            target_audience="IT",
            publishing_objective="Explain",
            primary_channel=Channel.WECHAT_WEBSITE,
            desired_audience_action="Demo",
        ),
    )


@pytest.mark.asyncio
async def test_duplicate_create_does_not_invoke_workflow_twice() -> None:
    service, _tasks, _workflow, principal = service_fixture()
    await service.create_task(principal, create_request(), "create-key-12345")
    await service.create_task(principal, create_request(), "create-key-12345")
    assert service._invoke.await_count == 1


@pytest.mark.asyncio
async def test_duplicate_outline_decision_does_not_resume_current_interrupt() -> None:
    service, tasks, _workflow, principal = service_fixture()
    tasks.status = "waiting_for_outline_approval"
    request = DecisionRequest(
        content_version_id="version-1",
        target_snapshot_hash="a" * 64,
        decision="approve",
        comment="Approved",
    )
    await service.decide(principal, "task-1", "outline", request, "decision-key-123")
    tasks.status = "waiting_for_master_approval"
    await service.decide(principal, "task-1", "outline", request, "decision-key-123")
    assert service._invoke.await_count == 1


@pytest.mark.asyncio
async def test_duplicate_clarification_does_not_resume_twice() -> None:
    service, tasks, _workflow, principal = service_fixture()
    tasks.status = "waiting_for_clarification"
    await service.answer_clarification(principal, "task-1", {"product_id": "product-1"}, "clarify-key-1234")
    await service.answer_clarification(principal, "task-1", {"product_id": "product-1"}, "clarify-key-1234")
    assert service._invoke.await_count == 1


@pytest.mark.asyncio
async def test_duplicate_retry_does_not_retry_checkpoint_twice() -> None:
    service, tasks, _workflow, principal = service_fixture()
    tasks.status = "failed"
    await service.retry_task(principal, "task-1", "retry-key-123456")
    await service.retry_task(principal, "task-1", "retry-key-123456")
    assert service._invoke.await_count == 1
