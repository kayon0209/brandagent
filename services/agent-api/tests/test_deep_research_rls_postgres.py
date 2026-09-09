"""Gated integration test: 010 deep research orphan recovery RLS semantics.

The deep-research orphan recovery gap (Phase 6 follow-up):

- 009_deep_research.sql enables AND FORCES RLS on
  deep_research_runs / deep_research_events;
- brandflow_app is a plain business role (NOT superuser, NOT BYPASSRLS);
- therefore a cross-workspace maintenance scan like
  PostgresDeepResearchStore.find_orphans() could not read ANY row under
  production semantics — startup recovery would silently see zero
  orphans and never fail restart-abandoned runs or refund their ledger
  reservations.

These tests prove the RESTRICTED recovery entry added by
010_deep_research_orphan_recovery.sql:

- normal business queries still fail closed without the workspace scope;
- the recovery entry identifies planned/running runs across workspaces
  without any app.workspace_id setting (this is the RED gap: before 010
  the store query sees nothing);
- terminal runs are never listed and never rewritten;
- the entry returns ONLY minimal identification columns (no question /
  synthesis / candidate content ever crosses the boundary);
- other roles (brandflow_checkpoint) cannot execute the entry;
- the full recover_orphans flow marks the orphan failed, refunds the
  reservation through the scoped ledger, and emits the honest failure
  event — as the business role, NOT as a superuser.
"""

import os
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from agent_api.api.security import Principal
from agent_api.application.deep_research import DeepResearchService
from agent_api.application.usage import UsageLedgerService
from agent_api.repositories.postgres_deep_research import PostgresDeepResearchStore
from agent_api.repositories.postgres_usage import PostgresUsageLedgerStore


pytestmark = pytest.mark.skipif(os.getenv("RUN_AGENT_DB_TESTS") != "true", reason="requires disposable PostgreSQL")


def fresh_workspace() -> str:
    return str(uuid4())


def business_role_url() -> str:
    """The DISPOSABLE test URL re-written for the plain business role.

    brandflow_app is granted tables by postgres-grants.sql but is NOT
    superuser and NOT BYPASSRLS — exactly the production posture.
    """
    parsed = urlsplit(os.environ["AGENT_TEST_DATABASE_URL"])
    host = parsed.hostname or "127.0.0.1"
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"brandflow_app@{host}{port}", parsed.path, "", ""))


def checkpoint_role_url() -> str:
    parsed = urlsplit(os.environ["AGENT_TEST_DATABASE_URL"])
    host = parsed.hostname or "127.0.0.1"
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"brandflow_checkpoint@{host}{port}", parsed.path, "", ""))


RECOVERY_FUNCTION = "public.deep_research_list_orphaned_runs"


async def _seed_run(database_url: str, *, workspace_id: str, status: str, request_id: str, created_by: str = "consumer-1") -> str:
    """Seed one run row through the owner path (as the deployment seeds)."""
    store = PostgresDeepResearchStore(database_url)
    await store.open()
    try:
        run = await store.insert_run(
            {
                "run_id": str(uuid4()),
                "workspace_id": workspace_id,
                "question": f"问题 {request_id}",
                "audience": "",
                "scope_hint": "",
                "status": "planned",
                "request_id": request_id,
                "created_by": created_by,
                "created_at": "2026-09-09T00:00:00+00:00",
            }
        )
        if status != "planned":
            run = await store.update_run(workspace_id, run["run_id"], {"status": status, "completed_at": None})
        return run["run_id"]
    finally:
        await store.close()


