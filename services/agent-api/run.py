"""Entry point for Windows: set event loop policy before uvicorn starts."""
import asyncio
import selectors
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # patch asyncio.get_running_loop to force SelectorEventLoop
    original_new = asyncio.SelectorEventLoop.__new__
    def _patched_new(cls):
        loop = original_new(cls)
        if sys.platform == "win32":
            loop._selector = selectors.SelectSelector()
        return loop
    asyncio.SelectorEventLoop.__new__ = _patched_new


async def main():
    import uvicorn
    config = uvicorn.Config(
        "agent_api.api.server:create_server_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
