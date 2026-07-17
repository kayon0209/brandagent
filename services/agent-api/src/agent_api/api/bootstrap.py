from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI

from agent_api.application.tasks import TaskWorkflowService
from agent_api.config import Settings
from agent_api.providers.zhipu import ZhipuProvider
from agent_api.mcp.client import RealMCPClient
from agent_api.mcp.context import MCPContextGateway
from agent_api.mcp.channels import MCPChannelValidator
from agent_api.application.channels import ChannelWorkflowService
from agent_api.repositories.postgres_channels import PostgresChannelStore
from agent_api.repositories.postgres_evaluation import PostgresEvaluationStore
from agent_api.evaluation.metrics import EvaluationService
from agent_api.repositories.postgres_knowledge import PostgresKnowledgeRepository
from agent_api.repositories.postgres_tasks import PostgresTaskRepository
from agent_api.repositories.postgres_workflow import PostgresWorkflowRepository
from agent_api.workflow.checkpoint import postgres_checkpointer, verify_checkpoint_isolation

from .main import create_app
from .security import ClerkJWTVerifier


class RuntimeTasks:
    def __init__(self) -> None:
        self.delegate: TaskWorkflowService | None = None

    async def ready(self) -> bool:
        return self.delegate is not None

    def __getattr__(self, name):
        if self.delegate is None:
            async def unavailable(*args, **kwargs):
                raise RuntimeError("Agent API dependencies are not ready")
            return unavailable
        return getattr(self.delegate, name)


def create_production_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    database_url = settings.require_database_url()
    checkpoint_database_url = settings.require_checkpoint_database_url()
    business_role = urlsplit(database_url).username
    checkpoint_role = urlsplit(checkpoint_database_url).username
    if checkpoint_database_url == database_url or not business_role or not checkpoint_role or business_role == checkpoint_role:
        raise RuntimeError("Checkpoint and business database connections must use distinct database roles")
    mcp_url = settings.require_mcp_url()
    authorized_parties = [
        party.strip() for party in (settings.clerk_authorized_parties or "").split(",") if party.strip()
    ]
    if not settings.clerk_audience and not authorized_parties:
        if settings.environment != "development":
            raise RuntimeError("CLERK_AUDIENCE or CLERK_AUTHORIZED_PARTIES is required outside development")
        authorized_parties = ["http://localhost:3000", "http://localhost:3001"]
    verifier = ClerkJWTVerifier(
        jwks_url=settings.clerk_jwks_url or "",
        issuer=settings.clerk_issuer or "",
        audience=settings.clerk_audience or "",
        authorized_parties=authorized_parties,
        dev_mode=(settings.environment == "development"),
    )
    task_repository = PostgresTaskRepository(database_url)
    workflow_repository = PostgresWorkflowRepository(database_url)
    channel_store = PostgresChannelStore(database_url)
    evaluation_store = PostgresEvaluationStore(database_url)
    knowledge_repository = PostgresKnowledgeRepository(database_url)
    provider = ZhipuProvider(api_key=settings.require_glm_key(), model=settings.glm_model)
    mcp_client = RealMCPClient(
        mcp_url,
        workflow_repository,
        workspace_id="system",
        task_id="discovery",
        workflow_node="startup",
        service_token=settings.require_mcp_service_token(),
        timeout_seconds=settings.brand_mcp_timeout_seconds,
    )
    mcp_context = MCPContextGateway(mcp_client)
    runtime = RuntimeTasks()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with AsyncExitStack() as stack:
            await verify_checkpoint_isolation(database_url, checkpoint_database_url)
            await task_repository.open()
            await workflow_repository.open()
            await channel_store.open()
            await evaluation_store.open()
            await knowledge_repository.open()
            stack.push_async_callback(task_repository.close)
            stack.push_async_callback(workflow_repository.close)
            stack.push_async_callback(channel_store.close)
            stack.push_async_callback(evaluation_store.close)
            stack.push_async_callback(knowledge_repository.close)
            await mcp_client.discover()
            saver = await stack.enter_async_context(postgres_checkpointer(checkpoint_database_url))
            runtime.delegate = TaskWorkflowService(
                tasks=task_repository,
                workflow=workflow_repository,
                provider=provider,
                checkpointer=saver,
                context=mcp_context,
                channel_store=channel_store,
                channels=ChannelWorkflowService(
                    store=channel_store,
                    provider=provider,
                    validator=MCPChannelValidator(mcp_client),
                ),
                tools=mcp_client,
                evaluation_store=evaluation_store,
                evaluation=EvaluationService(evaluation_store),
            )
            try:
                yield
            finally:
                runtime.delegate = None

    app = create_app(tasks=runtime, verifier=verifier, knowledge=knowledge_repository)
    app.router.lifespan_context = lifespan
    return app
