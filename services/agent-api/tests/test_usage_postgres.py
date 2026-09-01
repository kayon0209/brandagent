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


# ---------------------------------------------------------------------------
# P1-2 acceptance: network-retry safety on real PostgreSQL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replayed_request_id_never_double_charges_on_postgres() -> None:
    """The same Idempotency-Key replayed after success: no second model
    call booking, no second row, settled usage counted once."""

    workspace = str(uuid4())
    store = PostgresUsageLedgerStore(os.environ["AGENT_TEST_DATABASE_URL"])
    service = UsageLedgerService(store=store)
    await store.open()
    try:
        principal = Principal(user_id="consumer-1", workspace_id=workspace, role="admin", experience="personal")
        await _ensure_workspace(store, workspace, principal.user_id)
        key = "replay-key-0001"

        first = await service.reserve(principal, request_id=key, operation="variants", estimated_tokens=300)
        assert first["replayed"] is False
        await service.settle(principal, request_id=key, operation="variants", input_tokens=100, output_tokens=80, model="stub")

        # the retry arrives: reserve + settle replay against the SAME row
        replay_reserve = await service.reserve(principal, request_id=key, operation="variants", estimated_tokens=300)
        assert replay_reserve["replayed"] is True, "a replayed key must not open a new reservation"
        replay_settle = await service.settle(principal, request_id=key, operation="variants", input_tokens=100, output_tokens=80, model="stub")
        assert replay_settle["replayed"] is True, "a replayed key must not settle a second time"

        summary = await service.usage_summary(principal)
        assert summary["used"] == 180, "settled tokens must be counted exactly once"

        async with store._pool.connection() as connection:
            await store._scope(connection, workspace)
            cursor = await connection.execute(
                "SELECT COUNT(*) AS n FROM usage_ledger WHERE workspace_id=%s AND request_id=%s",
                (workspace, key),
            )
            assert (await cursor.fetchone())["n"] == 1, "exactly ONE ledger row per request id"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_provider_failure_refunds_once_and_retries_do_not_double_refund_on_postgres() -> None:
    workspace = str(uuid4())
    store = PostgresUsageLedgerStore(os.environ["AGENT_TEST_DATABASE_URL"])
    service = UsageLedgerService(store=store)
    await store.open()
    try:
        principal = Principal(user_id="consumer-1", workspace_id=workspace, role="admin", experience="personal")
        await _ensure_workspace(store, workspace, principal.user_id)
        key = "fail-key-0002"

        await service.reserve(principal, request_id=key, operation="suggestion", estimated_tokens=600)
        # provider explodes -> the route's ledgered_call refunds
        first_refund = await service.refund(principal, request_id=key, reason="CALL_FAILED")
        assert first_refund["state"] == "refunded"
        assert first_refund["replayed"] is False
        # the network retry of the SAME request refunds again -> replay
        second_refund = await service.refund(principal, request_id=key, reason="CALL_FAILED")
        assert second_refund["replayed"] is True, "a retried refund must not double-release quota"

        summary = await service.usage_summary(principal)
        assert summary["used"] >= 0
        # refunded entries never count against quota
        async with store._pool.connection() as connection:
            await store._scope(connection, workspace)
            cursor = await connection.execute(
                """SELECT COALESCE(SUM(
                       CASE WHEN state='refunded' THEN CEIL(COALESCE(estimated_cost,0)*1000000) ELSE 0 END),0) AS total
                   FROM usage_ledger WHERE workspace_id=%s""",
                (workspace,),
            )
            assert (await cursor.fetchone())["total"] == 0, "refunded rows must not count as usage"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_concurrent_respects_quota_without_oversubscription_on_postgres() -> None:
    """Two reserves racing under the per-workspace quota lock: the second
    either fits or is rejected — the sum can never exceed the quota."""

    workspace = str(uuid4())
    store = PostgresUsageLedgerStore(os.environ["AGENT_TEST_DATABASE_URL"], quota=1000)
    service = UsageLedgerService(store=store, quota=1000)
    await store.open()
    try:
        principal = Principal(user_id="consumer-1", workspace_id=workspace, role="admin", experience="personal")
        await _ensure_workspace(store, workspace, principal.user_id)

        import asyncio

        async def reserve(key: str):
            return await service.reserve(principal, request_id=key, operation="variants", estimated_tokens=600)

        results = await asyncio.gather(
            reserve("race-key-a1"), reserve("race-key-b1"), return_exceptions=True
        )
        ok = [r for r in results if isinstance(r, dict)]
        blocked = [r for r in results if isinstance(r, Exception)]
        # 600 + 600 = 1200 > 1000 -> exactly ONE may succeed
        assert len(ok) == 1 and len(blocked) == 1, f"quota must admit exactly one, got ok={len(ok)} blocked={len(blocked)}"

        summary = await service.usage_summary(principal)
        assert summary["used"] + 600 <= 1000, "committed usage may never exceed the quota"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_cross_workspace_usage_is_isolated_on_postgres() -> None:
    """Workspace A's ledger rows are invisible to workspace B: quota and
    usage are strictly per workspace (P1-2 isolation acceptance)."""

    store = PostgresUsageLedgerStore(os.environ["AGENT_TEST_DATABASE_URL"])
    service = UsageLedgerService(store=store)
    await store.open()
    try:
        workspace_a = str(uuid4())
        workspace_b = str(uuid4())
        principal_a = Principal(user_id="consumer-1", workspace_id=workspace_a, role="admin", experience="personal")
        principal_b = Principal(user_id="consumer-2", workspace_id=workspace_b, role="admin", experience="personal")
        await _ensure_workspace(store, workspace_a, principal_a.user_id)
        await _ensure_workspace(store, workspace_b, principal_b.user_id)
        # the repo-level bootstrap (workspaces + creator_profiles) is what
        # production runs on first touch; usage_summary requires the profile
        # row to exist
        await store.ensure_workspace(workspace_a, principal_a.user_id)
        await store.ensure_workspace(workspace_b, principal_b.user_id)

        await service.reserve(principal_a, request_id="iso-key-a", operation="suggestion", estimated_tokens=100)
        await service.settle(principal_a, request_id="iso-key-a", operation="suggestion", input_tokens=40, output_tokens=30, model="stub")

        summary_b = await service.usage_summary(principal_b)
        assert summary_b["used"] == 0, "workspace B must not see workspace A's usage"

        # B replaying A's request id opens B's OWN row — ids are scoped by workspace
        entry_b = await service.reserve(principal_b, request_id="iso-key-a", operation="suggestion", estimated_tokens=50)
        assert entry_b["replayed"] is False, "the same key in another workspace is a fresh request"
    finally:
        await store.close()
