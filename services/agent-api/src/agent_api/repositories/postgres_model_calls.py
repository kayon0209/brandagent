from uuid import uuid4

from psycopg_pool import AsyncConnectionPool


class PostgresModelCallRecorder:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def record(self, payload: dict[str, object]) -> None:
        async with self._pool.connection() as connection:
            await connection.execute("SELECT set_config('app.workspace_id',%s,true)", (str(payload["workspace_id"]),))
            await connection.execute(
                """INSERT INTO model_call_logs
                (model_call_id,workspace_id,task_id,provider,model,prompt_version,latency_ms,
                 input_tokens,output_tokens,usage_source,retry_count,status,error_code)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    str(uuid4()), payload["workspace_id"], payload["task_id"], payload["provider"],
                    payload["model"], payload["prompt_version"], payload["latency_ms"],
                    payload["input_tokens"], payload["output_tokens"], payload["usage_source"],
                    payload["retry_count"], payload["status"], payload["error_code"],
                ),
            )
