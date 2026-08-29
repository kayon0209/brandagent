"""Postgres-backed usage ledger integration tests (task 13).

Gated behind RUN_AGENT_DB_TESTS=true: PK (workspace_id, request_id)
idempotency on real SQL, reserve/settle/refund states, and cross-workspace
privacy under RLS.
"""

import os
from uuid import uuid4

import pytest

from agent_api.api.security import Principal
from agent_api.application.usage import QuotaExceeded, UsageLedgerService
from agent_api.repositories.postgres_usage import PostgresUsageLedgerStore


pytestmark = pytest.mark.skipif(os.getenv("RUN_AGENT_DB_TESTS") != "true", reason="requires disposable PostgreSQL")

WORKSPACE = str(uuid4())
OTHER_WORKSPACE = str(uuid4())


def principal_for(workspace_id: str) -> Principal:
    return Principal(user_id="consumer-1", workspace_id=workspace_id, role="admin", experience="personal")


async def _ensure_workspace(store: PostgresUsageLedgerStore, workspace_id: str, user_id: str) -> None:
    async with store._pool.connection() as connection:
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))
        await connection.execute(
            """INSERT INTO workspaces(workspace_id, name, slug, created_by)
               VALUES (%s, 'Test WS', %s, %s)
               ON CONFLICT (workspace_id) DO NOTHING""",
            (workspace_id, f"ws-{workspace_id}", user_id),
        )


@pytest.mark.asyncio
async def test_usage_ledger_reserve_settle_refund_on_postgres() -> None:
    store = PostgresUsageLedgerStore(os.environ["AGENT_TEST_DATABASE_URL"])
    service = UsageLedgerService(store=store)
    await store.open()
    try:
        principal = principal_for(WORKSPACE)
        await _ensure_workspace(store, WORKSPACE, principal.user_id)
        reserved = await service.reserve(principal, request_id="pg-req-1", operation="suggestion", estimated_tokens=100)
        assert reserved["state"] == "reserved"

        settled = await service.settle(
            principal, request_id="pg-req-1", operation="suggestion",
            input_tokens=40, output_tokens=35, model="glm-4.5-air",
        )
        assert settled["state"] == "settled"
        # replay settle: no double charge
        replay = await service.settle(
            principal, request_id="pg-req-1", operation="suggestion",
            input_tokens=40, output_tokens=35, model="glm-4.5-air",
        )
        assert replay["replayed"] is True
        summary = await service.usage_summary(principal)
        assert summary["used"] == 75

        refunded = await service.reserve(principal, request_id="pg-req-2", operation="draft_generation", estimated_tokens=200)
        assert refunded["state"] == "reserved"
        refunded_back = await service.refund(principal, request_id="pg-req-2", reason="PROVIDER_FAILED")
        assert refunded_back["state"] == "refunded"
        summary = await service.usage_summary(principal)
        assert summary["used"] == 75, "refunds must not count"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_quota_enforced_before_model_on_postgres() -> None:
    store = PostgresUsageLedgerStore(os.environ["AGENT_TEST_DATABASE_URL"], quota=150)
    service = UsageLedgerService(store=store, quota=150)
    await store.open()
    try:
        principal = principal_for(OTHER_WORKSPACE)
        await _ensure_workspace(store, OTHER_WORKSPACE, principal.user_id)
        await service.reserve(principal, request_id="pg-q-1", operation="suggestion", estimated_tokens=100)
        with pytest.raises(QuotaExceeded):
            await service.reserve(principal, request_id="pg-q-2", operation="draft_generation", estimated_tokens=100)
        # nothing partial persisted for the blocked call
        assert await store.find_entry(OTHER_WORKSPACE, "pg-q-2") is None
    finally:
        await store.close()
