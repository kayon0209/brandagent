from __future__ import annotations

import asyncio
import ssl
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
        self._client_lock = asyncio.Lock()

    async def _client_for_request(self) -> httpx.AsyncClient:
        """Return the shared client without letting one request replace it.

        A transport failure can happen after the provider accepted a POST. A
        caller must neither retry that request nor close a client another
        in-flight request is using. httpx will discard an invalid pooled
        connection itself; only lifespan shutdown owns client disposal.
        """

        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(timeout=self._timeout_seconds)
            return self._client

    async def aclose(self) -> None:
        """Release the provider connection pool during application shutdown."""

        async with self._client_lock:
            client, self._client = self._client, None
        if client is not None and not client.is_closed:
            await client.aclose()

    async def generate(self, *, system: str, prompt: str, prompt_version: str, max_output_tokens: int | None = None) -> ModelCallResult:
        started = time.perf_counter()
        client = await self._client_for_request()
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        if max_output_tokens is not None:
            # Some OpenAI-compatible gateways cut connections at ~60s of
            # generation time (measured: Gitee AI, 2026-09-09). Capping the
            # completion keeps generation inside that window.
            body["max_tokens"] = max_output_tokens
        try:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
                json=body,
            )
        except (httpx.TimeoutException, httpx.TransportError, ssl.SSLError) as error:
            # We cannot prove whether the provider received this non-idempotent
            # POST. Retrying could generate and charge the same request twice.
            raise ProviderExecutionError(
                "MODEL_EXECUTION_UNKNOWN",
                "The model execution outcome is unknown because the provider response was lost.",
                retryable=False,
            ) from error
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
            # A 2xx response proves the provider accepted and executed the
            # non-idempotent call, even if its body cannot be parsed locally.
            raise ProviderExecutionError(
                "MODEL_INVALID_RESPONSE",
                "The model provider returned an invalid response.",
                retryable=False,
                execution_confirmed=True,
            ) from error
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
