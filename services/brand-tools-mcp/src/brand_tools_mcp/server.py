import sys

# Windows + psycopg async: the whole project forces SelectorEventLoop for
# its SSL/DB stacks (agent-api run.py / server.py / research runner.py do
# the same). Without this, ProactorEventLoop makes the psycopg pool fail
# on every connection ("Psycopg cannot use the ProactorEventLoop"), which
# only surfaces when the server runs on a Windows HOST (Docker is fine).
# Module import happens before uvicorn creates its event loop, so setting
# the policy here is effective.
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402

from .config import Settings  # noqa: E402
from .repository import BrandToolsRepository  # noqa: E402
from .security import ServiceAuthMiddleware  # noqa: E402
from .tools import create_mcp  # noqa: E402


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
