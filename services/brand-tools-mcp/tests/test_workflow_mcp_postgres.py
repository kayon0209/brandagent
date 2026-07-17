import hashlib
import json
import os
from uuid import uuid4

import httpx
import psycopg
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agent_api.domain.models import AgentState, Channel, ContentBrief, DecisionOutcome
from agent_api.mcp.client import RealMCPClient
from agent_api.mcp.context import MCPContextGateway
from agent_api.providers.base import LLMProvider, ModelCallResult
from agent_api.repositories.postgres_workflow import PostgresWorkflowRepository
from agent_api.repositories.postgres_channels import PostgresChannelStore
from agent_api.workflow.checkpoint import checkpoint_config, checkpoint_serializer
from agent_api.workflow.graph import build_master_content_graph
from agent_api.workflow.services import WorkflowDependencies
from brand_tools_mcp.repository import BrandToolsRepository
from brand_tools_mcp.tools import create_mcp


pytestmark = pytest.mark.skipif(os.getenv("RUN_AGENT_DB_TESTS") != "true", reason="requires disposable PostgreSQL")


class FakeProvider(LLMProvider):
    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        content = '{"strategy":"verified"}' if prompt_version == "strategy-v1" else "Verified outline"
        return ModelCallResult(content, "fake", "fake-v1", prompt_version, 1, 1, 1, "estimated", 0)


class FakeDecisions:
    async def resolve(self, **kwargs):
        return DecisionOutcome(valid=False, decision="invalid")


@pytest.mark.asyncio
async def test_final_gate_uses_only_current_channel_versions() -> None:
    database_url = os.environ["AGENT_TEST_DATABASE_URL"]
    workspace_id = str(uuid4())
    task_id = str(uuid4())
    old_master_id = str(uuid4())
    current_master_id = str(uuid4())
    old_channel_id = str(uuid4())
    current_channel_id = str(uuid4())
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute(
            "INSERT INTO workspaces(workspace_id,name,slug,created_by) VALUES(%s,'Gate Test',%s,'test')",
            (workspace_id, f"gate-{workspace_id}"),
        )
        await connection.execute(
            "INSERT INTO content_tasks(task_id,workspace_id,user_id,title,status,selected_channels) VALUES(%s,%s,'operator-1','Gate task','draft',ARRAY['wechat_website'])",
            (task_id, workspace_id),
        )
        await connection.execute(
            """INSERT INTO content_versions
            (content_version_id,workspace_id,task_id,content_type,version_number,content,immutable_hash,created_by_type,created_by_id)
            VALUES(%s,%s,%s,'master_draft',1,'old master',%s,'workflow','operator-1'),
                  (%s,%s,%s,'master_draft',2,'current master',%s,'workflow','operator-1')""",
            (old_master_id, workspace_id, task_id, "1" * 64, current_master_id, workspace_id, task_id, "2" * 64),
        )
        await connection.execute(
            """INSERT INTO content_versions
            (content_version_id,workspace_id,task_id,content_type,channel,version_number,master_content_version_id,content,immutable_hash,created_by_type,created_by_id)
            VALUES(%s,%s,%s,'channel_draft','wechat_website',1,%s,'old channel',%s,'model','operator-1'),
                  (%s,%s,%s,'channel_revised','wechat_website',2,%s,'current channel',%s,'model','operator-1')""",
            (old_channel_id, workspace_id, task_id, old_master_id, "3" * 64,
             current_channel_id, workspace_id, task_id, current_master_id, "4" * 64),
        )
        await connection.execute(
            """INSERT INTO approval_requirements
            (workspace_id,task_id,content_version_id,decision_type,required_role,target_snapshot_hash,status)
            VALUES(%s,%s,%s,'channel','brand_reviewer',%s,'satisfied')""",
            (workspace_id, task_id, old_channel_id, "3" * 64),
        )
        await connection.commit()

    store = PostgresChannelStore(database_url)
    await store.open()
    assert await store.approved_channel_versions(workspace_id, task_id) == {}
    with pytest.raises(ValueError, match="Current channel approval set changed"):
        await store.create_final_requirement(
            workspace_id=workspace_id,
            task_id=task_id,
            channel_versions={"wechat_website": old_channel_id},
        )
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute(
            """INSERT INTO approval_requirements
            (workspace_id,task_id,content_version_id,decision_type,required_role,target_snapshot_hash,status)
            VALUES(%s,%s,%s,'channel','brand_reviewer',%s,'satisfied')""",
            (workspace_id, task_id, current_channel_id, "4" * 64),
        )
        await connection.commit()
    current = await store.approved_channel_versions(workspace_id, task_id)
    assert current == {"wechat_website": current_channel_id}
    assert await store.cross_channel_conflicts(workspace_id, task_id, current) == []
    await store.close()