# --------------------------------------------------------------------
# 1. business queries still fail closed (isolation is NOT weakened by 010)
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deep_research_tables_fail_closed_for_the_business_role() -> None:
    workspace = fresh_workspace()
    owner_url = os.environ["AGENT_TEST_DATABASE_URL"]
    await _seed_run(owner_url, workspace_id=workspace, status="running", request_id=f"req-fc-{uuid4()}")

    async with await psycopg.AsyncConnection.connect(business_role_url(), row_factory=dict_row) as connection:
        # no app.workspace_id: NOT EVEN the recovery scenario may weaken this
        cursor = await connection.execute("SELECT COUNT(*) AS n FROM deep_research_runs")
        assert (await cursor.fetchone())["n"] == 0, "009 RLS must stay fail-closed without the scope setting"

        # scoped to a foreign workspace: nothing leaks either
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (fresh_workspace(),))
        cursor = await connection.execute("SELECT COUNT(*) AS n FROM deep_research_runs")
        assert (await cursor.fetchone())["n"] == 0, "a foreign workspace scope must not reveal other rows"

        # the right workspace: the run IS visible to normal scoped queries
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace,))
        cursor = await connection.execute("SELECT COUNT(*) AS n FROM deep_research_runs")
        assert (await cursor.fetchone())["n"] == 1, "the scoped business role still reads its own workspace"


# --------------------------------------------------------------------
# 2. THE RED GAP: recovery listing across workspaces without a scope
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orphan_listing_reads_planned_running_runs_across_workspaces() -> None:
    owner_url = os.environ["AGENT_TEST_DATABASE_URL"]
    workspace_a, workspace_b = fresh_workspace(), fresh_workspace()
    req_a, req_b, req_done = f"req-oa-{uuid4()}", f"req-ob-{uuid4()}", f"req-done-{uuid4()}"
    ws_a_run = await _seed_run(owner_url, workspace_id=workspace_a, status="running", request_id=req_a)
    ws_b_run = await _seed_run(owner_url, workspace_id=workspace_b, status="planned", request_id=req_b)
    # a terminal run must never appear in the recovery listing
    done_run = await _seed_run(owner_url, workspace_id=workspace_a, status="succeeded", request_id=req_done)

    # the recovery listing runs over the BUSINESS role connection with NO
    # app.workspace_id — the exact startup condition of find_orphans()
    store = PostgresDeepResearchStore(business_role_url())
    await store.open()
    try:
        orphans = await store.find_orphans()
    finally:
        await store.close()

    # the disposable database is shared across gated tests: assert on
    # THIS test's seeded rows and on the shapes that must ALWAYS hold
    mine = {(row["run_id"], row["request_id"]) for row in orphans
            if row["request_id"] in (req_a, req_b, req_done)}
    assert mine == {(ws_a_run, req_a), (ws_b_run, req_b)}, \
        "recovery must see exactly this test's planned/running rows"
    for row in orphans:
        # minimal identification columns only — recovery never receives
        # question/synthesis/candidate content
        assert set(row.keys()) == {"run_id", "workspace_id", "request_id", "created_by"}
        assert row["workspace_id"] and row["created_by"]


# --------------------------------------------------------------------
# 3. the entry is NOT a generic RLS bypass
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_entry_grants_no_generic_cross_workspace_read() -> None:
    async with await psycopg.AsyncConnection.connect(business_role_url(), row_factory=dict_row) as connection:
        # direct table reads stay invisible without the scope setting
        cursor = await connection.execute("SELECT COUNT(*) AS n FROM deep_research_runs")
        assert (await cursor.fetchone())["n"] == 0

    # another (non-business) role must NOT execute the recovery entry
    async with await psycopg.AsyncConnection.connect(checkpoint_role_url(), row_factory=dict_row) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await connection.execute(f"SELECT * FROM {RECOVERY_FUNCTION}()")
        # a failed statement aborts the tx; roll back before the next probe
        await connection.rollback()
        # and no direct table read either (denied by grants — the table
        # is not in the checkpoint role's grant set at all)
        with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedTable)):
            await connection.execute("SELECT COUNT(*) AS n FROM public.deep_research_runs")
        await connection.rollback()

    # catalog: the listing returns exactly the minimal identification
    # columns — verified on the real call path, not on catalog shapes
    async with await psycopg.AsyncConnection.connect(business_role_url(), row_factory=dict_row) as connection:
        cursor = await connection.execute(f"SELECT * FROM {RECOVERY_FUNCTION}() WHERE false")
        cursor.fetchone()  # force Describe without reading data
        names = [desc.name for desc in cursor.description]
        assert names == ["run_id", "workspace_id", "request_id", "created_by"], f"unexpected return columns: {names}"


