import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from brand_tools_mcp.contracts import TOOL_CAPABILITIES
from brand_tools_mcp.tools import create_mcp


class FakeStore:
    async def open(self): return None
    async def close(self): return None
    async def search_documents(self, workspace_id, query, limit): return [{"document_id": "doc-1", "document_name": query}]
    async def product_facts(self, workspace_id, product_id): return [{"fact_id": "fact-1", "fact_content": "Verified capability", "source_document_id": "doc-1"}]
    async def brand_guidelines(self, workspace_id, brand_id): return {"guideline_version_id": "g1", "version": "v1"}
    async def channel_spec(self, workspace_id, channel): return {"channel_spec_version_id": "c1", "channel": channel, "version": "v1", "length_rules": {}, "forbidden_patterns": []}
    async def save_version(self, *args): return {"content_version_id": "v1", "immutable_hash": "a" * 64, "version_number": 1}
    async def verify_high_risk(self, *args): return {"decision_id": "d1"}
    async def content_package(self, workspace_id, task_id): return {"task_id": task_id, "versions": []}
    async def record_idempotent_result(self, workspace_id, actor_id, action, target, idempotency_key, request, result_factory): return await result_factory(), False


@pytest.mark.asyncio
async def test_real_streamable_http_transport_discovers_and_calls_nine_tools() -> None:
    mcp = create_mcp(FakeStore(), require_trusted_scope=False)
    app = mcp.streamable_http_app()
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://mcp.test") as http_client:
            async with streamable_http_client("http://mcp.test/mcp", http_client=http_client) as (read_stream, write_stream, _session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    discovered = await session.list_tools()
                    names = {tool.name for tool in discovered.tools}
                    assert names == set(TOOL_CAPABILITIES)
                    result = await session.call_tool(
                        "get_product_facts",
                        {"workspace_id": "workspace-1", "product_id": "product-1"},
                    )
                    assert result.isError is False
                    assert result.structuredContent["data"]["authoritative"] is True


def test_capability_classification_is_explicit() -> None:
    assert TOOL_CAPABILITIES["get_product_facts"].value == "read"
    assert TOOL_CAPABILITIES["save_content_version"].value == "write"
    assert TOOL_CAPABILITIES["export_content_package"].value == "high_risk"
