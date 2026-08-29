"""Postgres-backed consumer project/draft integration tests (task 8).

Gated behind RUN_AGENT_DB_TESTS=true. Exercises the real SQL: one-transaction
project creation (task+brief+project+draft), revision compare-and-swap,
autosave without content_version, adopt idempotency, and cross-workspace 404.
"""

import os
from uuid import uuid4

import pytest

from agent_api.api.security import Principal
from agent_api.application.consumer_projects import ConsumerProjectService
from agent_api.application.drafts import DraftService
from agent_api.domain.errors import ConflictError, NotFoundError
from agent_api.repositories.postgres_consumer_projects import PostgresConsumerProjectStore


pytestmark = pytest.mark.skipif(os.getenv("RUN_AGENT_DB_TESTS") != "true", reason="requires disposable PostgreSQL")

WORKSPACE = str(uuid4())
OTHER_WORKSPACE = str(uuid4())


async def _ensure_workspace(store: PostgresConsumerProjectStore, workspace_id: str, user_id: str) -> None:
    async with store._pool.connection() as connection:
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))
        await connection.execute(
            """INSERT INTO workspaces(workspace_id, name, slug, created_by)
               VALUES (%s, 'Test WS', %s, %s)
               ON CONFLICT (workspace_id) DO NOTHING""",
            (workspace_id, f"ws-{workspace_id}", user_id),
        )


@pytest.mark.asyncio
async def test_project_and_draft_lifecycle_on_postgres() -> None:
    store = PostgresConsumerProjectStore(os.environ["AGENT_TEST_DATABASE_URL"])
    await store.open()
    try:
        await _ensure_workspace(store, WORKSPACE, "consumer-1")
        principal = Principal(user_id="consumer-1", workspace_id=WORKSPACE, role="admin", experience="personal")
        projects = ConsumerProjectService(store=store)
        drafts = DraftService(store=store)

        created = await projects.create_project(principal, title="Nova 发布", core_idea="讲清楚价值", intent="公众号")
        assert created["title"] == "Nova 发布"

        # draft was created in the same transaction with revision 0
        draft = await drafts.get_or_create_draft(principal, created["task_id"])
        assert draft["revision"] == 0

        # autosave: revision bump, no content_versions
        saved = await drafts.autosave(
            principal,
            created["task_id"],
            {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": "初稿文本"}]},
            "初稿文本",
            expected_revision=0,
        )
        assert saved["revision"] == 1
        version = await store.get_draft_snapshot_version(WORKSPACE, created["task_id"], 0)
        assert version is None, "autosave must not create versions"

        # stale base revision is rejected without overwriting
        stale = await drafts.autosave(
            principal,
            created["task_id"],
            {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": "过期"}]},
            "过期",
            expected_revision=0,
        )
        assert stale is None
        current = await drafts.get_or_create_draft(principal, created["task_id"])
        assert current["plain_text"] == "初稿文本"

        # adopt creates an immutable snapshot; repeat adopt is idempotent
        adopted = await drafts.adopt(principal, created["task_id"], base_revision=1)
        assert adopted["idempotent"] is False
        repeated = await drafts.adopt(principal, created["task_id"], base_revision=1)
        assert repeated["idempotent"] is True
        assert repeated["version"]["content_version_id"] == adopted["version"]["content_version_id"]

        # blocks were persisted with the snapshot (RLS: scope the read connection first)
        async with store._pool.connection() as connection:
            await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (WORKSPACE,))
            cursor = await connection.execute(
                """SELECT COUNT(*) AS n FROM content_blocks
                   WHERE workspace_id=%s AND content_version_id=%s""",
                (WORKSPACE, adopted["version"]["content_version_id"]),
            )
            assert (await cursor.fetchone())["n"] == 1

        # stale adopt conflicts
        with pytest.raises(ConflictError):
            await drafts.adopt(principal, created["task_id"], base_revision=0)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_cross_workspace_draft_and_project_reads_are_scoped() -> None:
    store = PostgresConsumerProjectStore(os.environ["AGENT_TEST_DATABASE_URL"])
    await store.open()
    try:
        await _ensure_workspace(store, OTHER_WORKSPACE, "consumer-2")
        principal = Principal(user_id="consumer-2", workspace_id=OTHER_WORKSPACE, role="admin", experience="personal")
        projects = ConsumerProjectService(store=store)
        created = await projects.create_project(principal, title="iso", core_idea="隔离", intent="")

        intruder = Principal(user_id="intruder", workspace_id=WORKSPACE, role="admin", experience="personal")
        with pytest.raises(NotFoundError):
            await projects.get_project(intruder, created["task_id"])
        assert await store.get_draft(WORKSPACE, created["task_id"]) is None
    finally:
        await store.close()
