import asyncio
import ssl

import pytest
from pydantic import SecretStr

from agent_api.providers import zhipu
from agent_api.providers.base import ProviderExecutionError
from agent_api.providers.zhipu import ZhipuProvider


class _TlsFailureClient:
    is_closed = False

    def __init__(self) -> None:
        self.closed = False
        self.calls = 0

    async def post(self, *args, **kwargs):
        self.calls += 1
        raise ssl.SSLError("record layer failure")

    async def aclose(self) -> None:
        self.closed = True
        self.is_closed = True


class _SuccessfulClient:
    is_closed = False

    async def post(self, *args, **kwargs):
        return _Response()

    async def aclose(self) -> None:
        self.is_closed = True


class _Response:
    status_code = 200

    @staticmethod
    def json() -> dict:
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        }


class _MalformedSuccessResponse:
    status_code = 200

    @staticmethod
    def json() -> dict:
        return {"choices": []}


class _MalformedSuccessClient:
    is_closed = False

    async def post(self, *args, **kwargs):
        return _MalformedSuccessResponse()

    async def aclose(self) -> None:
        self.is_closed = True


@pytest.mark.asyncio
async def test_does_not_retry_an_ambiguous_tls_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _TlsFailureClient()
    monkeypatch.setattr(zhipu.httpx, "AsyncClient", lambda **kwargs: client)

    provider = ZhipuProvider(api_key=SecretStr("test-key"), timeout_seconds=1)

    with pytest.raises(ProviderExecutionError, match="execution outcome is unknown") as caught:
        await provider.generate(system="system", prompt="prompt", prompt_version="test")

    assert caught.value.code == "MODEL_EXECUTION_UNKNOWN"
    assert client.calls == 1, "a response-loss failure may already have reached the provider"
    assert client.closed is False, "one request must not close a shared client used by another request"


@pytest.mark.asyncio
async def test_malformed_200_response_is_a_confirmed_execution_not_a_refundable_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(zhipu.httpx, "AsyncClient", lambda **kwargs: _MalformedSuccessClient())
    provider = ZhipuProvider(api_key=SecretStr("test-key"), timeout_seconds=1)

    with pytest.raises(ProviderExecutionError) as caught:
        await provider.generate(system="system", prompt="prompt", prompt_version="test")

    assert caught.value.code == "MODEL_INVALID_RESPONSE"
    assert caught.value.execution_confirmed is True


@pytest.mark.asyncio
async def test_aclose_releases_the_client_and_later_request_recreates_it(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _SuccessfulClient()
    second = _SuccessfulClient()
    clients = iter([first, second])
    monkeypatch.setattr(zhipu.httpx, "AsyncClient", lambda **kwargs: next(clients))

    provider = ZhipuProvider(api_key=SecretStr("test-key"), timeout_seconds=1)

    await provider.generate(system="system", prompt="first", prompt_version="test")
    await provider.aclose()

    assert first.is_closed is True
    assert provider._client is None

    result = await provider.generate(system="system", prompt="second", prompt_version="test")

    assert result.content == "ok"


class _ConcurrentClient:
    is_closed = False

    def __init__(self) -> None:
        self.closed = False
        self.calls = 0
        self.first_started = asyncio.Event()
        self.second_started = asyncio.Event()
        self.release_second = asyncio.Event()

    async def post(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            self.first_started.set()
            await self.second_started.wait()
            raise ssl.SSLError("response lost after request write")
        self.second_started.set()
        await self.release_second.wait()
        if self.closed:
            raise RuntimeError("another request closed the shared client")
        return _Response()

    async def aclose(self) -> None:
        self.closed = True
        self.is_closed = True


@pytest.mark.asyncio
async def test_one_ambiguous_failure_does_not_close_a_client_used_by_another_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _ConcurrentClient()
    monkeypatch.setattr(zhipu.httpx, "AsyncClient", lambda **kwargs: client)
    provider = ZhipuProvider(api_key=SecretStr("test-key"), timeout_seconds=1)

    failed = asyncio.create_task(provider.generate(system="system", prompt="first", prompt_version="test"))
    await client.first_started.wait()
    succeeded = asyncio.create_task(provider.generate(system="system", prompt="second", prompt_version="test"))
    await client.second_started.wait()
    await asyncio.sleep(0)
    client.release_second.set()

    results = await asyncio.gather(failed, succeeded, return_exceptions=True)

    assert isinstance(results[0], ProviderExecutionError)
    assert results[0].code == "MODEL_EXECUTION_UNKNOWN"
    assert results[1].content == "ok"
    assert client.closed is False
