from __future__ import annotations

import time

import httpx
from pydantic import SecretStr

from .base import LLMProvider, ModelCallResult, ProviderExecutionError


class ZhipuProvider(LLMProvider):
    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str = "glm-4.7",
        base_url: str = "https://open.bigmodel.cn/api/paas/v4",
        timeout_seconds: float = 60,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        started = time.perf_counter()
        # connection reuse: a FRESH AsyncClient per call re-handshakes TLS
        # every time; on this gateway the second handshake in quick
        # succession (plan call -> search -> synthesize call) reliably
        # dies with [SSL] record layer failure in ~5s. Holding ONE client
        # (like the passing reproduction script) keeps the warm
        # connection and eliminates the failure mode.
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout_seconds)
        # transient transport failures (proxy intermittently kills TLS
        # streams on this host, ~5s in, reproduced): back off and retry —
        # the run must not die to a single network hiccup
        for attempt in range(3):
            try:
                response = await self._client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.2,
                    },
                )
                break
            except httpx.TimeoutException as error:
                raise ProviderExecutionError("MODEL_TIMEOUT", "The model provider timed out.", retryable=True) from error
            except httpx.TransportError as error:
                if attempt < 2:
                    # a killed stream poisons the pooled connection: drop it
                    await self._client.aclose()
                    self._client = httpx.AsyncClient(timeout=self._timeout_seconds)
                    import asyncio as _aio

                    await _aio.sleep(0.5 * (2 ** attempt))
                    continue
                raise ProviderExecutionError("MODEL_UNAVAILABLE", "The model provider is unavailable.", retryable=True) from error
        if response.status_code == 429:
            raise ProviderExecutionError("MODEL_RATE_LIMITED", "The model provider rate limit was reached.", retryable=True)
        if response.status_code >= 500:
            raise ProviderExecutionError("MODEL_UNAVAILABLE", "The model provider is unavailable.", retryable=True)
        if response.status_code >= 400:
            raise ProviderExecutionError("MODEL_REQUEST_REJECTED", "The model provider rejected the request.", retryable=False)
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ProviderExecutionError("MODEL_INVALID_RESPONSE", "The model provider returned an invalid response.", retryable=False) from error
        usage = payload.get("usage") or {}
        return ModelCallResult(
            content=content,
            provider="zhipu",
            model=self._model,
            prompt_version=prompt_version,
            latency_ms=round((time.perf_counter() - started) * 1000),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            usage_source="provider" if usage else "unavailable",
            retry_count=0,
        )
