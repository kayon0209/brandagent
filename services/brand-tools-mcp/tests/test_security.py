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
