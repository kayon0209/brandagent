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


# Local dev: no auth on MCP endpoints
app = mcp_app


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
