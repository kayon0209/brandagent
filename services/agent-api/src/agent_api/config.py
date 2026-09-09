from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    environment: str = "development"
    auth_mode: str | None = None
    glm_api_key: SecretStr | None = None
    glm_model: str = "glm-4.7"
    # OpenAI-compatible base URL of the model gateway. Defaults to Zhipu BigModel;
    # Gitee AI (https://ai.gitee.com/v1) and other compatible gateways only need
    # this env override — no code change.
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    agent_database_url: SecretStr | None = None
    agent_checkpoint_database_url: SecretStr | None = None
    brand_mcp_url: str | None = None
    brand_mcp_service_token: SecretStr | None = None
    brand_mcp_timeout_seconds: float = 15
    clerk_jwks_url: str | None = None
    clerk_issuer: str | None = None
    clerk_audience: str | None = None
    clerk_authorized_parties: str | None = None
    provider_verified: bool = False
    # Phase 6 deep research (user-approved 2026-09-08): the single outbound
    # search channel. Missing key disables the feature at startup with an
    # honest error instead of a crash mid-run.
    tavily_api_key: SecretStr | None = None
    deep_research_parallelism: int = 4
    # Reservation estimate rides the measured S2 experiment usage
    # (summary_full_v1.json: ~6.5K input + ~6.6K output ≈ 13K tokens),
    # NOT the whole monthly quota — a run must be affordable inside the
    # user's remaining balance, not price itself out of existence.
    deep_research_estimated_tokens: int = 13000
    # Model-gateway read timeout. 60s covers draft/suggestion calls, but a
    # deep-research synthesis prompt (20 evidence cards ≈ 6K chars) was
    # measured at 15-50s with occasional 60s+ tails on the Gitee AI
    # gateway — a ReadTimeout there becomes MODEL_EXECUTION_UNKNOWN and
    # fails the whole run. Deep research is a "minutes, not seconds"
    # surface, so the whole app uses the raised ceiling.
    glm_timeout_seconds: float = 150

    def require_tavily_key(self) -> SecretStr:
        if self.tavily_api_key is None or not self.tavily_api_key.get_secret_value():
            raise RuntimeError("TAVILY_API_KEY is required for deep research execution")
        return self.tavily_api_key

    def require_glm_key(self) -> SecretStr:
        if self.glm_api_key is None:
            raise RuntimeError("GLM_API_KEY is required for real provider execution")
        return self.glm_api_key

    def require_database_url(self) -> str:
        if self.agent_database_url is None:
            raise RuntimeError("AGENT_DATABASE_URL is required for persistent workflow execution")
        return self.agent_database_url.get_secret_value()

    def require_checkpoint_database_url(self) -> str:
        if self.agent_checkpoint_database_url is None:
            raise RuntimeError("AGENT_CHECKPOINT_DATABASE_URL is required for isolated workflow checkpoints")
        return self.agent_checkpoint_database_url.get_secret_value()

    def require_mcp_url(self) -> str:
        if not self.brand_mcp_url:
            raise RuntimeError("BRAND_MCP_URL is required for real tool execution")
        return self.brand_mcp_url

    def require_mcp_service_token(self) -> SecretStr:
        if self.brand_mcp_service_token is None or not self.brand_mcp_service_token.get_secret_value():
            raise RuntimeError("BRAND_MCP_SERVICE_TOKEN is required for authenticated tool execution")
        return self.brand_mcp_service_token
