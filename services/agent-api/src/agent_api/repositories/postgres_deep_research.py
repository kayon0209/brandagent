"""Postgres persistence for deep research runs (009 schema).

Same discipline as PostgresConsumerProjectStore: every access is
workspace-scoped through app.workspace_id (RLS fail-closed), pools
are injected per-service and opened in the app lifespan.
"""

from __future__ import annotations

import json

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent_api.domain.errors import NotFoundError

_RUN_COLUMNS = """run_id, workspace_id, question, audience, scope_hint, status,
   planned_directions, candidate_cards, synthesis, directions_completed,
   citations_valid, citations_invalid, search_calls, error,
   tokens_estimated, tokens_used, request_id, created_by, created_at,
   cancel_requested_at, completed_at"""


def _row_to_run(row) -> dict:
    from uuid import UUID as _UUID

    run = dict(row)
    # psycopg returns UUID columns as uuid objects; every store method
    # takes str workspace ids (and set_config needs TEXT, not uuid).
    for key in ("run_id", "workspace_id"):
        value = run.get(key)
        if isinstance(value, _UUID):
            run[key] = str(value)
    for key in ("planned_directions", "candidate_cards"):
        value = run.get(key)
        if isinstance(value, str):
            try:
                run[key] = json.loads(value)
            except ValueError:
                run[key] = []
    for key in ("cancel_requested_at", "completed_at", "created_at"):
        if run.get(key) is not None and not isinstance(run.get(key), str):
            run[key] = str(run[key])
    return run


