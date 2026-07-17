from agent_api.api import server


def test_local_server_configures_event_loop_before_uvicorn(monkeypatch) -> None:
    calls = []

    class FakeServer:
        def __init__(self, config):
            calls.append(("server", config))

        async def serve(self):
            return None

    class FakeRunner:
        def __init__(self, **kwargs):
            calls.append(("runner", kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def run(self, coroutine):
            coroutine.close()
            calls.append("runner_run")

    monkeypatch.setattr(server, "configure_event_loop", lambda: calls.append("event_loop"))
    monkeypatch.setattr("uvicorn.Config", lambda *args, **kwargs: (args, kwargs))
    monkeypatch.setattr("uvicorn.Server", FakeServer)
    monkeypatch.setattr(server.asyncio, "Runner", FakeRunner)
    monkeypatch.setattr(server.asyncio, "run", lambda coroutine, **kwargs: (coroutine.close(), calls.append(("run", kwargs))))
    monkeypatch.setattr(server.sys, "platform", "win32")

    server.main()

    assert calls[0] == "event_loop"
    assert calls[1][0] == "server"
    assert calls[1][1][0] == ("agent_api.api.server:create_server_app",)
    assert calls[1][1][1]["factory"] is True
    assert calls[2][0] == "runner"
    assert callable(calls[2][1]["loop_factory"])
    assert calls[3] == "runner_run"
