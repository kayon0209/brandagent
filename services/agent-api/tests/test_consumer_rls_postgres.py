"""Gated integration test: 004 consumer RLS on real PostgreSQL.

The scope assertions run as the real `brandflow_app` business role — a
superuser connection owns the tables and BYPASSRLS makes every policy
invisible, which would void the check (acceptance P1-5: never fake a pass
with postgres superuser).
"""

import os
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from agent_api.api.security import Principal
from agent_api.application.consumer_projects import ConsumerProjectService
from agent_api.repositories.postgres_consumer_projects import PostgresConsumerProjectStore


pytestmark = pytest.mark.skipif(os.getenv("RUN_AGENT_DB_TESTS") != "true", reason="requires disposable PostgreSQL")

def fresh_workspace() -> str:
    return str(uuid4())

CONSUMER_TABLES = (
    "creator_profiles",
    "consumer_projects",
    "consumer_drafts",
    "material_excerpts",
    "project_material_links",
    "editor_suggestions",
    "usage_ledger",
)


def business_role_url() -> str:
    parsed = urlsplit(os.environ["AGENT_TEST_DATABASE_URL"])
    host = parsed.hostname or "127.0.0.1"
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"brandflow_app@{host}{port}", parsed.path, "", ""))


@pytest.mark.asyncio
async def test_consumer_tables_fail_closed_without_workspace_scope() -> None:
    workspace = fresh_workspace()
    # seed through the app store as the deployment does (admin/owner path)
    store = PostgresConsumerProjectStore(os.environ["AGENT_TEST_DATABASE_URL"])
    await store.open()
    try:
        principal = Principal(user_id="consumer-1", workspace_id=workspace, role="admin", experience="personal")
        projects = ConsumerProjectService(store=store)
        created = await projects.create_project(principal, title="RLS", core_idea="隔离验证", intent="")
        assert created["title"] == "RLS"
    finally:
        await store.close()

    # the RLS contract itself is checked over the BUSINESS role connection:
    # brandflow_app is not the owner and not superuser, so policies apply.
    async with await psycopg.AsyncConnection.connect(business_role_url(), row_factory=dict_row) as connection:
        # WITH the workspace scope: the row is visible
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace,))
        cursor = await connection.execute(
            "SELECT COUNT(*) AS n FROM consumer_projects WHERE workspace_id=%s",
            (workspace,),
        )
        assert (await cursor.fetchone())["n"] == 1, "the scoped business role must see its own workspace"

        # WITHOUT app.workspace_id the SAME connection sees NOTHING
        await connection.execute("SELECT set_config('app.workspace_id','',true)")
        cursor = await connection.execute(
            "SELECT COUNT(*) AS n FROM consumer_projects WHERE workspace_id=%s",
            (workspace,),
        )
        assert (await cursor.fetchone())["n"] == 0, "004 must fail closed: rows are invisible without the workspace setting"

        cursor = await connection.execute("SELECT COUNT(*) AS n FROM consumer_drafts")
        assert (await cursor.fetchone())["n"] == 0

        # every consumer table fails closed without the scope setting
        for table in CONSUMER_TABLES:
            cursor = await connection.execute(f"SELECT COUNT(*) AS n FROM {table}")
            assert (await cursor.fetchone())["n"] == 0, f"{table} must be invisible without app.workspace_id"


@pytest.mark.asyncio
async def test_cross_workspace_rows_are_invisible_to_the_business_role() -> None:
    """Workspace B's rows never leak to workspace A, and a foreign id does
    not reveal existence (count is the same as for a random uuid)."""

    workspace_a = fresh_workspace()
    workspace_b = fresh_workspace()
    store = PostgresConsumerProjectStore(os.environ["AGENT_TEST_DATABASE_URL"])
    await store.open()
    try:
        for workspace, user in ((workspace_a, "consumer-a"), (workspace_b, "consumer-b")):
            principal = Principal(user_id=user, workspace_id=workspace, role="admin", experience="personal")
            projects = ConsumerProjectService(store=store)
            await projects.create_project(principal, title=f"ws-{user}", core_idea="c", intent="")
    finally:
        await store.close()

    async with await psycopg.AsyncConnection.connect(business_role_url(), row_factory=dict_row) as connection:
        # scoped to workspace A
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_a,))
        cursor = await connection.execute(
            "SELECT COUNT(*) AS n FROM consumer_projects WHERE workspace_id=%s",
            (workspace_b,),
        )
        assert (await cursor.fetchone())["n"] == 0, "workspace B's rows must be invisible to workspace A"

        cursor = await connection.execute("SELECT COUNT(*) AS n FROM consumer_projects")
        assert (await cursor.fetchone())["n"] == 1, "only workspace A's own row is visible"
