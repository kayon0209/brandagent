"""Postgres persistence for consumer materials (upgrade plan task 6).

Implements the MaterialStore port against the BrandFlow V2 schema:
source_documents / source_chunks / material_excerpts (003) plus the
idempotency_records and task_events infrastructure. Every access is
workspace-scoped; cross-workspace ids resolve to plain not-found.
"""

from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent_api.domain.consumer import ParsedMaterial


class PostgresMaterialStore:
    """MaterialStore adapter over the shared PostgreSQL instance.

    Consumer material writes are not attached to a real content task, so
    material events ride the existing task_events + SSE stream through a
    synthetic per-workspace material task id.
    """

    def __init__(self, database_url: str) -> None:
        self._pool = AsyncConnectionPool(database_url, open=False, kwargs={"row_factory": dict_row})

    async def open(self) -> None:
        await self._pool.open()

    async def close(self) -> None:
        await self._pool.close()

    def _material_task_id(self, workspace_id: str) -> str:
        """Stable synthetic task id grouping the workspace's material events."""
        return str(uuid5(NAMESPACE_URL, f"brandagent:material-task:{workspace_id}"))

    async def _scope(self, connection, workspace_id: str) -> None:
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    async def find_document_by_checksum(self, workspace_id: str, checksum: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT document_id, workspace_id, document_name, document_type,
                          version, authority_level, checksum, status
                   FROM source_documents
                   WHERE workspace_id=%s AND checksum=%s
                   LIMIT 1""",
                (workspace_id, checksum),
            )
            return await cursor.fetchone()

    async def insert_document(self, workspace_id: str, material: ParsedMaterial, checksum: str, request_id: str) -> dict:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """INSERT INTO source_documents
                       (workspace_id, document_name, document_type, version,
                        authority_level, status, checksum, created_by)
                   VALUES (%s, %s, 'external_reference', 'v1',
                           'reference', 'active', %s, %s)
                   ON CONFLICT (workspace_id, checksum) DO NOTHING
                   RETURNING document_id, workspace_id, document_name,
                             document_type, version, authority_level,
                             checksum, status""",
                (workspace_id, material.name, checksum, "consumer-material"),
            )
            row = await cursor.fetchone()
            if row is None:  # concurrent duplicate import: read the existing row
                row = await self.find_document_by_checksum(workspace_id, checksum)
            return row

    async def get_document(self, workspace_id: str, document_id: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT document_id, workspace_id, document_name, document_type,
                          version, authority_level, checksum, status
                   FROM source_documents
                   WHERE workspace_id=%s AND document_id=%s""",
                (workspace_id, document_id),
            )
            return await cursor.fetchone()

    async def list_documents(self, workspace_id: str) -> list[dict]:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT document_id, workspace_id, document_name, document_type,
                          version, authority_level, checksum, status, created_at
                   FROM source_documents
                   WHERE workspace_id=%s AND document_type='external_reference'
                   ORDER BY created_at DESC""",
                (workspace_id,),
            )
            return list(await cursor.fetchall())

    # ------------------------------------------------------------------
    # Chunks
    # ------------------------------------------------------------------

    async def insert_chunks(self, workspace_id: str, document_id: str, chunks: list[dict]) -> list[dict]:
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            inserted = []
            for chunk in chunks:
                cursor = await connection.execute(
                    """INSERT INTO source_chunks
                           (chunk_id, workspace_id, document_id, chunk_index, content)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (chunk_id) DO UPDATE SET content = EXCLUDED.content
                       RETURNING chunk_id, workspace_id, document_id, chunk_index, content""",
                    (chunk["chunk_id"], workspace_id, document_id, chunk["chunk_index"], chunk["content"]),
                )
                inserted.append(await cursor.fetchone())
            return inserted

    async def get_chunks(self, workspace_id: str, document_id: str) -> list[dict]:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT chunk_id, workspace_id, document_id, chunk_index, content
                   FROM source_chunks
                   WHERE workspace_id=%s AND document_id=%s
                   ORDER BY chunk_index""",
                (workspace_id, document_id),
            )
            return list(await cursor.fetchall())

    # ------------------------------------------------------------------
    # Excerpts
    # ------------------------------------------------------------------

    async def insert_excerpts(self, workspace_id: str, document_id: str, excerpts: list[dict]) -> list[dict]:
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            inserted = []
            for excerpt in excerpts:
                cursor = await connection.execute(
                    """INSERT INTO material_excerpts
                           (excerpt_id, workspace_id, document_id, chunk_id, excerpt_type,
                            summary, excerpt_text, tags, provenance_hash, status, created_by_type)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                       ON CONFLICT (excerpt_id) DO UPDATE SET status = EXCLUDED.status
                       RETURNING excerpt_id, workspace_id, document_id, chunk_id, excerpt_type,
                                 summary, excerpt_text, tags, provenance_hash, status,
                                 created_by_type, created_at""",
                    (
                        excerpt["excerpt_id"], workspace_id, document_id, excerpt["chunk_id"],
                        excerpt["excerpt_type"], excerpt["summary"], excerpt["excerpt_text"],
                        json.dumps(excerpt.get("tags", [])), excerpt["provenance_hash"],
                        excerpt["status"], excerpt["created_by_type"],
                    ),
                )
                inserted.append(await cursor.fetchone())
            return inserted

    async def get_excerpts(self, workspace_id: str, document_id: str) -> list[dict]:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT excerpt_id, workspace_id, document_id, chunk_id, excerpt_type,
                          summary, excerpt_text, tags, provenance_hash, status,
                          created_by_type, created_at
                   FROM material_excerpts
                   WHERE workspace_id=%s AND document_id=%s
                   ORDER BY created_at""",
                (workspace_id, document_id),
            )
            return list(await cursor.fetchall())

    # ------------------------------------------------------------------
    # Import idempotency (workspace + request_id)
    # ------------------------------------------------------------------

    async def record_import(self, workspace_id: str, request_id: str, result: dict) -> None:
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            await connection.execute(
                """INSERT INTO idempotency_records
                       (workspace_id, actor_id, action, immutable_target, idempotency_key,
                        request_hash, status, response_status, response_body, expires_at)
                   VALUES (%s, %s, 'consumer_material_import', 'consumer-materials', %s,
                           %s, 'succeeded', 200, %s::jsonb, NOW() + INTERVAL '24 hours')
                   ON CONFLICT (workspace_id, actor_id, action, idempotency_key) DO NOTHING""",
                (
                    workspace_id,
                    "consumer-material",
                    request_id,
                    f"material-import:{request_id}",
                    json.dumps(result),
                ),
            )

    async def find_import(self, workspace_id: str, request_id: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT response_body
                   FROM idempotency_records
                   WHERE workspace_id=%s
                     AND action='consumer_material_import'
                     AND idempotency_key=%s
                     AND status='succeeded'""",
                (workspace_id, request_id),
            )
            row = await cursor.fetchone()
            return row["response_body"] if row else None

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def append_event(self, event: dict) -> None:
        """Material events ride the existing task_events + SSE stream.

        The synthetic material task id groups all material events of one
        workspace under one SSE cursor namespace without inventing a new
        transport.
        """
        workspace_id = event["workspace_id"]
        task_id = self._material_task_id(workspace_id)
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            # Material events are not attached to a real content task; the
            # task_events FK requires a row, so ensure the synthetic task
            # exists (idempotent) before inserting the event.
            await connection.execute(
                """INSERT INTO content_tasks
                       (task_id, workspace_id, user_id, title, status, selected_channels)
                   VALUES (%s, %s, 'consumer-materials', '素材处理', 'draft', '{}')
                   ON CONFLICT (task_id) DO NOTHING""",
                (task_id, workspace_id),
            )
            await connection.execute(
                """INSERT INTO task_events
                       (workspace_id, task_id, event_type, public_payload, workflow_node, request_id)
                   VALUES (%s, %s, %s, %s::jsonb, 'consumer_materials', %s)""",
                (
                    workspace_id,
                    task_id,
                    event["type"],
                    json.dumps(event.get("data", {}), ensure_ascii=False),
                    event.get("request_id", ""),
                ),
            )

    async def material_events(self, workspace_id: str, after_event_id: int = 0, *, limit: int = 100) -> list[dict]:
        task_id = self._material_task_id(workspace_id)
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT event_id, event_type, public_payload, request_id, created_at
                   FROM task_events
                   WHERE workspace_id=%s AND task_id=%s AND event_id>%s
                   ORDER BY event_id
                   LIMIT %s""",
                (workspace_id, task_id, after_event_id, limit),
            )
            return list(await cursor.fetchall())
