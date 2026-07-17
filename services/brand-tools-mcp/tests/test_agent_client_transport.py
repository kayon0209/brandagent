import asyncio

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from agent_api.mcp.client import MCPExecutionError, RealMCPClient
from brand_tools_mcp.tools import create_mcp

from test_transport_contract import FakeStore


class Recorder:
    def __init__(self) -> None:
        self.rows = []

    async def record_tool_call(self, payload):
        self.rows.append(payload)


@pytest.mark.asyncio
async def test_agent_client_uses_real_transport_and_sanitized_log() -> None:
    mcp = create_mcp(FakeStore(), require_trusted_scope=False)
    app = mcp.streamable_http_app()
    recorder = Recorder()

    def client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mcp.test")

    client = RealMCPClient(
        "http://mcp.test/mcp",
        recorder,
        workspace_id="workspace-1",
        task_id="task-1",
        workflow_node="retrieve_brand_context",
        http_client_factory=client_factory,
    )
    async with app.router.lifespan_context(app):
        assert len(await client.discover()) == 9
        result = await client.call(
            "get_product_facts",
            {"workspace_id": "workspace-1", "product_id": "product-1", "secret": "must-not-log"},
        )
    assert result["data"]["authoritative"] is True
    assert recorder.rows[0]["tool_name"] == "get_product_facts"
    assert "secret" not in recorder.rows[0]["sanitized_input"]


class UnavailableApplication:
    def __init__(self, delay: float = 0) -> None:
        self.calls = 0
        self.delay = delay

    async def __call__(self, scope, receive, send) -> None:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        await send({"type": "http.response.start", "status": 503, "headers": []})
        await send({"type": "http.response.body", "body": b"unavailable"})


@pytest.mark.asyncio
async def test_agent_client_retries_unavailable_server_and_logs_failure() -> None:
    application = UnavailableApplication()
    recorder = Recorder()

    def client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://localhost")

    client = RealMCPClient(
        "http://localhost/mcp", recorder, workspace_id="w", task_id="t", workflow_node="node",
        max_attempts=2, http_client_factory=client_factory,
    )
    with pytest.raises(MCPExecutionError) as caught:
        await client.call("get_product_facts", {"workspace_id": "w", "product_id": "p"})
    assert caught.value.code == "MCP_UNAVAILABLE"
    assert application.calls >= 2
    assert recorder.rows[-1]["output_status"] == "failed"


@pytest.mark.asyncio
async def test_agent_client_times_out_and_records_stage_aware_failure() -> None:
    application = UnavailableApplication(delay=0.05)
    recorder = Recorder()

    def client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://localhost")

    client = RealMCPClient(
        "http://localhost/mcp",
        recorder,
        workspace_id="w",
        task_id="t",
        workflow_node="retrieve_brand_context",
        timeout_seconds=0.01,
        max_attempts=1,
        http_client_factory=client_factory,
    )
    with pytest.raises(MCPExecutionError) as caught:
        await client.call("get_product_facts", {"workspace_id": "w", "product_id": "p"})
    assert caught.value.code == "MCP_TIMEOUT"
    assert recorder.rows[-1]["output_status"] == "timed_out"
    assert recorder.rows[-1]["workflow_node"] == "retrieve_brand_context"


@pytest.mark.asyncio
async def test_agent_client_rejects_invalid_tool_envelope() -> None:
    server = FastMCP(
        "invalid",
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @server.tool(name="get_product_facts", structured_output=True)
    async def invalid_tool(workspace_id: str, product_id: str) -> dict[str, object]:
        return {"unexpected": True}

    application = server.streamable_http_app()
    recorder = Recorder()

    def client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://localhost")

    client = RealMCPClient(
        "http://localhost/mcp", recorder, workspace_id="w", task_id="t", workflow_node="node",
        max_attempts=1, http_client_factory=client_factory,
    )
    async with application.router.lifespan_context(application):
        with pytest.raises(MCPExecutionError) as caught:
            await client.call("get_product_facts", {"workspace_id": "w", "product_id": "p"})
    assert caught.value.code == "MCP_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_agent_client_refuses_non_idempotent_write_before_transport() -> None:
    application = UnavailableApplication()
    recorder = Recorder()

    def client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://localhost")

    client = RealMCPClient(
        "http://localhost/mcp", recorder, workspace_id="w", task_id="t", workflow_node="save",
        http_client_factory=client_factory,
    )
    with pytest.raises(MCPExecutionError) as caught:
        await client.call("save_content_version", {"workspace_id": "w", "task_id": "t", "content": "draft"})
    assert caught.value.code == "MCP_IDEMPOTENCY_REQUIRED"
    assert application.calls == 0