class PostgresDeepResearchStore:
    def __init__(self, database_url: str) -> None:
        self._pool = AsyncConnectionPool(database_url, open=False, kwargs={"row_factory": dict_row})

    async def open(self) -> None:
        await self._pool.open()

    async def close(self) -> None:
        await self._pool.close()

    async def _scope(self, connection, workspace_id: str) -> None:
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))

    async def _ensure_workspace(self, connection, workspace_id: str) -> None:
        await connection.execute(
            """INSERT INTO workspaces (workspace_id, name, slug, created_by)
               VALUES (%s, '个人工作区', %s, 'consumer')
               ON CONFLICT (workspace_id) DO NOTHING""",
            (workspace_id, f"ws-{workspace_id[:12]}"),
        )

    # ------------------------------------------------------------------
    # runs
    # ------------------------------------------------------------------

    async def insert_run(self, run: dict) -> dict:
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, run["workspace_id"])
            await self._ensure_workspace(connection, run["workspace_id"])
            cursor = await connection.execute(
                f"""INSERT INTO deep_research_runs
                        (run_id, workspace_id, question, audience, scope_hint, status,
                         request_id, created_by, created_at)
                    VALUES (%s, %s, %s, %s, %s, 'planned', %s, %s, %s)
                    RETURNING {_RUN_COLUMNS}""",
                (
                    run["run_id"], run["workspace_id"], run["question"],
                    run["audience"], run["scope_hint"],
                    run["request_id"], run["created_by"], run["created_at"],
                ),
            )
            return _row_to_run(await cursor.fetchone())

    async def get_run(self, workspace_id: str, run_id: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                f"SELECT {_RUN_COLUMNS} FROM deep_research_runs WHERE run_id = %s",
                (run_id,),
            )
            row = await cursor.fetchone()
            return _row_to_run(row) if row is not None else None

    async def find_run_by_request(self, workspace_id: str, request_id: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                f"SELECT {_RUN_COLUMNS} FROM deep_research_runs WHERE request_id = %s LIMIT 1",
                (request_id,),
            )
            row = await cursor.fetchone()
            return _row_to_run(row) if row is not None else None

    async def list_runs(self, workspace_id: str, limit: int = 20) -> list[dict]:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                f"""SELECT {_RUN_COLUMNS} FROM deep_research_runs
                    ORDER BY created_at DESC LIMIT %s""",
                (limit,),
            )
            return [_row_to_run(row) for row in await cursor.fetchall()]

    async def update_run(self, workspace_id: str, run_id: str, updates: dict) -> dict:
        allowed = {
            "status", "planned_directions", "candidate_cards", "synthesis",
            "directions_completed", "citations_valid", "citations_invalid",
            "search_calls", "error", "tokens_estimated", "tokens_used",
            "cancel_requested_at", "completed_at",
        }
        fields = [key for key in updates if key in allowed]
        if not fields:
            run = await self.get_run(workspace_id, run_id)
            if run is None:
                raise NotFoundError("Research run not found")
            return run
        assignments = []
        values: list = []
        for key in fields:
            value = updates[key]
            if key in ("planned_directions", "candidate_cards"):
                assignments.append(f"{key} = %s::jsonb")
                values.append(json.dumps(value, ensure_ascii=False))
            else:
                assignments.append(f"{key} = %s")
                values.append(value)
        values.extend([run_id])
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                f"UPDATE deep_research_runs SET {', '.join(assignments)} WHERE run_id = %s RETURNING {_RUN_COLUMNS}",
                tuple(values),
            )
            row = await cursor.fetchone()
            if row is None:
                raise NotFoundError("Research run not found")
            return _row_to_run(row)

    async def request_cancel(self, workspace_id: str, run_id: str) -> dict:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                f"""UPDATE deep_research_runs
                       SET cancel_requested_at = NOW()
                     WHERE run_id = %s AND status IN ('planned','running')
                     RETURNING {_RUN_COLUMNS}""",
                (run_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                run = await self.get_run(workspace_id, run_id)
                if run is None:
                    raise NotFoundError("Research run not found")
                return run  # finished run: cancel is a no-op returning the row
            return _row_to_run(row)

    async def find_orphans(self) -> list[dict]:
        """Restart-orphaned runs (planned/running) across ALL workspaces.

        Called at startup: a service restart kills every in-process
        orchestration task, so any non-terminal run row is by definition
        abandoned.

        RLS gap fix (010): deep_research_runs is FORCE RLS and the
        business role is neither superuser nor BYPASSRLS, so a plain
        table scan would (correctly) see zero rows here. This method
        instead calls the restricted security-definer entry
        deep_research_list_orphaned_runs(), which returns ONLY the
        minimal identification columns (run_id, workspace_id,
        request_id, created_by) — never question/synthesis/candidate
        content — and is granted to the business role alone. It is not
        a generic cross-workspace read path; every caller must be a
        recovery step.
        """
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """SELECT run_id, workspace_id, request_id, created_by
                     FROM deep_research_list_orphaned_runs()""",
            )
            orphans = []
            for row in await cursor.fetchall():
                from uuid import UUID as _UUID

                orphan = dict(row)
                for key in ("run_id", "workspace_id"):
                    value = orphan.get(key)
                    if isinstance(value, _UUID):
                        orphan[key] = str(value)
                orphans.append(orphan)
            return orphans

    async def fail_orphan(self, run_id: str) -> bool:
        """Fail exactly one restart-orphaned run through the 010 entry.

        Terminal and unknown runs are refused (False); the honest
        error message is FIXED by the migration so every caller shows
        identical wording. Scoped to the one recovery-shaped mutation
        (planned/running -> failed); not a general write path.
        """
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT deep_research_fail_orphaned_run(%s) AS failed",
                (run_id,),
            )
            row = await cursor.fetchone()
            return bool(row and row.get("failed"))

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------

    async def append_event(self, event: dict) -> None:
        async with self._pool.connection() as connection:
            await self._scope(connection, event["workspace_id"])
            await connection.execute(
                """INSERT INTO deep_research_events
                       (workspace_id, run_id, event_type, event_version,
                        public_payload, request_id)
                   VALUES (%s, %s, %s, %s, %s::jsonb, %s)""",
                (
                    event["workspace_id"], event["run_id"], event["event_type"],
                    event.get("event_version", "1.0"),
                    json.dumps(event.get("public_payload", {}), ensure_ascii=False),
                    event.get("request_id", ""),
                ),
            )

    async def list_events(self, workspace_id: str, run_id: str, after_event_id: int) -> list[dict]:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT event_id, event_type, event_version, public_payload, created_at
                     FROM deep_research_events
                    WHERE run_id = %s AND event_id > %s
                    ORDER BY event_id""",
                (run_id, after_event_id),
            )
            rows = await cursor.fetchall()
            events = []
            for row in rows:
                payload = row.get("public_payload")
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except ValueError:
                        payload = {}
                events.append(
                    {
                        "event_id": row["event_id"],
                        "event_type": row["event_type"],
                        "event_version": row.get("event_version", "1.0"),
                        "public_payload": payload or {},
                        "created_at": str(row["created_at"]),
                    }
                )
            return events
