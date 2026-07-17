from __future__ import annotations

import json
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


class PostgresEvaluationStore:
    def __init__(self, database_url: str) -> None:
        self._pool = AsyncConnectionPool(database_url, open=False, kwargs={"row_factory": dict_row})

    async def open(self) -> None:
        await self._pool.open()

    async def close(self) -> None:
        await self._pool.close()

    async def _scope(self, connection, workspace_id: str) -> None:
        await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (workspace_id,))

    async def measurement_rows(self, workspace_id: str) -> dict[str, list[dict]]:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            reviews = await connection.execute(
                """SELECT r.task_id,r.review_type,r.passed,r.max_severity,v.content_type
                FROM review_results r JOIN content_versions v
                  ON v.workspace_id=r.workspace_id AND v.content_version_id=r.content_version_id
                WHERE r.workspace_id=%s""", (workspace_id,),
            )
            tasks = await connection.execute("SELECT task_id,status FROM content_tasks WHERE workspace_id=%s", (workspace_id,))
            tools = await connection.execute("SELECT task_id,output_status,capability,latency_ms,error_code FROM tool_call_logs WHERE workspace_id=%s", (workspace_id,))
            models = await connection.execute("SELECT task_id,status,latency_ms,estimated_cost,usage_source FROM model_call_logs WHERE workspace_id=%s", (workspace_id,))
            versions = await connection.execute("SELECT task_id,created_by_type FROM content_versions WHERE workspace_id=%s", (workspace_id,))
            return {"reviews": list(await reviews.fetchall()), "tasks": list(await tasks.fetchall()), "tools": list(await tools.fetchall()), "models": list(await models.fetchall()), "versions": list(await versions.fetchall())}

    async def persist_run(self, workspace_id: str, metrics: list[dict], bad_cases: list[dict]) -> str:
        run_id = str(uuid4())
        async with self._pool.connection() as connection, connection.transaction():
            await self._scope(connection, workspace_id)
            dataset_size_cursor = await connection.execute("SELECT COUNT(*) AS count FROM content_tasks WHERE workspace_id=%s", (workspace_id,))
            dataset_size = (await dataset_size_cursor.fetchone())["count"]
            await connection.execute(
                """INSERT INTO evaluation_runs
                (evaluation_run_id,workspace_id,evaluation_version,code_version,status,dataset_size,limitations,started_at,completed_at)
                VALUES(%s,%s,'brandflow-eval-v1','workspace-current','completed',%s,%s,NOW(),NOW())""",
                (run_id, workspace_id, dataset_size, "Metrics use persisted workspace events only; unavailable provider measurements remain null."),
            )
            for metric in metrics:
                await connection.execute(
                    """INSERT INTO evaluation_metrics
                    (workspace_id,evaluation_run_id,metric_group,metric_name,metric_value,metric_payload,measurement_source)
                    VALUES(%s,%s,%s,%s,%s,%s,'deterministic')""",
                    (workspace_id, run_id, metric["category"], metric["name"], metric["value"], json.dumps(metric)),
                )
            for case in bad_cases:
                await connection.execute(
                    """INSERT INTO bad_cases
                    (workspace_id,evaluation_run_id,task_id,category,severity,summary,evidence)
                    VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                    (workspace_id, run_id, case.get("task_id"), case["category"], case["severity"], case["summary"], json.dumps({"reproducible": case["reproducible"]})),
                )
        return run_id

    async def load_run(self, workspace_id: str, run_id: str) -> dict:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            run_cursor = await connection.execute(
                "SELECT * FROM evaluation_runs WHERE workspace_id=%s AND evaluation_run_id=%s",
                (workspace_id, run_id),
            )
            run = await run_cursor.fetchone()
            if not run:
                raise ValueError("Evaluation run not found")
            metrics_cursor = await connection.execute(
                "SELECT metric_payload FROM evaluation_metrics WHERE workspace_id=%s AND evaluation_run_id=%s ORDER BY metric_group,metric_name",
                (workspace_id, run_id),
            )
            cases_cursor = await connection.execute(
                "SELECT bad_case_id,task_id,category,severity,summary,status,evidence FROM bad_cases WHERE workspace_id=%s AND evaluation_run_id=%s ORDER BY created_at",
                (workspace_id, run_id),
            )
            return {
                "run": {key: str(value) if key in {"evaluation_run_id", "workspace_id"} else value for key, value in run.items()},
                "metrics": [row["metric_payload"] for row in await metrics_cursor.fetchall()],
                "bad_cases": [{key: str(value) if key in {"bad_case_id", "task_id"} and value is not None else value for key, value in row.items()} for row in await cases_cursor.fetchall()],
            }

    async def versions(self, workspace_id: str, task_id: str, parent_id: str, current_id: str) -> tuple[dict, dict]:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT content_version_id,content,created_by_type,created_by_id,prompt_version,created_at,change_summary
                FROM content_versions WHERE workspace_id=%s AND task_id=%s AND content_version_id=ANY(%s)""",
                (workspace_id, task_id, [parent_id, current_id]),
            )
            rows = {str(row["content_version_id"]): row for row in await cursor.fetchall()}
            if set(rows) != {parent_id, current_id}:
                raise ValueError("Version not found")
            return rows[parent_id], rows[current_id]

    async def bad_cases(self, workspace_id: str) -> list[dict]:
        async with self._pool.connection() as connection:
            await self._scope(connection, workspace_id)
            cursor = await connection.execute(
                """SELECT bad_case_id,evaluation_run_id,task_id,category,severity,summary,status,evidence,created_at
                FROM bad_cases WHERE workspace_id=%s ORDER BY created_at DESC LIMIT 200""", (workspace_id,),
            )
            return [{key: str(value) if key in {"bad_case_id", "evaluation_run_id", "task_id"} and value is not None else value for key, value in row.items()} for row in await cursor.fetchall()]
