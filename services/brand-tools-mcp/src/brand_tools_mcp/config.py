from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRAND_MCP_", env_file=None, extra="ignore")

    database_url: SecretStr | None = None
    service_token: SecretStr | None = None
    host: str = "127.0.0.1"
    port: int = 8100
    # Dev-only escape hatch: allow /mcp requests WITHOUT an Authorization header
    # to reach the transport (MCP SDK session init / tool discovery).  Default is
    # False so a missing header is rejected with 401 instead of being trusted.
    # Tool calls still need a bound TrustedCallScope, so this only ever opens
    # discovery — never tool execution.
    allow_anonymous_discovery: bool = False
    # public read-only instance (agentization P2-1): token file + listener
    public_tokens_path: str | None = None
    public_port: int = 8200
    public_host: str = "127.0.0.1"
    # OAuth-style credential (P2-1 enhancement): verify Clerk JWTs against
    # the same JWKS the agent-api uses; workspace derives from the sub claim
    public_clerk_jwks_url: str | None = None
    public_clerk_issuer: str | None = None
    public_clerk_audience: str | None = None
    public_clerk_authorized_parties: str | None = None

    def require_database_url(self) -> str:
        if self.database_url is None:
            raise RuntimeError("BRAND_MCP_DATABASE_URL is required")
        return self.database_url.get_secret_value()

    def require_service_token(self) -> str:
        if self.service_token is None or not self.service_token.get_secret_value():
            raise RuntimeError("BRAND_MCP_SERVICE_TOKEN is required")
        return self.service_token.get_secret_value()
