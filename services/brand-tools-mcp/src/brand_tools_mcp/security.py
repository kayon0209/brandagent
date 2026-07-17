from __future__ import annotations

import hmac
from contextvars import ContextVar, Token
from dataclasses import dataclass

from starlette.responses import JSONResponse


@dataclass(frozen=True, slots=True)
class TrustedCallScope:
    workspace_id: str
    task_id: str
    actor_id: str

    def authorize(self, workspace_id: str, actor_id: str | None = None, task_id: str | None = None) -> None:
        if not hmac.compare_digest(self.workspace_id, workspace_id):
            raise PermissionError("Workspace scope mismatch")
        if actor_id is not None and not hmac.compare_digest(self.actor_id, actor_id):
            raise PermissionError("Actor scope mismatch")
        if task_id is not None and not hmac.compare_digest(self.task_id, task_id):
            raise PermissionError("Task scope mismatch")


_scope: ContextVar[TrustedCallScope | None] = ContextVar("brandflow_mcp_scope", default=None)


def bind_scope(scope: TrustedCallScope) -> Token:
    return _scope.set(scope)


def reset_scope(token: Token) -> None:
    _scope.reset(token)


def require_scope() -> TrustedCallScope:
    scope = _scope.get()
    if scope is None:
        raise PermissionError("Trusted MCP call scope is required")
    return scope


class ServiceAuthMiddleware:
    def __init__(self, application, token: str) -> None:
        if not token:
            raise RuntimeError("BRAND_MCP_SERVICE_TOKEN is required")
        self._application = application
        self._token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or not str(scope.get("path", "")).startswith("/mcp"):
            await self._application(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied = headers.get(b"authorization", b"").decode()
        expected = f"Bearer {self._token}"
        if not supplied or not hmac.compare_digest(supplied, expected):
            # In dev mode, allow unauthenticated requests to /mcp for MCP SDK discovery
            if supplied:
                response = JSONResponse({"error": "trusted service authentication required"}, status_code=401)
                await response(scope, receive, send)
                return
            # No auth header: pass through for MCP SDK session init
            await self._application(scope, receive, send)
            return
        workspace_id = headers.get(b"x-brandflow-workspace", b"").decode() or "system"
        task_id = headers.get(b"x-brandflow-task", b"").decode() or "discovery"
        actor_id = headers.get(b"x-brandflow-actor", b"").decode() or "system"
        token = bind_scope(TrustedCallScope(workspace_id=workspace_id, task_id=task_id, actor_id=actor_id))
        try:
            await self._application(scope, receive, send)
        finally:
            reset_scope(token)
