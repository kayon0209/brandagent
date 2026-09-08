from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelCallResult:
    content: str
    provider: str
    model: str
    prompt_version: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    usage_source: str
    retry_count: int


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        raise NotImplementedError


class ProviderExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool, execution_confirmed: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        # True only when the provider has already returned a success response
        # (or otherwise proved it ran the request). This is distinct from a
        # transport response-loss state, where execution remains unknown.
        self.execution_confirmed = execution_confirmed
