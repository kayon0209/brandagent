from pydantic import SecretStr
import pytest

from agent_api.api.bootstrap import create_production_app
from agent_api.config import Settings


def test_default_model_is_glm_47_and_provider_is_unverified() -> None:
    settings = Settings()
    assert settings.glm_model == "glm-4.7"
    assert settings.provider_verified is False


def test_secret_values_are_not_exposed_in_repr() -> None:
    settings = Settings(glm_api_key=SecretStr("not-a-real-key"))
    assert "not-a-real-key" not in repr(settings)


def test_production_composition_fails_closed_without_required_settings() -> None:
    settings = Settings(
        agent_database_url=None,
        agent_checkpoint_database_url=None,
        glm_api_key=None,
        clerk_jwks_url=None,
        clerk_issuer=None,
        clerk_audience=None,
    )
    with pytest.raises(RuntimeError, match="AGENT_DATABASE_URL"):
        create_production_app(settings)


def test_production_composition_rejects_shared_business_checkpoint_connection() -> None:
    shared = SecretStr("postgresql://role@localhost/database")
    settings = Settings(
        agent_database_url=shared,
        agent_checkpoint_database_url=shared,
        glm_api_key=SecretStr("not-a-real-key"),
        clerk_jwks_url="https://example.invalid/jwks",
        clerk_issuer="https://example.invalid",
        clerk_audience="brandflow",
    )
    with pytest.raises(RuntimeError, match="distinct database roles"):
        create_production_app(settings)


def test_production_composition_rejects_same_database_role_with_different_options() -> None:
    settings = Settings(
        agent_database_url=SecretStr("postgresql://shared@localhost/database"),
        agent_checkpoint_database_url=SecretStr("postgresql://shared@localhost/database?options=-csearch_path%3Dcheckpoint"),
        glm_api_key=SecretStr("not-a-real-key"),
        clerk_jwks_url="https://example.invalid/jwks",
        clerk_issuer="https://example.invalid",
        clerk_audience="brandflow",
    )
    with pytest.raises(RuntimeError, match="distinct database roles"):
        create_production_app(settings)


def test_production_composition_wires_the_full_consumer_stack() -> None:
    """The real entrypoint must construct without UnboundLocalError (design
    review P0): provider is created before every consumer service uses it."""

    settings = Settings(
        environment="development",
        auth_mode="dev",
        agent_database_url=SecretStr("postgresql://business@localhost:5432/app"),
        agent_checkpoint_database_url=SecretStr("postgresql://checkpoint@localhost:5433/checkpoint"),
        glm_api_key=SecretStr("not-a-real-key"),
        brand_mcp_url="https://example.invalid/mcp",
        brand_mcp_service_token=SecretStr("not-a-real-token"),
        clerk_jwks_url="https://example.invalid/jwks",
        clerk_issuer="https://example.invalid",
        clerk_audience="brandflow",
    )
    app = create_production_app(settings)
    # the consumer routers are mounted with the full bundle wired
    openapi = app.openapi()
    paths = set(openapi["paths"].keys())
    assert "/api/v1/consumer/projects" in paths
    assert "/api/v1/consumer/usage" in paths
    assert "/api/v1/consumer/materials" in paths
