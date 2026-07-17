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
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
