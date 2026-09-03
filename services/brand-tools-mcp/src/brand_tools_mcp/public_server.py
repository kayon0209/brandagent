"""Public READ-ONLY brand-tools MCP instance (agentization P2-1).

Exposes exactly four read tools - search_brand_documents, get_product_facts,
get_brand_guidelines, get_channel_spec - so external MCP clients (Claude
Desktop, Cursor, IDE agents) can consult a workspace's brand knowledge.

Security posture (distinct from the internal server by DESIGN, not by
authorization):

- write tools (save_content_version) and high-risk gated tools
  (export_content_package, create_publish_preview) are NOT REGISTERED in
  this process at all - they cannot be reached by any auth failure
- the validator tools are omitted too: they belong to the internal
  pipeline, not to external browsing
- access is granted by per-workspace bearer tokens (BRAND_MCP_PUBLIC_TOKENS
  file: one '<token> <workspace_id>' pair per line). Each token is pinned
  to ONE workspace; a token can never read across workspaces
- the RLS store scoping (app.workspace_id) still applies underneath, so
  defense is layered: token->workspace mapping, then PostgreSQL RLS

The token format is deliberately simple so it can be swapped for an
OAuth resource-server later without touching the tool surface.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from mcp.server.fastmcp import FastMCP

from .config import Settings
from .repository import BrandToolsRepository
from .security import ServiceAuthMiddleware

READ_TOOLS = (
    "search_brand_documents",
    "get_product_facts",
    "get_brand_guidelines",
    "get_channel_spec",
)


def load_public_tokens(path: str) -> dict[str, str]:
    """Parse '<token> <workspace_id>' lines into an access table.

    Blank lines and #-comments are ignored; malformed lines raise so a
    misconfigured deploy fails loudly at boot instead of silently granting
    nothing (or worse, everything).
    """
    tokens: dict[str, str] = {}
    with open(path, encoding="utf8") as handle:
        for number, raw in enumerate(handle.read().splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"public token file line {number}: expected '<token> <workspace_id>', got {raw!r}")
            token, workspace_id = parts
            if token in tokens:
                raise ValueError(f"public token file line {number}: duplicate token")
            tokens[token] = workspace_id
    if not tokens:
        raise ValueError(f"public token file {path} contains no tokens")
    return tokens


def create_public_mcp(repository: BrandToolsRepository, *, host: str = "0.0.0.0", port: int = 8200) -> FastMCP:
    from .tools import envelope

    mcp = FastMCP(
        "brandagent-public-brand-tools",
        instructions=(
            "Read-only brand knowledge access for BrandAgent workspaces. "
            "This server has no write or publish capability by design."
        ),
        host=host,
        port=port,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
    )

    @mcp.tool(description="Search active brand documents in one workspace.", structured_output=True)
    async def search_brand_documents(workspace_id: str, query: str, limit: int = 10) -> dict[str, object]:
        return envelope(
            "search_brand_documents",
            {"items": await repository.search_documents(workspace_id, query, min(max(limit, 1), 50))},
        )

    @mcp.tool(description="Get current authoritative product facts.", structured_output=True)
    async def get_product_facts(workspace_id: str, product_id: str) -> dict[str, object]:
        facts = await repository.product_facts(workspace_id, product_id)
        return envelope("get_product_facts", {"items": facts, "authoritative": bool(facts)})

    @mcp.tool(description="Get the active brand guideline version.", structured_output=True)
    async def get_brand_guidelines(workspace_id: str, brand_id: str) -> dict[str, object]:
        guideline = await repository.brand_guidelines(workspace_id, brand_id)
        return envelope("get_brand_guidelines", guideline or {}, degraded=guideline is None)

    @mcp.tool(description="Get the active specification for a supported channel.", structured_output=True)
    async def get_channel_spec(workspace_id: str, channel: str) -> dict[str, object]:
        if channel not in await repository.supported_channels(workspace_id):
            from .repository import ToolRejected

            raise ToolRejected("Unsupported channel")
        specification = await repository.channel_spec(workspace_id, channel)
        return envelope("get_channel_spec", specification or {}, degraded=specification is None)

    return mcp


class PublicAuthMiddleware:
    """Bearer gate for the public instance, two credential modes (P2-1 -> OAuth):

    1. STATIC TOKENS - the BRAND_MCP_PUBLIC_TOKENS table maps a literal
       token to ONE pinned workspace. Simple, revocable by file edit.
    2. CLERK JWT (OAuth-style) - when BRAND_MCP_PUBLIC_CLERK_JWKS_URL is
       configured and the bearer is a JWT (three dot-separated parts),
       it is verified against the Clerk JWKS (RS256, issuer, exp/iat),
       and the workspace is DERIVED with the exact same uuid5 rule as
       agent-api (brandagent:personal:{sub}) - so a creator logged into
       BrandAgent can paste the SAME session token into Claude Desktop.
       Custom-token templates may additionally pin org workspaces via
       org_id claims; personal derivation is the default.

    Static tokens keep working in parallel (both tables are consulted);
    a JWT-shaped static token is rejected to avoid ambiguity.
    """

    def __init__(self, application, tokens: dict[str, str], *, jwt_verifier=None) -> None:
        import hmac

        self._application = application
        self._tokens = tokens
        self._jwt_verifier = jwt_verifier  # ClerkJWTVerifier-like: async verify(token) -> Principal
        self._hmac = hmac

    async def _resolve_workspace(self, token: str) -> str | None:
        """Return the ONE workspace this credential may touch, or None."""
        if token.count(".") == 2 and self._jwt_verifier is not None:
            try:
                # PublicClerkVerifier.verify returns the derived personal
                # workspace_id directly (org tokens raise inside)
                workspace = await self._jwt_verifier.verify(token)
            except Exception:  # noqa: BLE001 — any verify failure is a 401
                return None
            return str(workspace)
        # static table (hmac-constant-time on the lookup key for parity
        # with the internal middleware's compare discipline)
        for known, workspace in self._tokens.items():
            if self._hmac.compare_digest(known, token):
                return workspace
        return None

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or not str(scope.get("path", "")).startswith("/mcp"):
            await self._application(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied = headers.get(b"authorization", b"").decode()
        expected_prefix = "Bearer "
        if not supplied.startswith(expected_prefix):
            from starlette.responses import JSONResponse

            response = JSONResponse({"error": "bearer token required"}, status_code=401)
            await response(scope, receive, send)
            return
        token = supplied[len(expected_prefix) :]
        bound_workspace = await self._resolve_workspace(token)
        if bound_workspace is None:
            from starlette.responses import JSONResponse

            response = JSONResponse({"error": "unknown or revoked credential"}, status_code=401)
            await response(scope, receive, send)
            return
        # the credential's workspace is the ONLY reachable workspace; tool
        # calls passing any other id are rejected before the repository
        scope["state"] = {**(scope.get("state") or {}), "public_workspace_id": bound_workspace}
        await self._application(scope, receive, send)


def create_public_app() -> object:
    """ASGI app factory: repository + read-only tools + credential gate."""
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    settings = Settings()
    tokens: dict[str, str] = {}
    if settings.public_tokens_path:
        tokens = load_public_tokens(settings.public_tokens_path)

    jwt_verifier = None
    clerk_jwks = settings.public_clerk_jwks_url
    if clerk_jwks:
        if not (clerk_jwks.startswith("https://") and settings.public_clerk_issuer):
            raise RuntimeError("public Clerk mode requires BRAND_MCP_PUBLIC_CLERK_JWKS_URL (https) and BRAND_MCP_PUBLIC_CLERK_ISSUER")
        from .public_clerk import PublicClerkVerifier

        jwt_verifier = PublicClerkVerifier(
            jwks_url=clerk_jwks,
            issuer=settings.public_clerk_issuer,
            audience=settings.public_clerk_audience or None,
            authorized_parties=[p.strip() for p in (settings.public_clerk_authorized_parties or "").split(",") if p.strip()] or None,
        )

    if not tokens and jwt_verifier is None:
        raise RuntimeError(
            "the public instance needs at least one credential source: "
            "BRAND_MCP_PUBLIC_TOKENS (static table) or BRAND_MCP_PUBLIC_CLERK_JWKS_URL (OAuth-style)"
        )

    repository = BrandToolsRepository(settings.require_database_url())
    mcp = create_public_mcp(repository, host=settings.host, port=settings.public_port)
    app = mcp.streamable_http_app()

    async def health(_request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "alive",
                "service": "brandagent-public-brand-tools-mcp",
                "tools": list(READ_TOOLS),
                "auth": {"static_tokens": bool(tokens), "clerk_jwt": jwt_verifier is not None},
            }
        )

    app.routes.insert(0, Route("/health", health, methods=["GET"]))
    return PublicAuthMiddleware(app, tokens, jwt_verifier=jwt_verifier)


if __name__ == "__main__":
    from pathlib import Path

    import uvicorn

    settings = Settings()
    uvicorn.run(
        f"{create_public_app.__module__}:create_public_app",
        host=settings.public_host,
        port=settings.public_port,
        factory=True,
    )
