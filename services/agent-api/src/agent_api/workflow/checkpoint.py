from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.base import BaseCheckpointSaver
import psycopg


def checkpoint_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_msgpack_modules=[
            ("agent_api.domain.models", "AgentState"),
            ("agent_api.domain.models", "ContentBrief"),
            ("agent_api.domain.models", "ReviewSummary"),
            ("agent_api.domain.models", "DecisionOutcome"),
            ("agent_api.domain.models", "Channel"),
            ("agent_api.domain.models", "TaskStatus"),
        ],
    )


class FencedCheckpointer(BaseCheckpointSaver):
    def __init__(self, delegate, lease_authority) -> None:
        super().__init__(serde=delegate.serde)
        self._delegate = delegate
        self._lease_authority = lease_authority

    @property
    def config_specs(self):
        return self._delegate.config_specs

    def get_next_version(self, current, channel):
        return self._delegate.get_next_version(current, channel)

    async def aget_tuple(self, config):
        return await self._delegate.aget_tuple(config)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        async for item in self._delegate.alist(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(self, config, checkpoint, metadata, new_versions):
        async with self._lease_authority.checkpoint_fence():
            return await self._delegate.aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        async with self._lease_authority.checkpoint_fence():
            return await self._delegate.aput_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id):
        async with self._lease_authority.checkpoint_fence():
            return await self._delegate.adelete_thread(thread_id)


def checkpoint_config(*, workspace_id: str, task_id: str) -> dict[str, dict[str, str]]:
    if not workspace_id or not task_id:
        raise ValueError("workspace_id and task_id are required")
    return {
        "configurable": {
            "thread_id": f"{workspace_id}:{task_id}",
            "checkpoint_ns": f"workspace:{workspace_id}",
        }
    }


async def _database_identity(database_url: str) -> tuple[str, str, str]:
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        cursor = await connection.execute("SELECT current_database(),current_user,current_schema()")
        row = await cursor.fetchone()
        return str(row[0]), str(row[1]), str(row[2])


async def verify_checkpoint_isolation(business_database_url: str, checkpoint_database_url: str) -> None:
    business_database, business_role, business_schema = await _database_identity(business_database_url)
    checkpoint_database, checkpoint_role, checkpoint_schema = await _database_identity(checkpoint_database_url)
    if business_role == checkpoint_role:
        raise RuntimeError("Checkpoint and business connections resolved to the same database role")
    if business_database == checkpoint_database and business_schema == checkpoint_schema:
        raise RuntimeError("Checkpoint and business connections resolved to the same database schema")


@asynccontextmanager
async def postgres_checkpointer(database_url: str) -> AsyncIterator[AsyncPostgresSaver]:
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("A PostgreSQL connection URL is required")
    async with AsyncPostgresSaver.from_conn_string(database_url, serde=checkpoint_serializer()) as saver:
        await saver.setup()
        yield saver
