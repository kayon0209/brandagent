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
from agent_api.application.editorial_assist import EditorialAssistService, SelectionStale, selection_hash
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

        start = BASE_TEXT.find(TARGET)
        suggestion = await assist.propose(
            principal,
            task_id,
            action="shorten",
            selected_text=TARGET,
            block_id="b1",
            base_revision=saved["revision"],
            start_offset=start,
            end_offset=start + len(TARGET) - 1,
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


REPEATED = f"前言。{TARGET}中段。{TARGET}结尾。"
B1_TEXT = f"开头。{TARGET}"
B2_TEXT = f"第二段开头。{TARGET}"


@pytest.mark.asyncio
async def test_same_block_duplicate_text_replaces_only_the_second_occurrence_on_postgres() -> None:
    """P1-1 acceptance: the SAME sentence appears twice inside ONE block.
    Selecting the second occurrence must replace exactly that range on
    real PostgreSQL — a .find()-based anchor would have hit the first."""

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

        created = await projects.create_project(principal, title="dup", core_idea="c", intent="")
        task_id = created["task_id"]
        saved = await drafts.autosave(
            principal,
            task_id,
            {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": REPEATED}]},
            REPEATED,
            expected_revision=0,
        )

        first = REPEATED.find(TARGET)
        second = REPEATED.find(TARGET, first + 1)
        assert second > first, "fixture must contain two distinct occurrences"

        suggestion = await assist.propose(
            principal,
            task_id,
            action="shorten",
            selected_text=TARGET,
            block_id="b1",
            base_revision=saved["revision"],
            start_offset=second,
            end_offset=second + len(TARGET) - 1,
        )
        result = await assist.accept(principal, task_id, suggestion["suggestion_id"], base_revision=saved["revision"])
        new_text = result["document"]["blocks"][0]["text"]
        assert new_text.count(TARGET) == 1, "only the selected (second) occurrence may be replaced"
        assert new_text.startswith(f"前言。{TARGET}"), "the first occurrence must survive untouched"
        # the persisted draft itself carries the exact replacement
        fresh = await drafts.get_or_create_draft(principal, task_id)
        assert fresh["plain_text"].count(TARGET) == 1
        assert "精炼后的句子。" in fresh["plain_text"]
    finally:
        await suggestion_store.close()
        await draft_store.close()


@pytest.mark.asyncio
async def test_multiblock_duplicate_text_replaces_only_the_selected_block_on_postgres() -> None:
    """P1-1 acceptance: the SAME sentence in b1 and b2. Selecting the b2
    occurrence must leave b1 untouched — verified on real PostgreSQL."""

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

        created = await projects.create_project(principal, title="multi", core_idea="c", intent="")
        task_id = created["task_id"]
        document = {
            "blocks": [
                {"block_id": "b1", "block_type": "paragraph", "text": B1_TEXT},
                {"block_id": "b2", "block_type": "paragraph", "text": B2_TEXT},
            ]
        }
        saved = await drafts.autosave(
            principal, task_id, document, "\n".join(b["text"] for b in document["blocks"]), expected_revision=0,
        )

        start = B2_TEXT.find(TARGET)
        suggestion = await assist.propose(
            principal,
            task_id,
            action="shorten",
            selected_text=TARGET,
            block_id="b2",
            base_revision=saved["revision"],
            start_offset=start,
            end_offset=start + len(TARGET) - 1,
        )
        result = await assist.accept(principal, task_id, suggestion["suggestion_id"], base_revision=saved["revision"])
        blocks = result["document"]["blocks"]
        assert TARGET in blocks[0]["text"], "the b1 occurrence must survive untouched"
        assert TARGET not in blocks[1]["text"], "the b2 occurrence must be the one replaced"
        assert "精炼后的句子。" in blocks[1]["text"]
    finally:
        await suggestion_store.close()
        await draft_store.close()


@pytest.mark.asyncio
async def test_propose_without_offsets_is_refused_before_any_model_call_on_postgres() -> None:
    """P1-1 acceptance: no offsets -> no anchor -> ValueError BEFORE the
    provider runs and BEFORE a suggestion row is persisted."""

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

        created = await projects.create_project(principal, title="anchorless", core_idea="c", intent="")
        task_id = created["task_id"]
        saved = await drafts.autosave(
            principal,
            task_id,
            {"blocks": [{"block_id": "b1", "block_type": "paragraph", "text": BASE_TEXT}]},
            BASE_TEXT,
            expected_revision=0,
        )

        with pytest.raises(ValueError):
            await assist.propose(
                principal,
                task_id,
                action="shorten",
                selected_text=TARGET,
                block_id="b1",
                base_revision=saved["revision"],
                start_offset=None,
                end_offset=None,
            )
        # nothing was persisted
        async with suggestion_store._pool.connection() as connection:
            await suggestion_store._scope(connection, WORKSPACE)
            cursor = await connection.execute(
                "SELECT COUNT(*) AS n FROM editor_suggestions WHERE workspace_id=%s AND task_id=%s",
                (WORKSPACE, task_id),
            )
            assert (await cursor.fetchone())["n"] == 0
    finally:
        await suggestion_store.close()
        await draft_store.close()


@pytest.mark.asyncio
async def test_db_layer_refuses_anchorless_suggestion_rows() -> None:
    """P1-1 acceptance: the editor_suggestions schema itself is NOT NULL on
    the offset pair, so an anchorless suggestion row cannot exist at all —
    accept can never fall back to text search for legacy data."""

    draft_store = PostgresConsumerProjectStore(os.environ["AGENT_TEST_DATABASE_URL"])
    suggestion_store = PostgresSuggestionStore(os.environ["AGENT_TEST_DATABASE_URL"], draft_store=draft_store)
    await draft_store.open()
    await suggestion_store.open()
    try:
        await _ensure_workspace(draft_store, WORKSPACE, "consumer-1")
        async with suggestion_store._pool.connection() as connection:
            await suggestion_store._scope(connection, WORKSPACE)
            with pytest.raises(Exception) as rejected:
                await connection.execute(
                    """INSERT INTO editor_suggestions
                           (workspace_id, task_id, base_revision, block_id,
                            start_offset, end_offset, selected_text_hash, action,
                            proposal_text, supporting_excerpt_ids, status)
                       VALUES (%s, %s, 1, 'b1', NULL, NULL, %s, 'shorten', '改写。', '{}'::uuid[], 'proposed')""",
                    (WORKSPACE, str(uuid4()), selection_hash(TARGET)),
                )
            assert "null value" in str(rejected.value).lower() or "not-null" in str(rejected.value).lower(), (
                "the offset columns must be NOT NULL so anchorless rows cannot persist"
            )
    finally:
        await suggestion_store.close()
        await draft_store.close()
