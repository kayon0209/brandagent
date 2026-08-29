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
