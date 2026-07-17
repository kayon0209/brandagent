import pytest

from agent_api.workflow import checkpoint
from agent_api.workflow.checkpoint import checkpoint_config, verify_checkpoint_isolation


def test_checkpoint_config_is_workspace_scoped() -> None:
    first = checkpoint_config(workspace_id="workspace-a", task_id="same-task")
    second = checkpoint_config(workspace_id="workspace-b", task_id="same-task")
    assert first["configurable"]["thread_id"] != second["configurable"]["thread_id"]
    assert first["configurable"]["checkpoint_ns"] == "workspace:workspace-a"


@pytest.mark.asyncio
async def test_checkpoint_isolation_rejects_resolved_shared_role(monkeypatch) -> None:
    identities = iter([
        ("brandflow", "shared_role", "public"),
        ("brandflow", "shared_role", "checkpoint"),
    ])

    async def fake_identity(_database_url: str):
        return next(identities)

    monkeypatch.setattr(checkpoint, "_database_identity", fake_identity)
    with pytest.raises(RuntimeError, match="same database role"):
        await verify_checkpoint_isolation("business", "checkpoint")


@pytest.mark.asyncio
async def test_checkpoint_isolation_rejects_resolved_shared_schema(monkeypatch) -> None:
    identities = iter([
        ("brandflow", "business_role", "public"),
        ("brandflow", "checkpoint_role", "public"),
    ])

    async def fake_identity(_database_url: str):
        return next(identities)

    monkeypatch.setattr(checkpoint, "_database_identity", fake_identity)
    with pytest.raises(RuntimeError, match="same database schema"):
        await verify_checkpoint_isolation("business", "checkpoint")
