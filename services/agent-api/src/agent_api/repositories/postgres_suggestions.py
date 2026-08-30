"""Postgres persistence for editor suggestions (upgrade plan task 9).

Implements the SuggestionStore port over the 003 editor_suggestions table.
Draft reads/writes delegate to the shared consumer store (same database),
so accept keeps its atomic compare-and-swap semantics.
"""

from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent_api.domain.errors import NotFoundError


_NULL_OFFSET = -1


class PostgresSuggestionStore:
    def __init__(self, database_url: str, *, draft_store) -> None:
        """draft_store: PostgresConsumerProjectStore (drafts + excerpts + links)."""

        self._pool = AsyncConnectionPool(database_url, open=False, kwargs={"row_factory": dict_row})
        self._drafts = draft_store

    async def open(self) -> None:
        await self._pool.open()

    async def close(self) -> None:
        await self._pool.close()

    async def _scope(self, connection, workspace_id: str) -> None:
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))

    # ------------------------------------------------------------------
    # delegate: drafts, excerpts, links, events are the shared store's job
    # ------------------------------------------------------------------

    async def get_draft(self, workspace_id: str, task_id: str) -> dict | None:
        return await self._drafts.get_draft(workspace_id, task_id)

    async def save_draft(self, workspace_id: str, task_id: str, document: dict, plain_text: str, expected_revision: int) -> dict:
        return await self._drafts.save_draft(workspace_id, task_id, document, plain_text, expected_revision)

    async def get_excerpts_by_ids(self, workspace_id: str, excerpt_ids: list[str]) -> list[dict]:
        return await self._drafts.get_excerpts_by_ids(workspace_id, excerpt_ids)

    async def linked_excerpt_ids(self, workspace_id: str, task_id: str) -> list[str]:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT excerpt_id FROM project_material_links
                   WHERE workspace_id=%s AND task_id=%s
                   ORDER BY COALESCE(position, 0), created_at""",
                (workspace_id, task_id),
            )
            return [row["excerpt_id"] for row in await cursor.fetchall()]

    async def append_event(self, event: dict) -> None:
        await self._drafts.append_event(event)

    # ------------------------------------------------------------------
    # suggestions
    # ------------------------------------------------------------------

    async def insert_suggestion(self, suggestion: dict) -> dict:
        workspace_id = suggestion["workspace_id"]
        task_id = suggestion["task_id"]
        # the client's block-local offsets are authoritative; derive from
        # the canonical block text only when they are absent (legacy)
        start_offset = suggestion.get("start_offset")
        end_offset = suggestion.get("end_offset")
        if not isinstance(start_offset, int) or not isinstance(end_offset, int):
            draft = await self._drafts.get_draft(workspace_id, task_id)
            if draft is None:
                raise NotFoundError(f"draft for project {task_id} not found")
            block = next(
                (b for b in draft["document"].get("blocks", []) if b.get("block_id") == suggestion["block_id"]),
                None,
            )
            if block is None:
                raise NotFoundError(f"block {suggestion['block_id']} not found in the draft")
            start = block.get("text", "").find(suggestion["selected_text"])
            start_offset = start if start >= 0 else _NULL_OFFSET
            end_offset = (start + len(suggestion["selected_text"]) - 1) if start >= 0 else _NULL_OFFSET

        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """INSERT INTO editor_suggestions
                       (workspace_id, task_id, base_revision, block_id,
                        start_offset, end_offset, selected_text_hash, action,
                        proposal_text, supporting_excerpt_ids, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'proposed')
                   RETURNING suggestion_id, workspace_id, task_id, action, block_id,
                             base_revision, selected_text_hash, proposal_text,
                             supporting_excerpt_ids, status, created_at""",
                (
                    workspace_id,
                    task_id,
                    suggestion["base_revision"],
                    suggestion["block_id"],
                    start_offset,
                    end_offset,
                    suggestion["selected_text_hash"],
                    suggestion["action"],
                    suggestion["suggested_text"],
                    suggestion.get("supporting_excerpt_ids") or [],
                ),
            )
            row = await cursor.fetchone()
        row = dict(row)
        row["selected_text"] = suggestion["selected_text"]
        row["suggested_text"] = suggestion["suggested_text"]
        row["prompt_version"] = suggestion.get("prompt_version", "")
        return row

    async def get_suggestion(self, workspace_id: str, suggestion_id: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT suggestion_id, workspace_id, task_id, action, block_id,
                          base_revision, start_offset, end_offset,
                          selected_text_hash, proposal_text,
                          supporting_excerpt_ids, status, created_at, resolved_at
                   FROM editor_suggestions
                   WHERE workspace_id=%s AND suggestion_id=%s""",
                (workspace_id, suggestion_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        row = dict(row)
        row["suggested_text"] = row.pop("proposal_text", "")
        return row

    async def mark_accepted(self, workspace_id: str, suggestion_id: str, revision: int) -> None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            await connection.execute(
                """UPDATE editor_suggestions
                   SET status='accepted', resolved_at=NOW()
                   WHERE workspace_id=%s AND suggestion_id=%s""",
                (workspace_id, suggestion_id),
            )