@pytest.mark.asyncio
async def test_workflow_research_node_calls_real_mcp_and_records_tools() -> None:
    database_url = os.environ["AGENT_TEST_DATABASE_URL"]
    workspace_id = str(uuid4())
    task_id = str(uuid4())
    brand_id = str(uuid4())
    product_id = str(uuid4())
    document_id = str(uuid4())
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute("INSERT INTO workspaces(workspace_id,name,slug,created_by) VALUES(%s,'MCP Test',%s,'test')", (workspace_id, f"mcp-{workspace_id}"))
        await connection.execute("INSERT INTO workspace_members(workspace_id,user_id,role,status) VALUES(%s,'operator-1','content_operator','active'),(%s,'reviewer-1','brand_reviewer','active'),(%s,'approver-1','final_approver','active')", (workspace_id, workspace_id, workspace_id))
        await connection.execute("INSERT INTO content_tasks(task_id,workspace_id,user_id,title,status,selected_channels) VALUES(%s,%s,'operator-1','MCP task','draft',ARRAY['wechat_website'])", (task_id, workspace_id))
        await connection.execute(
            """INSERT INTO content_briefs
            (workspace_id,task_id,topic,brand_id,product_id,target_audience,publishing_objective,primary_channel,desired_audience_action)
            VALUES(%s,%s,'Nova',%s,%s,'IT','Explain','wechat_website','Demo')""",
            (workspace_id, task_id, brand_id, product_id),
        )
        await connection.execute("INSERT INTO source_documents(document_id,workspace_id,document_name,document_type,version,authority_level,public_usage_allowed,status,checksum,created_by) VALUES(%s,%s,'Facts','product_fact','v1','primary',TRUE,'active',%s,'test')", (document_id, workspace_id, f"checksum-{document_id}"))
        await connection.execute("INSERT INTO verified_facts(workspace_id,product_id,fact_content,source_document_id,version,authority_level,public_usage_allowed,status) VALUES(%s,%s,'Verified capability',%s,'v1','primary',TRUE,'active')", (workspace_id, product_id, document_id))
        await connection.execute("INSERT INTO brand_guideline_versions(workspace_id,brand_id,version,active) VALUES(%s,%s,'brand-v1',TRUE)", (workspace_id, brand_id))
        await connection.execute("INSERT INTO channel_spec_versions(workspace_id,channel,version,active) VALUES(%s,'wechat_website','channel-v1',TRUE)", (workspace_id,))
        await connection.commit()

    tool_repository = BrandToolsRepository(database_url)
    workflow_repository = PostgresWorkflowRepository(database_url)
    await workflow_repository.open()
    mcp = create_mcp(tool_repository, require_trusted_scope=False)
    app = mcp.streamable_http_app()

    def http_client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mcp.test")

    root_client = RealMCPClient(
        "http://mcp.test/mcp",
        workflow_repository,
        workspace_id=workspace_id,
        task_id=task_id,
        workflow_node="retrieve_brand_context",
        http_client_factory=http_client_factory,
    )
    state = AgentState(
        task_id=task_id,
        workspace_id=workspace_id,
        user_id="operator-1",
        brief=ContentBrief(
            task_id=task_id,
            workspace_id=workspace_id,
            topic="Nova",
            brand_id=brand_id,
            product_id=product_id,
            target_audience="IT",
            publishing_objective="Explain",
            primary_channel=Channel.WECHAT_WEBSITE,
            desired_audience_action="Demo",
        ),
        selected_channels=[Channel.WECHAT_WEBSITE],
    )
    graph = build_master_content_graph(
        WorkflowDependencies(
            provider=FakeProvider(),
            context=MCPContextGateway(root_client),
            versions=workflow_repository,
            decisions=FakeDecisions(),
            runtime=workflow_repository,
        ),
        checkpointer=InMemorySaver(serde=checkpoint_serializer()),
    )
    async with app.router.lifespan_context(app):
        paused = await graph.ainvoke(state, checkpoint_config(workspace_id=workspace_id, task_id=task_id))
    assert paused["master_outline_version_id"] is not None
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        cursor = await connection.execute("SELECT tool_name,output_status FROM tool_call_logs WHERE workspace_id=%s AND task_id=%s", (workspace_id, task_id))
        rows = await cursor.fetchall()
    assert {row[0] for row in rows} == {"get_product_facts", "get_brand_guidelines", "get_channel_spec"}
    assert all(row[1] == "succeeded" for row in rows)
    master_version_id = str(uuid4())
    master_content = "Approved canonical master"
    master_hash = hashlib.sha256(master_content.encode()).hexdigest()
    channel_version_id = str(uuid4())
    channel_content = "Approved channel variant"
    channel_hash = hashlib.sha256(channel_content.encode()).hexdigest()
    decision_id = str(uuid4())
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute(
            """INSERT INTO content_versions
            (content_version_id,workspace_id,task_id,content_type,version_number,content,immutable_hash,created_by_type,created_by_id)
            VALUES(%s,%s,%s,'master_draft',1,%s,%s,'workflow','operator-1')""",
            (master_version_id, workspace_id, task_id, master_content, master_hash),
        )
        brand_requirement_id = str(uuid4())
        final_requirement_id = str(uuid4())
        await connection.execute(
            """INSERT INTO approval_requirements
            (approval_requirement_id,workspace_id,task_id,content_version_id,decision_type,required_role,target_snapshot_hash)
            VALUES(%s,%s,%s,%s,'master_brand','brand_reviewer',%s),
                  (%s,%s,%s,%s,'master_final','final_approver',%s)""",
            (brand_requirement_id, workspace_id, task_id, master_version_id, master_hash,
             final_requirement_id, workspace_id, task_id, master_version_id, master_hash),
        )
        await connection.execute(
            """INSERT INTO human_decisions
            (workspace_id,task_id,content_version_id,approval_requirement_id,decision_type,decision,comment,user_id,user_role,target_snapshot_hash,idempotency_key,request_id)
            VALUES(%s,%s,%s,%s,'master_brand','approve','Brand approved','reviewer-1','brand_reviewer',%s,%s,%s),
                  (%s,%s,%s,%s,'master_final','approve','Final approved','approver-1','final_approver',%s,%s,%s)""",
            (workspace_id, task_id, master_version_id, brand_requirement_id, master_hash, f"brand-{master_version_id}", f"brand-request-{master_version_id}",
             workspace_id, task_id, master_version_id, final_requirement_id, master_hash, f"final-{master_version_id}", f"final-request-{master_version_id}"),
        )
        await connection.execute(
            """INSERT INTO content_versions
            (content_version_id,workspace_id,task_id,content_type,channel,version_number,master_content_version_id,content,immutable_hash,created_by_type,created_by_id)
            VALUES(%s,%s,%s,'channel_draft','wechat_website',1,%s,%s,%s,'model','operator-1')""",
            (channel_version_id, workspace_id, task_id, master_version_id, channel_content, channel_hash),
        )
        channel_requirement_id = str(uuid4())
        await connection.execute(
            """INSERT INTO approval_requirements
            (approval_requirement_id,workspace_id,task_id,content_version_id,decision_type,required_role,target_snapshot_hash)
            VALUES(%s,%s,%s,%s,'channel','brand_reviewer',%s)""",
            (channel_requirement_id, workspace_id, task_id, channel_version_id, channel_hash),
        )
        await connection.execute(
            """INSERT INTO human_decisions
            (workspace_id,task_id,content_version_id,approval_requirement_id,decision_type,decision,comment,user_id,user_role,target_snapshot_hash,idempotency_key,request_id)
            VALUES(%s,%s,%s,%s,'channel','approve','Channel approved','reviewer-1','brand_reviewer',%s,%s,%s)""",
            (workspace_id, task_id, channel_version_id, channel_requirement_id, channel_hash, f"channel-{channel_version_id}", f"channel-request-{channel_version_id}"),
        )
        await connection.commit()
    channel_store = PostgresChannelStore(database_url)
    await channel_store.open()
    requirement = await channel_store.create_final_requirement(
        workspace_id=workspace_id,
        task_id=task_id,
        channel_versions={"wechat_website": channel_version_id},
    )
    await channel_store.close()
    snapshot_hash = requirement["target_snapshot_hash"]
    requirement_id = requirement["approval_requirement_id"]
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute(
            """INSERT INTO human_decisions
            (decision_id,workspace_id,task_id,approval_requirement_id,decision_type,
             decision,comment,user_id,user_role,target_snapshot_hash,idempotency_key,request_id)
            VALUES(%s,%s,%s,%s,'final_package','approve','Approved final package','approver-1','final_approver',%s,%s,%s)""",
            (decision_id, workspace_id, task_id, requirement_id, snapshot_hash, f"decision-{decision_id}", f"request-{decision_id}"),
        )
        await connection.commit()
    export_arguments = {
        "workspace_id": workspace_id,
        "task_id": task_id,
        "actor_id": "approver-1",
        "decision_id": decision_id,
        "target_snapshot_hash": snapshot_hash,
        "idempotency_key": "mcp-export-key-1234",
        "formats": ["json", "markdown"],
    }
    export_mcp = create_mcp(tool_repository, require_trusted_scope=False)
    export_app = export_mcp.streamable_http_app()

    def export_http_client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=export_app), base_url="http://mcp.test")

    export_client = RealMCPClient(
        "http://mcp.test/mcp",
        workflow_repository,
        workspace_id=workspace_id,
        task_id=task_id,
        workflow_node="export_content_package",
        http_client_factory=export_http_client_factory,
    )
    async with export_app.router.lifespan_context(export_app):
        exported = await export_client.call("export_content_package", export_arguments)
        replayed = await export_client.call("export_content_package", export_arguments)
    assert exported["data"]["idempotency_replayed"] is False
    assert replayed["data"]["idempotency_replayed"] is True
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        high_risk_cursor = await connection.execute(
            """SELECT approval_result,approval_decision_id,idempotency_key FROM tool_call_logs
            WHERE workspace_id=%s AND task_id=%s AND tool_name='export_content_package'""",
            (workspace_id, task_id),
        )
        high_risk_rows = await high_risk_cursor.fetchall()
    assert len(high_risk_rows) == 2
    assert all(row[0] == "verified" and str(row[1]) == decision_id and row[2] == "mcp-export-key-1234" for row in high_risk_rows)
    await workflow_repository.close()
