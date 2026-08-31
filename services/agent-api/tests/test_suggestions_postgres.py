"""Postgres-backed editorial suggestion integration tests (task 9).

Gated behind RUN_AGENT_DB_TESTS=true. Exercises editor_suggestions against
real SQL: propose persists offsets+hash over the canonical plain text,
accept replaces the exact range atomically, stale revision returns 409,
and re-accept is idempotent.
"""

import os
from uuid import uuid4

import pytest

from agent_api.api.security import Principal
from agent_api.application.consumer_projects import ConsumerProjectService
from agent_api.application.drafts import DraftService
from agent_api.application.editorial_assist import EditorialAssistService, SelectionStale
from agent_api.providers.base import ModelCallResult
from agent_api.repositories.postgres_consumer_projects import PostgresConsumerProjectStore
from agent_api.repositories.postgres_suggestions import PostgresSuggestionStore


pytestmark = pytest.mark.skipif(os.getenv("RUN_AGENT_DB_TESTS") != "true", reason="requires disposable PostgreSQL")

WORKSPACE = str(uuid4())

BASE_TEXT = "这是第一段。这里有一个需要改写的句子，它有点啰嗦。这是结尾。"
TARGET = "这里有一个需要改写的句子，它有点啰嗦。"


class StubProvider:
    """Returns the REAL ModelCallResult contract (not a dict) so this gated
    integration suite cannot mask provider-protocol drift from the in-memory
    suite (test_editorial_assist.RecordingProvider pins the same contract)."""

    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        return ModelCallResult(
            content="精炼后的句子。",
            provider="stub",
            model="stub",
            prompt_version=prompt_version,
            latency_ms=5,
            input_tokens=1,
            output_tokens=1,
            usage_source="none",
            retry_count=0,
        )


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
async def test_suggestion_propose_accept_and_stale_on_postgres() -> None:
    draft_store = PostgresConsumerProjectStore(os.environ["AGENT_TEST_DATABASE_URL"])
    suggestion_store = PostgresSuggestionStore(os.environ["AGENT_TEST_DATABASE_URL"], draft_store=draft_store)
    await draft_store.open()
    await suggestion_store.open()
    try:
        await _ensure_workspace(draft_store, WORKSPACE, "consumer-1")
        principal = Principal(user_id="consumer-1", workspace_id=WORKSPACE, role="admin", experience="personal")
        projects = ConsumerProjectService(store=draft_store)
        drafts = DraftService(store=draft_store)
        assist = EditorialAssistService(store=suggestion_store, provider=StubProvider())

        created = await projects.create_project(principal, title="t", core_idea="c", intent="")
        task_id = created["task_id"]
        saved = await drafts.autosave(
            principal,
            task_id,
            {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": BASE_TEXT}]},
            BASE_TEXT,
            expected_revision=0,
        )

        suggestion = await assist.propose(
            principal,
            task_id,
            action="shorten",
            selected_text=TARGET,
            block_id="b1",
            base_revision=saved["revision"],
        )
        assert suggestion["status"] == "proposed"
        assert suggestion["suggested_text"] == "精炼后的句子。"

        # stale accept on a fresh (unaccepted) suggestion must 409 and leave the draft alone
        with pytest.raises(SelectionStale):
            await assist.accept(principal, task_id, suggestion["suggestion_id"], base_revision=saved["revision"] - 1)
        fresh = await drafts.get_or_create_draft(principal, task_id)
        assert fresh["plain_text"] == BASE_TEXT

        result = await assist.accept(principal, task_id, suggestion["suggestion_id"], base_revision=saved["revision"])
        assert result["revision"] == saved["revision"] + 1
        assert TARGET not in result["plain_text"]
        assert "精炼后的句子。" in result["plain_text"]

        # idempotent replay returns the accepted outcome without bumping again
        replay = await assist.accept(principal, task_id, suggestion["suggestion_id"], base_revision=saved["revision"] + 1)
        assert replay["idempotent"] is True
    finally:
        await suggestion_store.close()
        await draft_store.close()
