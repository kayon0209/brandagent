import pytest

from agent_api.providers.base import LLMProvider, ModelCallResult, ProviderExecutionError
from agent_api.providers.logged import LoggedLLMProvider


class Recorder:
    def __init__(self): self.rows = []
    async def record(self, payload): self.rows.append(payload)


class Failing(LLMProvider):
    async def generate(self, **kwargs): raise TimeoutError("secret provider detail")


class RetryableFailing(LLMProvider):
    async def generate(self, **kwargs):
        raise ProviderExecutionError("MODEL_TIMEOUT", "Provider timed out", retryable=True)


@pytest.mark.asyncio
async def test_provider_failure_is_logged_without_prompt_and_returns_stable_error() -> None:
    recorder = Recorder()
    provider = LoggedLLMProvider(Failing(), recorder, workspace_id="w", task_id="t")
    with pytest.raises(ProviderExecutionError) as caught:
        await provider.generate(system="hidden system", prompt="confidential brief", prompt_version="v1")
    assert caught.value.code == "MODEL_CALL_FAILED"
    assert caught.value.retryable is False
    assert "confidential brief" not in str(recorder.rows)
    assert recorder.rows[0]["error_code"] == "TimeoutError"


@pytest.mark.asyncio
async def test_provider_preserves_retryable_stable_error() -> None:
    recorder = Recorder()
    provider = LoggedLLMProvider(RetryableFailing(), recorder, workspace_id="w", task_id="t")
    with pytest.raises(ProviderExecutionError) as caught:
        await provider.generate(system="hidden", prompt="confidential", prompt_version="v1")
    assert caught.value.code == "MODEL_TIMEOUT"
    assert caught.value.retryable is True
    assert recorder.rows[0]["error_code"] == "MODEL_TIMEOUT"
