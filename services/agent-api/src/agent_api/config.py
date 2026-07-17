from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    environment: str = "development"
    glm_api_key: SecretStr | None = None
    glm_model: str = "glm-4.7"
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
