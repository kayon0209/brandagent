import asyncio
import selectors
import sys

from agent_api.api.bootstrap import create_production_app
from agent_api.runtime import configure_event_loop


def create_server_app():
    configure_event_loop()
    return create_production_app()


def main() -> None:
    configure_event_loop()
    import uvicorn

    config = uvicorn.Config(
        "agent_api.api.server:create_server_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
    )
    application_server = uvicorn.Server(config)
    if sys.platform == "win32":
        with asyncio.Runner(
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        ) as runner:
            runner.run(application_server.serve())
    else:
        asyncio.run(application_server.serve())


if __name__ == "__main__":
    main()
