"""Gated integration test: 004 consumer RLS on real PostgreSQL.

Verifies the fail-closed workspace policy on the seven 003 tables with the
business role (superuser would bypass RLS and void the check).
"""

import os
from uuid import uuid4

import pytest

from agent_api.api.security import Principal
from agent_api.application.consumer_projects import ConsumerProjectService
from agent_api.repositories.postgres_consumer_projects import PostgresConsumerProjectStore


pytestmark = pytest.mark.skipif(os.getenv("RUN_AGENT_DB_TESTS") != "true", reason="requires disposable PostgreSQL")

WORKSPACE = str(uuid4())


@pytest.mark.asyncio
async def test_consumer_tables_fail_closed_without_workspace_scope() -> None:
    store = PostgresConsumerProjectStore(os.environ["AGENT_TEST_DATABASE_URL"])
    await store.open()
    try:
        # a workspace + project exist (RLS-scoped writes work)
        principal = Principal(user_id="consumer-1", workspace_id=WORKSPACE, role="admin", experience="personal")
        projects = ConsumerProjectService(store=store)
        created = await projects.create_project(principal, title="RLS", core_idea="隔离验证", intent="")
        assert created["title"] == "RLS"

        # WITHOUT app.workspace_id the same connection sees NOTHING
        async with store._pool.connection() as connection:
            await connection.execute("SELECT set_config('app.workspace_id','',true)")
            cursor = await connection.execute(
                "SELECT COUNT(*) AS n FROM consumer_projects WHERE workspace_id=%s",
                (WORKSPACE,),
            )
            count = (await cursor.fetchone())["n"]
            assert count == 0, "004 must fail closed: rows are invisible without the workspace setting"

            cursor = await connection.execute(
                "SELECT COUNT(*) AS n FROM consumer_drafts"
            )
            assert (await cursor.fetchone())["n"] == 0
    finally:
        await store.close()
