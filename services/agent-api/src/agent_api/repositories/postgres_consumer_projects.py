"""Postgres persistence for consumer projects and drafts (task 8).

Implements ConsumerProjectStore and ConsumerDraftStore against the 002+003
schema. Every access is workspace-scoped via app.workspace_id; drafts are
updated with revision compare-and-swap so a stale editor can never
overwrite a newer server draft.
"""

from __future__ import annotations

import hashlib
import json
from uuid import NAMESPACE_URL, uuid4, uuid5

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent_api.domain.errors import ConflictError, NotFoundError


class PostgresConsumerProjectStore:
    def __init__(self, database_url: str) -> None:
        self._pool = AsyncConnectionPool(database_url, open=False, kwargs={"row_factory": dict_row})

    async def open(self) -> None:
        await self._pool.open()

    async def close(self) -> None:
        await self._pool.close()

    async def _scope(self, connection, workspace_id: str) -> None:
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))

    async def _ensure_workspace(self, connection, workspace_id: str) -> None:
        """Idempotent workspace row so first-write consumers never hit the FK.

        Live-stack audit finding: a brand-new user's first consumer write
        (create project / import material) crashed with a 500 because the
        stable dev-auth workspace had no `workspaces` row yet. The B-end
        bootstraps on entry; C-end surfaces write first, so the store
        guarantees the row itself (ON CONFLICT DO NOTHING).
        """

        await connection.execute(
            """INSERT INTO workspaces (workspace_id, name, slug, created_by)
               VALUES (%s, '个人工作区', %s, 'consumer')
               ON CONFLICT (workspace_id) DO NOTHING""",
            (workspace_id, f"ws-{workspace_id[:12]}"),
        )

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    async def insert_project(self, workspace_id: str, title: str, core_idea: str, intent: str) -> dict:
        task_id = str(uuid4())
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            await self._ensure_workspace(connection, workspace_id)
            # One transaction: content_task + content_brief + consumer_project + consumer_draft.
            await connection.execute(
                """INSERT INTO content_tasks
                       (task_id, workspace_id, user_id, title, status, selected_channels)
                   VALUES (%s, %s, %s, %s, 'draft', '{}')""",
                (task_id, workspace_id, "consumer", title),
            )
            await connection.execute(
                """INSERT INTO content_briefs
                       (task_id, workspace_id, topic, target_audience,
                        publishing_objective, desired_audience_action)
                   VALUES (%s, %s, %s, '', %s, '')""",
                (task_id, workspace_id, title, core_idea),
            )
            await connection.execute(
                """INSERT INTO consumer_projects
                       (task_id, workspace_id, core_idea, writing_intent)
                   VALUES (%s, %s, %s, %s)""",
                (task_id, workspace_id, core_idea, intent),
            )
            await connection.execute(
                """INSERT INTO consumer_drafts
                       (task_id, workspace_id, revision, document, plain_text)
                   VALUES (%s, %s, 0, %s::jsonb, '')""",
                (task_id, workspace_id, json.dumps({"blocks": []})),
            )
        return await self.get_project(workspace_id, task_id) or {"task_id": task_id}

    async def get_project(self, workspace_id: str, task_id: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT p.task_id, p.workspace_id,
                          t.title AS title,
                          p.core_idea, p.writing_intent,
                          p.active_master_version_id
                   FROM consumer_projects p
                   JOIN content_tasks t ON t.task_id = p.task_id AND t.workspace_id = p.workspace_id
                   WHERE p.workspace_id=%s AND p.task_id=%s""",
                (workspace_id, task_id),
            )
            project = await cursor.fetchone()
            if project is None:
                return None
            project["linked_excerpt_ids"] = await self._linked_excerpt_ids(connection, workspace_id, task_id)
            return project

    async def _linked_excerpt_ids(self, connection, workspace_id: str, task_id: str) -> list[str]:
        cursor = await connection.execute(
            """SELECT excerpt_id FROM project_material_links
               WHERE workspace_id=%s AND task_id=%s
               ORDER BY COALESCE(position, 0), created_at""",
            (workspace_id, task_id),
        )
        return [row["excerpt_id"] for row in await cursor.fetchall()]

    async def list_projects(self, workspace_id: str) -> list[dict]:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT p.task_id FROM consumer_projects p
                   WHERE p.workspace_id=%s ORDER BY p.updated_at DESC""",
                (workspace_id,),
            )
            tasks = [row["task_id"] for row in await cursor.fetchall()]
        projects = []
        for task_id in tasks:
            project = await self.get_project(workspace_id, task_id)
            if project is not None:
                projects.append(project)
        return projects

    async def update_project(self, workspace_id: str, task_id: str, *, title: str | None, core_idea: str | None, intent: str | None) -> dict | None:
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            if title is not None:
                await connection.execute(
                    "UPDATE content_tasks SET title=%s WHERE workspace_id=%s AND task_id=%s",
                    (title, workspace_id, task_id),
                )
            if core_idea is not None or intent is not None:
                await connection.execute(
                    """UPDATE consumer_projects
                       SET core_idea=COALESCE(%s, core_idea),
                           writing_intent=COALESCE(%s, writing_intent),
                           updated_at=NOW()
                       WHERE workspace_id=%s AND task_id=%s""",
                    (core_idea, intent, workspace_id, task_id),
                )
        return await self.get_project(workspace_id, task_id)

    async def link_excerpt(self, workspace_id: str, task_id: str, excerpt_id: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT COALESCE(MAX(position),0)+1 AS next
                   FROM project_material_links
                   WHERE workspace_id=%s AND task_id=%s""",
                (workspace_id, task_id),
            )
            next_position = (await cursor.fetchone())["next"]
            await connection.execute(
                """INSERT INTO project_material_links (workspace_id, task_id, excerpt_id, position)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (task_id, excerpt_id) DO NOTHING""",
                (workspace_id, task_id, excerpt_id, next_position),
            )
        return await self.get_project(workspace_id, task_id)

    async def unlink_excerpt(self, workspace_id: str, task_id: str, excerpt_id: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            await connection.execute(
                "DELETE FROM project_material_links WHERE workspace_id=%s AND task_id=%s AND excerpt_id=%s",
                (workspace_id, task_id, excerpt_id),
            )
        return await self.get_project(workspace_id, task_id)

    async def get_excerpts_by_ids(self, workspace_id: str, excerpt_ids: list[str]) -> list[dict]:
        if not excerpt_ids:
            return []
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT excerpt_id, workspace_id, document_id, chunk_id, excerpt_type,
                          summary, excerpt_text, tags, status, provenance_hash, created_by_type
                   FROM material_excerpts
                   WHERE workspace_id=%s AND excerpt_id = ANY(%s)""",
                (workspace_id, excerpt_ids),
            )
            return list(await cursor.fetchall())

    # ------------------------------------------------------------------
    # Drafts + versions
    # ------------------------------------------------------------------

    async def ensure_draft(self, workspace_id: str, task_id: str) -> dict:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            # ownership guard (security review P2): a consumer_projects row must
            # exist for THIS workspace before a draft can materialize
            cursor = await connection.execute(
                "SELECT 1 FROM consumer_projects WHERE workspace_id=%s AND task_id=%s",
                (workspace_id, task_id),
            )
            if await cursor.fetchone() is None:
                raise NotFoundError(f"project {task_id} not found in this workspace")
            await self._ensure_workspace(connection, workspace_id)
            await connection.execute(
                """INSERT INTO consumer_drafts (task_id, workspace_id, revision, document, plain_text)
                   VALUES (%s, %s, 0, %s::jsonb, '')
                   ON CONFLICT (task_id) DO NOTHING""",
                (task_id, workspace_id, json.dumps({"blocks": []})),
            )
        draft = await self.get_draft(workspace_id, task_id)
        if draft is None:
            raise NotFoundError(f"draft for project {task_id} not found")
        return draft

    async def get_draft(self, workspace_id: str, task_id: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT task_id, workspace_id, revision, document, plain_text,
                          last_snapshot_version_id, updated_at
                   FROM consumer_drafts
                   WHERE workspace_id=%s AND task_id=%s""",
                (workspace_id, task_id),
            )
            return await cursor.fetchone()

    async def save_draft(self, workspace_id: str, task_id: str, document: dict, plain_text: str, expected_revision: int) -> dict:
        """Revision compare-and-swap; a moved revision raises ConflictError."""

        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """UPDATE consumer_drafts
                   SET document=%s::jsonb,
                       plain_text=%s,
                       revision=revision+1,
                       updated_at=NOW(),
                       updated_by='consumer'
                   WHERE workspace_id=%s AND task_id=%s AND revision=%s
                   RETURNING task_id, workspace_id, revision, document, plain_text,
                             last_snapshot_version_id, updated_at""",
                (json.dumps(self._jsonable(document)), plain_text, workspace_id, task_id, expected_revision),
            )
            row = await cursor.fetchone()
            if row is None:
                draft = await self.get_draft(workspace_id, task_id)
                if draft is None:
                    raise NotFoundError(f"draft for project {task_id} not found")
                raise ConflictError("draft revision changed elsewhere")
            return row

    async def insert_candidate_version(self, workspace_id: str, task_id: str, plain_text: str, document: dict, *, prompt_version: str) -> dict:
        version_id = str(uuid4())
        immutable_hash = hashlib.sha256(plain_text.encode("utf-8")).hexdigest()
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT COALESCE(MAX(version_number),0)+1 AS next
                   FROM content_versions
                   WHERE workspace_id=%s AND task_id=%s AND content_type='master_revised'""",
                (workspace_id, task_id),
            )
            next_number = (await cursor.fetchone())["next"]
            cursor = await connection.execute(
                """INSERT INTO content_versions
                       (content_version_id, workspace_id, task_id, content_type, channel,
                        version_number, content, structured_blocks,
                        review_status, approval_status, immutable_hash,
                        created_by_type, created_by_id, prompt_version, change_summary)
                   VALUES (%s, %s, %s, 'master_revised', NULL, %s, %s, %s::jsonb,
                           'passed', 'not_required', %s, 'model', 'consumer-draft-gen',
                           %s, 'consumer draft candidate')
                   RETURNING content_version_id, task_id, workspace_id, content_type,
                             version_number, content, structured_blocks,
                             created_by_type, approval_status, immutable_hash,
                             prompt_version""",
                (
                    version_id,
                    workspace_id,
                    task_id,
                    next_number,
                    plain_text,
                    json.dumps(self._jsonable(document.get("blocks", []))),
                    immutable_hash,
                    prompt_version,
                ),
            )
            return await cursor.fetchone()

    async def get_version(self, workspace_id: str, version_id: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT content_version_id, task_id, workspace_id, content_type,
                          version_number, content, structured_blocks,
                          created_by_type, approval_status, immutable_hash,
                          prompt_version
                   FROM content_versions
                   WHERE workspace_id=%s AND content_version_id=%s""",
                (workspace_id, version_id),
            )
            return await cursor.fetchone()

    async def insert_snapshot_version(self, workspace_id: str, task_id: str, document: dict, plain_text: str, revision: int) -> dict:
        """Immutable master_draft snapshot of the draft at `revision`."""

        version_id = str(uuid5(NAMESPACE_URL, f"brandagent:snapshot:{task_id}:{revision}"))
        immutable_hash = hashlib.sha256((plain_text + str(revision)).encode("utf-8")).hexdigest()
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT COALESCE(MAX(version_number),0)+1 AS next
                   FROM content_versions
                   WHERE workspace_id=%s AND task_id=%s AND content_type='master_draft'""",
                (workspace_id, task_id),
            )
            next_number = (await cursor.fetchone())["next"]
            cursor = await connection.execute(
                """INSERT INTO content_versions
                       (content_version_id, workspace_id, task_id, content_type, channel,
                        version_number, content, structured_blocks,
                        review_status, approval_status, immutable_hash,
                        created_by_type, created_by_id, prompt_version, change_summary)
                   VALUES (%s, %s, %s, 'master_draft', NULL, %s, %s, %s::jsonb,
                           'passed', 'not_required', %s, 'human', 'consumer',
                           NULL, 'adopted draft snapshot')
                   ON CONFLICT (content_version_id) DO NOTHING
                   RETURNING content_version_id, task_id, workspace_id, content_type,
                             version_number, content, structured_blocks,
                             created_by_type, approval_status, immutable_hash""",
                (
                    version_id,
                    workspace_id,
                    task_id,
                    next_number,
                    plain_text,
                    json.dumps(self._jsonable(document.get("blocks", []))),
                    immutable_hash,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                existing = await self.get_draft_snapshot_version(workspace_id, task_id, revision)
                if existing is not None:
                    return existing
                raise ConflictError("snapshot insert raced; retry adopt")
            # blocks
            for position, block in enumerate(document.get("blocks", [])):
                block_text = block.get("text", "")
                await connection.execute(
                    """INSERT INTO content_blocks
                           (workspace_id, task_id, content_version_id, block_type, position, content, content_hash)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (content_version_id, position) DO NOTHING""",
                    (
                        workspace_id,
                        task_id,
                        version_id,
                        block.get("block_type", "paragraph"),
                        position,
                        block_text,
                        hashlib.sha256(block_text.encode("utf-8")).hexdigest(),
                    ),
                )
            await connection.execute(
                """UPDATE consumer_projects
                   SET active_master_version_id=%s, updated_at=NOW()
                   WHERE workspace_id=%s AND task_id=%s""",
                (version_id, workspace_id, task_id),
            )
            await connection.execute(
                """UPDATE consumer_drafts
                   SET last_snapshot_version_id=%s
                   WHERE workspace_id=%s AND task_id=%s""",
                (version_id, workspace_id, task_id),
            )
            return row

    async def get_draft_snapshot_version(self, workspace_id: str, task_id: str, revision: int) -> dict | None:
        version_id = str(uuid5(NAMESPACE_URL, f"brandagent:snapshot:{task_id}:{revision}"))
        return await self.get_version(workspace_id, version_id)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def append_event(self, event: dict) -> None:
        workspace_id = event["workspace_id"]
        task_id = event["task_id"]
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            await connection.execute(
                """INSERT INTO task_events
                       (workspace_id, task_id, event_type, public_payload, workflow_node, request_id)
                   VALUES (%s, %s, %s, %s::jsonb, 'consumer_projects', '')""",
                (
                    workspace_id,
                    task_id,
                    event["event_type"],
                    json.dumps(self._jsonable(event.get("data", {})), ensure_ascii=False),
                ),
            )

    @staticmethod
    def _jsonable(value):
        if isinstance(value, dict):
            return {key: PostgresConsumerProjectStore._jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [PostgresConsumerProjectStore._jsonable(item) for item in value]
        if hasattr(value, "hex") and not isinstance(value, str):
            return str(value)
        return value
