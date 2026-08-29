from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .config import Settings
from .repository import BrandToolsRepository
from .security import ServiceAuthMiddleware
from .tools import create_mcp


settings = Settings()
repository = BrandToolsRepository(settings.require_database_url())
mcp = create_mcp(repository)
mcp_app = mcp.streamable_http_app()


async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "alive", "service": "brandflow-brand-tools-mcp"})


# Health at /health
mcp_app.routes.insert(0, Route("/health", health, methods=["GET"]))


# The service auth middleware is REQUIRED in every environment (security
# review P1): without it no TrustedCallScope is ever bound and every tool
# call dies at require_scope(), while the transport itself would be
# unauthenticated. Token-only requests fall back to the default system
# scope; the agent API always sends the scoped headers.
app = ServiceAuthMiddleware(mcp_app, settings.require_service_token())


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
