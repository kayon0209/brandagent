"""Postgres persistence for the consumer usage ledger (task 13).

usage_ledger (003) with PK (workspace_id, request_id) provides the
idempotency guarantee. Every access is workspace-scoped via RLS.
"""

from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent_api.domain.errors import NotFoundError


class PostgresUsageLedgerStore:
    def __init__(self, database_url: str, *, quota: int = 30000) -> None:
        self._pool = AsyncConnectionPool(database_url, open=False, kwargs={"row_factory": dict_row})
        self._quota = quota

    async def open(self) -> None:
        await self._pool.open()

    async def close(self) -> None:
        await self._pool.close()

    async def _scope(self, connection, workspace_id: str) -> None:
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))

    # ------------------------------------------------------------------
    # workspace bootstrap (creator_profiles row stands in for plan/account)
    # ------------------------------------------------------------------

    async def ensure_workspace(self, workspace_id: str, user_id: str) -> None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            await connection.execute(
                """INSERT INTO workspaces (workspace_id, name, slug, created_by)
                   VALUES (%s, '个人工作区', %s, 'consumer')
                   ON CONFLICT (workspace_id) DO NOTHING""",
                (workspace_id, f"ws-{workspace_id[:12]}"),
            )
            await connection.execute(
                """INSERT INTO creator_profiles (workspace_id, user_id)
                   VALUES (%s, %s)
                   ON CONFLICT (workspace_id, user_id) DO NOTHING""",
                (workspace_id, user_id),
            )

    # ------------------------------------------------------------------
    # ledger entries
    # ------------------------------------------------------------------

    async def find_entry(self, workspace_id: str, request_id: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT workspace_id, request_id, user_id, operation, model,
                          input_tokens, output_tokens, estimated_cost, state
                   FROM usage_ledger
                   WHERE workspace_id=%s AND request_id=%s""",
                (workspace_id, request_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._with_estimated(row)

    @staticmethod
    def _with_estimated(row: dict) -> dict:
        # estimated_tokens is derived from the reserved cost (1e-6 per token)
        if row.get("estimated_tokens") is None:
            cost = row.get("estimated_cost")
            row["estimated_tokens"] = int(float(cost) * 1_000_000) if cost is not None else 0
        return row

    async def insert_entry(self, entry: dict) -> dict | None:
        """Reserve quota atomically; None means the quota check failed.

        Review-P2 TOCTOU fix: committed-usage check and INSERT happen in ONE
        statement under a per-workspace advisory lock, so concurrent reserves
        for the same workspace can never both pass the check.
        """

        estimated = entry.get("estimated_tokens", 0) or 0
        quota = entry.get("quota")
        async with self._pool.connection() as connection:
            await self._scope(connection, entry["workspace_id"])
            if quota is not None:
                await connection.execute(
                    'SELECT pg_advisory_xact_lock(hashtext(%s))',
                    (f"usage-quota:{entry['workspace_id']}",),
                )
                cursor = await connection.execute(
                    """INSERT INTO usage_ledger
                           (workspace_id, request_id, user_id, operation, state,
                            estimated_cost)
                       SELECT %s, %s, %s, %s, 'reserved', %s
                       WHERE %s + COALESCE((
                           SELECT SUM(
                               CASE
                                 WHEN state='settled' THEN
                                     CASE
                                       WHEN input_tokens IS NOT NULL OR output_tokens IS NOT NULL
                                         THEN COALESCE(input_tokens,0)+COALESCE(output_tokens,0)
                                       ELSE CEIL(COALESCE(estimated_cost,0)*1000000)
                                     END
                                 WHEN state='reserved' THEN CEIL(COALESCE(estimated_cost,0)*1000000)
                                 WHEN state='refunded' THEN 0
                               END)
                           FROM usage_ledger
                           WHERE workspace_id=%s AND state IN ('settled','reserved')
                       ), 0) <= %s
                      RETURNING workspace_id, request_id, user_id, operation,
                              model, input_tokens, output_tokens, estimated_cost,
                              state""",
                    (
                        entry["workspace_id"],
                        entry["request_id"],
                        entry["user_id"],
                        entry["operation"],
                        estimated * 0.000001,
                        estimated,
                        entry["workspace_id"],
                        quota,
                    ),
                )
            else:
                cursor = await connection.execute(
                    """INSERT INTO usage_ledger
                           (workspace_id, request_id, user_id, operation, state,
                            estimated_cost)
                       VALUES (%s, %s, %s, %s, 'reserved', %s)
                    RETURNING workspace_id, request_id, user_id, operation,
                              model, input_tokens, output_tokens, estimated_cost,
                              state""",
                    (
                        entry["workspace_id"],
                        entry["request_id"],
                        entry["user_id"],
                        entry["operation"],
                        estimated * 0.000001,
                    ),
                )
            row = await cursor.fetchone()
            return self._with_estimated(row) if row is not None else None

    async def update_entry(self, workspace_id: str, request_id: str, updates: dict) -> dict:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """UPDATE usage_ledger
                   SET state=%s,
                       input_tokens=%s,
                       output_tokens=%s,
                       model=%s,
                       estimated_cost=%s,
                       settled_at=CASE WHEN %s='settled' THEN NOW() ELSE NULL END
                   WHERE workspace_id=%s AND request_id=%s
                   RETURNING workspace_id, request_id, user_id, operation,
                             model, input_tokens, output_tokens, estimated_cost,
                             state""",
                (
                    updates.get("state"),
                    updates.get("input_tokens"),
                    updates.get("output_tokens"),
                    updates.get("model"),
                    updates.get("estimated_cost"),
                    updates.get("state"),
                    workspace_id,
                    request_id,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                raise NotFoundError(f"usage entry {request_id} not found")
            return self._with_estimated(row)

    async def committed_tokens(self, workspace_id: str) -> int:
        """Settled usage plus open reservations (both count against quota)."""

        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT COALESCE(SUM(
                       CASE
                         WHEN state='settled' THEN
                             CASE
                               WHEN input_tokens IS NOT NULL OR output_tokens IS NOT NULL
                                 THEN COALESCE(input_tokens,0)+COALESCE(output_tokens,0)
                               ELSE CEIL(COALESCE(estimated_cost,0)*1000000)
                             END
                         WHEN state='reserved' THEN CEIL(COALESCE(estimated_cost,0) * 1000000)
                         ELSE 0
                       END),0) AS total
                   FROM usage_ledger
                   WHERE workspace_id=%s""",
                (workspace_id,),
            )
            return int((await cursor.fetchone())["total"])

    async def usage_summary(self, workspace_id: str) -> dict | None:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT 1 AS present FROM creator_profiles
                   WHERE workspace_id=%s LIMIT 1""",
                (workspace_id,),
            )
            if await cursor.fetchone() is None:
                return None
            cursor = await connection.execute(
                """SELECT COALESCE(SUM(
                       CASE
                         WHEN input_tokens IS NOT NULL OR output_tokens IS NOT NULL
                           THEN COALESCE(input_tokens,0)+COALESCE(output_tokens,0)
                         ELSE CEIL(COALESCE(estimated_cost,0)*1000000)
                       END),0) AS used
                   FROM usage_ledger
                   WHERE workspace_id=%s AND state='settled'""",
                (workspace_id,),
            )
            used = int((await cursor.fetchone())["used"])
            return {"workspace_id": workspace_id, "used": used, "quota": self._quota}
