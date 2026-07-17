from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRAND_MCP_", env_file=None, extra="ignore")

    database_url: SecretStr | None = None
    service_token: SecretStr | None = None
    host: str = "127.0.0.1"
    port: int = 8100

    def require_database_url(self) -> str:
        if self.database_url is None:
            raise RuntimeError("BRAND_MCP_DATABASE_URL is required")
        return self.database_url.get_secret_value()

    def require_service_token(self) -> str:
        if self.service_token is None or not self.service_token.get_secret_value():
            raise RuntimeError("BRAND_MCP_SERVICE_TOKEN is required")
        return self.service_token.get_secret_value()
