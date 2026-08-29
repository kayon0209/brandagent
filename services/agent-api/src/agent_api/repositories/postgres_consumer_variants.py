"""Postgres adapter for consumer platform variants (upgrade plan task 11).

Bridges the ConsumerVariantStore port onto the shared 002 schema by
reusing PostgresChannelStore (variant writes/leases) and the consumer
project store (project + active master snapshot reads). Channel variant
rows are real content_versions rows of type channel_draft, each pinned
to the adopted master snapshot via master_content_version_id — the
lineage requirement of the upgrade plan.
"""

from __future__ import annotations

import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent_api.domain.errors import NotFoundError


class PostgresConsumerVariantStore:
    def __init__(self, database_url: str, *, project_store) -> None:
        """project_store: PostgresConsumerProjectStore (workspace + master reads)."""

        self._pool = AsyncConnectionPool(database_url, open=False, kwargs={"row_factory": dict_row})
        self._projects = project_store

    async def open(self) -> None:
        await self._pool.open()

    async def close(self) -> None:
        await self._pool.close()

    async def _scope(self, connection, workspace_id: str) -> None:
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))

    # ------------------------------------------------------------------
    # project + master
    # ------------------------------------------------------------------

    async def get_project(self, workspace_id: str, task_id: str) -> dict | None:
        return await self._projects.get_project(workspace_id, task_id)

    async def active_master(self, workspace_id: str, task_id: str) -> dict | None:
        """The consumer's adopted master snapshot (active_master_version_id)."""

        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT v.content_version_id, v.task_id, v.workspace_id, v.content_type,
                          v.content, v.immutable_hash, v.structured_blocks
                   FROM consumer_projects p
                   JOIN content_versions v
                     ON v.content_version_id = p.active_master_version_id
                    AND v.workspace_id = p.workspace_id
                   WHERE p.workspace_id=%s AND p.task_id=%s""",
                (workspace_id, task_id),
            )
            return await cursor.fetchone()

    async def current_variant(self, workspace_id: str, task_id: str, channel: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT content_version_id, task_id, workspace_id, content_type, channel,
                          version_number, content, master_content_version_id,
                          immutable_hash, prompt_version, created_at
                   FROM content_versions
                   WHERE workspace_id=%s AND task_id=%s AND channel=%s
                     AND content_type IN ('channel_draft', 'channel_revised')
                   ORDER BY version_number DESC
                   LIMIT 1""",
                (workspace_id, task_id, channel),
            )
            return await cursor.fetchone()

    # ------------------------------------------------------------------
    # variant writes (idempotent per master hash + channel + prompt version)
    # ------------------------------------------------------------------

    async def save_variant(self, **payload) -> dict:
        workspace_id = payload["workspace_id"]
        task_id = payload["task_id"]
        channel = payload["channel"]
        master_content_version_id = payload["master_content_version_id"]
        master_snapshot_hash = payload["master_snapshot_hash"]
        prompt_version = payload["prompt_version"]

        # replay: same master hash + channel + prompt version returns the existing row
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT content_version_id, task_id, workspace_id, content_type, channel,
                          version_number, content, master_content_version_id,
                          immutable_hash, prompt_version
                   FROM content_versions
                   WHERE workspace_id=%s AND task_id=%s AND channel=%s
                     AND master_content_version_id=%s
                     AND prompt_version=%s
                     AND content_type='channel_draft'
                   ORDER BY version_number DESC
                   LIMIT 1""",
                (workspace_id, task_id, channel, master_content_version_id, prompt_version),
            )
            existing = await cursor.fetchone()
            if existing is not None:
                return {**existing, "idempotent": True}

            cursor = await connection.execute(
                """SELECT COALESCE(MAX(version_number),0)+1 AS next
                   FROM content_versions
                   WHERE workspace_id=%s AND task_id=%s AND channel=%s AND content_type='channel_draft'""",
                (workspace_id, task_id, channel),
            )
            next_number = (await cursor.fetchone())["next"]
            version_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"brandagent:variant:{task_id}:{channel}:{master_snapshot_hash}:{prompt_version}:{next_number}",
                )
            )
            cursor = await connection.execute(
                """INSERT INTO content_versions
                       (content_version_id, workspace_id, task_id, content_type, channel,
                        version_number, content, structured_blocks,
                        review_status, approval_status, immutable_hash,
                        created_by_type, created_by_id, prompt_version, change_summary,
                        master_content_version_id)
                   VALUES (%s, %s, %s, 'channel_draft', %s, %s, %s, %s::jsonb,
                           'passed', 'not_required', %s, 'model', 'consumer-variant',
                           %s, 'consumer platform variant', %s)
                   RETURNING content_version_id, task_id, workspace_id, content_type, channel,
                             version_number, content, master_content_version_id,
                             immutable_hash, prompt_version""",
                (
                    version_id,
                    workspace_id,
                    task_id,
                    channel,
                    next_number,
                    payload.get("content", ""),
                    json.dumps(payload.get("block_mappings", [])),
                    hashlib.sha256(str(payload.get("content", "")).encode("utf-8")).hexdigest(),
                    prompt_version,
                    master_content_version_id,
                ),
            )
            row = await cursor.fetchone()
            return {**row, "idempotent": False}

    # ------------------------------------------------------------------
    # events ride the consumer project store
    # ------------------------------------------------------------------

    async def append_event(self, event: dict) -> None:
        await self._projects.append_event(event)


__all__ = ["PostgresConsumerVariantStore", "NotFoundError"]
