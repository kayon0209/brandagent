import httpx
import pytest

from brand_tools_mcp.security import ServiceAuthMiddleware, TrustedCallScope, require_scope


async def scoped_application(scope, receive, send) -> None:
    trusted = require_scope()
    body = f"{trusted.workspace_id}|{trusted.task_id}|{trusted.actor_id}".encode()
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": body})


@pytest.mark.asyncio
async def test_mcp_auth_fails_closed_without_complete_trusted_scope() -> None:
    application = ServiceAuthMiddleware(scoped_application, "service-secret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://mcp.test") as client:
        missing = await client.post("/mcp", headers={"Authorization": "Bearer service-secret"})
        wrong = await client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer wrong",
                "X-BrandFlow-Workspace": "workspace-1",
                "X-BrandFlow-Task": "task-1",
                "X-BrandFlow-Actor": "actor-1",
            },
        )
    assert missing.status_code == 200
    assert wrong.status_code == 401
    # Token-only auth uses default scope values
    assert missing.text == "system|discovery|system"


@pytest.mark.asyncio
async def test_mcp_auth_binds_workspace_task_and_actor_scope() -> None:
    application = ServiceAuthMiddleware(scoped_application, "service-secret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://mcp.test") as client:
        response = await client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer service-secret",
                "X-BrandFlow-Workspace": "workspace-1",
                "X-BrandFlow-Task": "task-1",
                "X-BrandFlow-Actor": "actor-1",
            },
        )
    assert response.status_code == 200
    assert response.text == "workspace-1|task-1|actor-1"


def test_trusted_scope_rejects_cross_task_and_cross_actor_arguments() -> None:
    scope = TrustedCallScope(workspace_id="workspace-1", task_id="task-1", actor_id="actor-1")
    with pytest.raises(PermissionError):
        scope.authorize("workspace-1", "actor-1", "task-2")
    with pytest.raises(PermissionError):
        scope.authorize("workspace-1", "actor-2", "task-1")


# ---------------------------------------------------------------------------
# Fail closed on a missing Authorization header (security review P0)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_authorization_header_is_rejected_by_default() -> None:
    """No header must be a 401 — the old "dev mode" pass-through trusted anyone."""
    application = ServiceAuthMiddleware(scoped_application, "service-secret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://mcp.test") as client:
        response = await client.post("/mcp")
    assert response.status_code == 401
    assert "trusted service authentication" in response.text


async def echo_application(scope, receive, send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


@pytest.mark.asyncio
async def test_anonymous_discovery_requires_explicit_opt_in() -> None:
    """The dev escape hatch still works, but only when asked for explicitly."""
    gated = ServiceAuthMiddleware(echo_application, "service-secret")
    opt_in = ServiceAuthMiddleware(echo_application, "service-secret", allow_anonymous_discovery=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gated), base_url="http://mcp.test") as client:
        default_response = await client.post("/mcp")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=opt_in), base_url="http://mcp.test") as client:
        opted_in_response = await client.post("/mcp")

    assert default_response.status_code == 401
    assert opted_in_response.status_code == 200


@pytest.mark.asyncio
async def test_anonymous_discovery_still_cannot_execute_tools() -> None:
    """Defence in depth: discovery may pass, but no scope is bound for tools."""
    opt_in = ServiceAuthMiddleware(scoped_application, "service-secret", allow_anonymous_discovery=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=opt_in), base_url="http://mcp.test") as client:
        with pytest.raises(PermissionError):
            await client.post("/mcp")


@pytest.mark.asyncio
async def test_non_mcp_paths_are_never_gated_by_service_token() -> None:
    """Health checks must keep working without the service token."""
    application = ServiceAuthMiddleware(echo_application, "service-secret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://mcp.test") as client:
        # /health is not under /mcp, so the middleware forwards it untouched
        response = await client.post("/health")
    assert response.status_code == 200


def test_deployed_app_installs_the_service_auth_middleware(monkeypatch) -> None:
    """The production ASGI app must carry ServiceAuthMiddleware (review P1)."""

    import sys

    monkeypatch.setenv("BRAND_MCP_DATABASE_URL", "postgresql://brand_tools@localhost:5432/brandflow")
    monkeypatch.setenv("BRAND_MCP_SERVICE_TOKEN", "service-secret")

    saved = {name: module for name, module in sys.modules.items() if name.startswith("brand_tools_mcp")}
    try:
        for module in list(saved):
            del sys.modules[module]

        import brand_tools_mcp.server as server_module

        assert isinstance(server_module.app, server_module.ServiceAuthMiddleware), (
            "server.app must wrap the MCP transport with ServiceAuthMiddleware; "
            "otherwise no TrustedCallScope is ever bound in production"
        )
    finally:
        # restore the original module identities so later tests keep class identity
        sys.modules.update(saved)


# ---------------------------------------------------------------------------
# High-risk publishing stays fail closed (upgrade plan task 11)
# ---------------------------------------------------------------------------

from brand_tools_mcp.tools import create_mcp  # noqa: E402


class RecordingRepository:
    """Minimal repository that records high-risk calls and their arguments."""

    def __init__(self) -> None:
        self.authorized_calls: list[dict] = []

    async def authorized_package(self, **payload) -> tuple[dict, bool]:
        self.authorized_calls.append(payload)
        return {"package_id": "pkg-1"}, False

    async def open(self) -> None: ...  # noqa: E704

    async def close(self) -> None: ...  # noqa: E704


@pytest.mark.asyncio
async def test_export_rejects_without_persisted_authorization() -> None:
    from brand_tools_mcp.repository import ToolRejected

    calls: list[dict] = []

    class RejectingRepository:
        async def authorized_package(self, **payload) -> tuple[dict, bool]:
            calls.append(payload)
            raise ToolRejected("no persisted authorization for this action")

    mcp = create_mcp(RejectingRepository(), require_trusted_scope=False)  # type: ignore[arg-type]
    envelope = await mcp.call_tool(
        "export_content_package",
        {
            "workspace_id": "ws",
            "task_id": "task",
            "actor_id": "actor",
            "decision_id": "missing",
            "target_snapshot_hash": "x" * 64,
            "idempotency_key": "key-1",
            "formats": ["md"],
        },
    )
    # FastMCP structured_output returns (unstructured, structured) tuples
    result = envelope[1] if isinstance(envelope, tuple) and len(envelope) == 2 else envelope
    if isinstance(result, list):
        result = result[0]
    payload = getattr(result, "structured_content", None) or result
    assert payload["error"]["code"] == "MCP_APPROVAL_INVALID"
    assert calls, "the tool must reach the authorization check"


@pytest.mark.asyncio
async def test_preview_never_publishes_and_no_publish_tool_exists() -> None:
    mcp = create_mcp(RecordingRepository(), require_trusted_scope=False)  # type: ignore[arg-type]
    envelope = await mcp.call_tool(
        "create_publish_preview",
        {
            "workspace_id": "ws",
            "task_id": "task",
            "actor_id": "actor",
            "decision_id": "d-1",
            "target_snapshot_hash": "x" * 64,
            "idempotency_key": "key-2",
        },
    )
    result = envelope[1] if isinstance(envelope, tuple) and len(envelope) == 2 else envelope
    if isinstance(result, list):
        result = result[0]
    payload = getattr(result, "structured_content", None) or result
    assert payload["data"]["published"] is False
    # and a publish-shaped action is NOT among the exposed tools
    tools = await mcp.list_tools()
    tool_names = {tool.name for tool in tools}
    assert "publish_content" not in tool_names
    assert "export_content_package" in tool_names  # the authorized high-risk path
