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

    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
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
        except httpx.TimeoutException as error:
            raise ProviderExecutionError("MODEL_TIMEOUT", "The model provider timed out.", retryable=True) from error
        except httpx.TransportError as error:
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
