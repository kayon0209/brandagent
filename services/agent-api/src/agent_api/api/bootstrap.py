from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI

from agent_api.application.tasks import TaskWorkflowService
from agent_api.application.materials import HeuristicDistiller, MaterialService, SimpleTextParser
from agent_api.application.consumer_projects import ConsumerProjectService
from agent_api.application.drafts import DraftService
from agent_api.application.draft_generation import DraftGenerationService
from agent_api.config import Settings
from agent_api.providers.zhipu import ZhipuProvider
from agent_api.mcp.client import RealMCPClient
from agent_api.mcp.context import MCPContextGateway
from agent_api.mcp.channels import MCPChannelValidator
from agent_api.application.channels import ChannelWorkflowService
from agent_api.repositories.postgres_channels import PostgresChannelStore
from agent_api.repositories.postgres_consumer_projects import PostgresConsumerProjectStore
from agent_api.repositories.postgres_evaluation import PostgresEvaluationStore
from agent_api.evaluation.metrics import EvaluationService
from agent_api.repositories.postgres_knowledge import PostgresKnowledgeRepository
from agent_api.repositories.postgres_materials import PostgresMaterialStore
from agent_api.repositories.postgres_tasks import PostgresTaskRepository
from agent_api.repositories.postgres_workflow import PostgresWorkflowRepository
from agent_api.workflow.checkpoint import postgres_checkpointer, verify_checkpoint_isolation
from agent_api.workflow.consumer_graph import GraphCandidateGenerator
from agent_api.application.platform_variants import ConsumerChannelGeneratorAdapter

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
        if settings.auth_mode != "dev":
            raise RuntimeError("CLERK_AUDIENCE or CLERK_AUTHORIZED_PARTIES is required outside dev auth mode")
        authorized_parties = ["http://localhost:3000", "http://localhost:3001"]
    if settings.auth_mode == "dev" and settings.environment == "production":
        # Security review P2: a stray AUTH_MODE=dev must never silently
        # disable authentication in a production deployment.
        raise RuntimeError("AUTH_MODE=dev is not allowed when ENVIRONMENT=production")
    verifier = ClerkJWTVerifier(
        jwks_url=settings.clerk_jwks_url or "",
        issuer=settings.clerk_issuer or "",
        audience=settings.clerk_audience or "",
        authorized_parties=authorized_parties,
        dev_mode=(settings.auth_mode == "dev"),
    )
    task_repository = PostgresTaskRepository(database_url)
    workflow_repository = PostgresWorkflowRepository(database_url)
    channel_store = PostgresChannelStore(database_url)
    evaluation_store = PostgresEvaluationStore(database_url)
    knowledge_repository = PostgresKnowledgeRepository(database_url)
    material_store = PostgresMaterialStore(database_url)
    material_service = MaterialService(
        store=material_store,
        parser=SimpleTextParser(),
        distiller=HeuristicDistiller(),
    )
    # The provider must exist before every consumer service below wires it.
    provider = ZhipuProvider(
        api_key=settings.require_glm_key(),
        model=settings.glm_model,
        base_url=settings.glm_base_url,
    )
    consumer_project_store = PostgresConsumerProjectStore(database_url)
    consumer_projects = ConsumerProjectService(store=consumer_project_store)
    consumer_drafts = DraftService(store=consumer_project_store)
    consumer_generation = DraftGenerationService(
        store=consumer_project_store,
        generator=GraphCandidateGenerator(provider=provider),
        projects=consumer_projects,
    )
    from agent_api.repositories.postgres_suggestions import PostgresSuggestionStore
    from agent_api.application.editorial_assist import EditorialAssistService

    suggestion_store = PostgresSuggestionStore(database_url, draft_store=consumer_project_store)
    consumer_assist = EditorialAssistService(store=suggestion_store, provider=provider)

    from agent_api.application.platform_variants import PlatformVariantService
    from agent_api.repositories.postgres_consumer_variants import PostgresConsumerVariantStore

    variant_store = PostgresConsumerVariantStore(database_url, project_store=consumer_project_store)
    consumer_variants = PlatformVariantService(
        store=variant_store,
        generator=ConsumerChannelGeneratorAdapter(provider=provider),
        channels=("wechat_website", "xiaohongshu", "video_script_60s"),
    )

    from agent_api.application.usage import UsageLedgerService
    from agent_api.repositories.postgres_usage import PostgresUsageLedgerStore

    usage_store = PostgresUsageLedgerStore(database_url)
    consumer_usage = UsageLedgerService(store=usage_store)

    # round-3: six-layer author style distillation shares the consumer
    # project store pool (RLS-scoped reads/writes on style_reports)
    from agent_api.application.style_distillation import StyleDistillationService

    consumer_style = StyleDistillationService(store=consumer_project_store, provider=provider)

    # Phase 6 deep research (user-approved 2026-09-08): bounded multi-agent
    # orchestration over the disposable Tavily channel. Enabled only when
    # the key is present so B-end-only deployments keep booting.
    from agent_api.application.deep_research import DeepResearchService
    from agent_api.repositories.postgres_deep_research import PostgresDeepResearchStore
    from agent_api.research.search_provider import TavilySearchProvider

    deep_research_store = PostgresDeepResearchStore(database_url)
    deep_research_service = None
    if settings.tavily_api_key is not None and settings.tavily_api_key.get_secret_value():
        deep_research_service = DeepResearchService(
            store=deep_research_store,
            provider=provider,
            search=TavilySearchProvider(api_key=settings.tavily_api_key.get_secret_value()),
            ledger=consumer_usage,
            parallelism=settings.deep_research_parallelism,
            estimated_tokens=settings.deep_research_estimated_tokens,
        )

    class ConsumerApps:
        """ConsumerProjectsApp protocol bundle wired into create_app."""

        def __init__(self, *, channel_validator) -> None:
            self.projects = consumer_projects
            self.drafts = consumer_drafts
            self.generation = consumer_generation
            self.assist = consumer_assist
            self.variants = consumer_variants
            self.usage = consumer_usage
            self.usage_ledger = consumer_usage
            # P2-3: workspace-usable channel listing (custom channels via
            # the MCP spec table); falls back to the built-in previews
            # when the MCP service is unreachable
            self.channel_validator = channel_validator
            self.style = consumer_style
            # Phase 6: deep research bundle (service + the join seam)
            self.research = deep_research_service
            self.materials = material_service
            # app.projects (consumer_projects) already exposes link_excerpt

    mcp_client = RealMCPClient(
        mcp_url,
        workflow_repository,
        workspace_id="system",
        task_id="discovery",
        workflow_node="startup",
        service_token=settings.require_mcp_service_token(),
        timeout_seconds=settings.brand_mcp_timeout_seconds,
    )
    consumer_apps = ConsumerApps(channel_validator=MCPChannelValidator(mcp_client))
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
            await material_store.open()
            await consumer_project_store.open()
            await suggestion_store.open()
            await variant_store.open()
            await usage_store.open()
            await deep_research_store.open()
            stack.push_async_callback(task_repository.close)
            stack.push_async_callback(workflow_repository.close)
            stack.push_async_callback(channel_store.close)
            stack.push_async_callback(evaluation_store.close)
            stack.push_async_callback(knowledge_repository.close)
            stack.push_async_callback(material_store.close)
            stack.push_async_callback(consumer_project_store.close)
            stack.push_async_callback(suggestion_store.close)
            stack.push_async_callback(variant_store.close)
            stack.push_async_callback(usage_store.close)
            stack.push_async_callback(deep_research_store.close)
            stack.push_async_callback(provider.aclose)
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

    app = create_app(
        tasks=runtime,
        verifier=verifier,
        knowledge=knowledge_repository,
        materials=material_service,
        consumer_apps=consumer_apps,
    )
    app.router.lifespan_context = lifespan
    return app
