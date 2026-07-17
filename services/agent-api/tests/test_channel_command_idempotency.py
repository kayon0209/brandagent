import pytest

from agent_api.api.security import Principal
from agent_api.application.tasks import TaskWorkflowService
from agent_api.repositories.leases import WorkflowLease


class Tasks:
    async def require_operator(self, principal): return None
    async def get_task(self, principal, task_id): return {"task_id": task_id, "selected_channels": ["wechat_website"]}


class Store:
    def __init__(self): self.response = None
    async def task_context(self, workspace_id, task_id): return {"product_id": "product-1", "selected_channels": ["wechat_website"]}
    async def claim_operation(self, workspace_id, actor_id, action, idempotency_key, target, request):
        if self.response is not None: return None, self.response
        return WorkflowLease(owner="owner-1", version=1, heartbeat_seconds=60), None
    async def renew_operation(self, *args): return True
    async def complete_operation(self, workspace_id, actor_id, action, idempotency_key, response, lease): self.response = response
    async def set_task_stage(self, *args): return None


class Channels:
    def __init__(self): self.calls = 0
    async def generate(self, **kwargs): self.calls += 1; return {"wechat_website": {"content_version_id": "v1"}}


@pytest.mark.asyncio
async def test_channel_generation_replays_durable_result_without_second_model_call() -> None:
    store = Store()
    channels = Channels()
    service = TaskWorkflowService(tasks=Tasks(), workflow=None, provider=None, checkpointer=None, channel_store=store, channels=channels)
    principal = Principal(user_id="operator-1", workspace_id="workspace-1", role="content_operator")
    first = await service.generate_channels(principal, "task-1", "same-idempotency-key")
    second = await service.generate_channels(principal, "task-1", "same-idempotency-key")
    assert first == second
    assert channels.calls == 1
