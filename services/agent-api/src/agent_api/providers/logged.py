from __future__ import annotations

import time
from typing import Protocol

from .base import LLMProvider, ModelCallResult, ProviderExecutionError


class ModelCallRecorder(Protocol):
    async def record(self, payload: dict[str, object]) -> None: ...


class LoggedLLMProvider(LLMProvider):
    def __init__(self, provider: LLMProvider, recorder: ModelCallRecorder, *, workspace_id: str, task_id: str) -> None:
        self._provider = provider
        self._recorder = recorder
        self._workspace_id = workspace_id
        self._task_id = task_id

    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        started = time.perf_counter()
        lease_guard = getattr(self._recorder, "assert_active_lease", None)
        if lease_guard is not None:
            await lease_guard()
        try:
            result = await self._provider.generate(system=system, prompt=prompt, prompt_version=prompt_version)
        except ProviderExecutionError as error:
            try:
                await self._recorder.record({
                    "workspace_id": self._workspace_id, "task_id": self._task_id,
                    "provider": self._provider.__class__.__name__, "model": "unavailable",
                    "prompt_version": prompt_version, "latency_ms": round((time.perf_counter() - started) * 1000),
                    "input_tokens": None, "output_tokens": None, "usage_source": "unavailable",
                    "retry_count": 0, "status": "failed", "error_code": error.code,
                })
            except Exception:
                pass
            raise
        except Exception as error:
            try:
                await self._recorder.record({
                    "workspace_id": self._workspace_id, "task_id": self._task_id,
                    "provider": self._provider.__class__.__name__, "model": "unavailable",
                    "prompt_version": prompt_version, "latency_ms": round((time.perf_counter() - started) * 1000),
                    "input_tokens": None, "output_tokens": None, "usage_source": "unavailable",
                    "retry_count": 0, "status": "failed", "error_code": type(error).__name__,
                })
            except Exception:
                pass
            raise ProviderExecutionError("MODEL_CALL_FAILED", "The selected model provider failed.", retryable=False) from error
        if lease_guard is not None:
            await lease_guard()
        payload = {
            "workspace_id": self._workspace_id,
            "task_id": self._task_id,
            "provider": result.provider,
            "model": result.model,
            "prompt_version": result.prompt_version,
            "latency_ms": result.latency_ms,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "usage_source": result.usage_source,
            "retry_count": result.retry_count,
            "status": "succeeded",
            "error_code": None,
        }
        try:
            await self._recorder.record(payload)
        except Exception as error:
            raise ProviderExecutionError(
                "MODEL_AUDIT_FAILED_AFTER_SUCCESS",
                "The model completed, but its audit record could not be persisted. Automatic retry is disabled.",
                retryable=False,
            ) from error
        return result