# --------------------------------------------------------------------
# 4. the full recovery flow over the business role
# --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recover_orphans_marks_failed_refunds_and_emits_event_as_business_role() -> None:
    owner_url = os.environ["AGENT_TEST_DATABASE_URL"]
    workspace = fresh_workspace()
    request_id = f"req-orph-{uuid4()}"
    orphan_id = await _seed_run(owner_url, workspace_id=workspace, status="running", request_id=request_id)

    # the reservation exists EXACTLY as it would when the process died
    ledger_owner = UsageLedgerService(store=PostgresUsageLedgerStore(owner_url))
    await ledger_owner._store.open()
    try:
        principal = Principal(user_id="consumer-1", workspace_id=workspace, role="admin", experience="personal")
        await ledger_owner.reserve(principal, request_id=request_id, operation="deep_research", estimated_tokens=30000)
    finally:
        await ledger_owner._store.close()

    # everything below runs as the plain BUSINESS role
    store = PostgresDeepResearchStore(business_role_url())
    ledger = UsageLedgerService(store=PostgresUsageLedgerStore(business_role_url()))
    service = DeepResearchService(
        store=store,
        provider=_NoCallProvider(),
        search=_NoSearchProvider(),
        ledger=ledger,
    )
    await store.open()
    await ledger._store.open()
    try:
        await service.recover_orphans()  # shared disposable DB: count varies; assert THIS run's outcome

        run = await store.get_run(workspace, orphan_id)
        assert run is not None and run["status"] == "failed"
        assert "额度已退回" in run["error"], "after a successful refund the failed message may claim it"

        outstanding = await ledger._store.find_entry(workspace, request_id)
        assert outstanding is not None and outstanding["state"] == "refunded", "the reservation must be released"

        events = await store.list_events(workspace, orphan_id, 0)
        types = [e["event_type"] for e in events]
        assert "consumer.research.failed.v1" in types, "recovery emits the honest failure event"
    finally:
        await store.close()
        await ledger._store.close()


@pytest.mark.asyncio
async def test_recover_orphans_never_rewrites_terminal_runs() -> None:
    owner_url = os.environ["AGENT_TEST_DATABASE_URL"]
    workspace = fresh_workspace()
    request_id = f"req-done-{uuid4()}"
    done_id = await _seed_run(owner_url, workspace_id=workspace, status="succeeded", request_id=request_id)
    ledger_owner = UsageLedgerService(store=PostgresUsageLedgerStore(owner_url))
    await ledger_owner._store.open()
    try:
        principal = Principal(user_id="consumer-1", workspace_id=workspace, role="admin", experience="personal")
        await ledger_owner.settle(principal, request_id=request_id, operation="deep_research", input_tokens=10, output_tokens=5, model="fake")
    finally:
        await ledger_owner._store.close()

    store = PostgresDeepResearchStore(business_role_url())
    ledger = UsageLedgerService(store=PostgresUsageLedgerStore(business_role_url()))
    service = DeepResearchService(store=store, provider=_NoCallProvider(), search=_NoSearchProvider(), ledger=ledger)
    await store.open()
    await ledger._store.open()
    try:
        await service.recover_orphans()

        run = await store.get_run(workspace, done_id)
        assert run is not None and run["status"] == "succeeded", "terminal runs are never rewritten"

        # settled entry must remain untouched by recovery
        async with await psycopg.AsyncConnection.connect(owner_url, row_factory=dict_row) as connection:
            cursor = await connection.execute(
                "SELECT state FROM usage_ledger WHERE workspace_id=%s AND request_id=%s",
                (workspace, request_id),
            )
            row = await cursor.fetchone()
        assert row is not None and row["state"] == "settled", "settled usage is never re-refunded"
    finally:
        await store.close()
        await ledger._store.close()


# --------------------------------------------------------------------
# doubles: recovery must never invoke the model or a web search
# --------------------------------------------------------------------


class _NoCallProvider:
    async def generate(self, *, system: str, prompt: str, prompt_version: str):  # pragma: no cover - guard
        raise AssertionError("startup recovery must never call the model")


class _NoSearchProvider:
    async def search(self, query: str, max_results: int = 5):  # pragma: no cover - guard
        raise AssertionError("startup recovery must never search the web")
