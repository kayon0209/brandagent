import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pydantic import SecretStr

from agent_api.providers.zhipu import ZhipuProvider


pytestmark = pytest.mark.skipif(os.getenv("RUN_ZHIPU_INTEGRATION") != "true", reason="requires explicit real-provider verification")


@pytest.mark.asyncio
async def test_glm_47_real_provider_returns_usage_without_exposing_content() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    load_dotenv(repository_root / ".env.local", override=False)
    api_key = os.getenv("GLM_API_KEY")
    assert api_key, "GLM_API_KEY must be configured locally"
    provider = ZhipuProvider(api_key=SecretStr(api_key), model=os.getenv("GLM_MODEL", "glm-4.7"))
    result = await provider.generate(
        system="Return one short JSON object. Do not include reasoning.",
        prompt='Return exactly: {"status":"ok"}',
        prompt_version="provider-verification-v1",
    )
    assert result.provider == "zhipu"
    assert result.model == "glm-4.7"
    assert len(result.content) > 0
    print({
        "provider": result.provider,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "response_length": len(result.content),
    })
