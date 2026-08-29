from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from uuid import NAMESPACE_URL, uuid5

from agent_api.api.security import ClerkJWTVerifier


class SigningKey:
    def __init__(self, key): self.key = key


class StaticJWKClient:
    def __init__(self, public_key): self.public_key = public_key
    def get_signing_key_from_jwt(self, token): return SigningKey(self.public_key)


def token(private_key, **overrides):
    now = datetime.now(UTC)
    claims = {
        "sub": "user-1", "org_id": "workspace-1", "org_role": "org:content_operator",
        "iss": "https://clerk.test", "aud": "brandflow", "azp": "http://localhost:3000",
        "iat": now, "exp": now + timedelta(minutes=5),
        **overrides,
    }
    return jwt.encode(claims, private_key, algorithm="RS256")


def session_token(private_key, **overrides):
    now = datetime.now(UTC)
    claims = {
        "sub": "user-1", "o": {"id": "org_workspace_1", "rol": "member"},
        "iss": "https://clerk.test", "azp": "http://localhost:3000",
        "iat": now, "exp": now + timedelta(minutes=5),
        **overrides,
    }
    return jwt.encode(claims, private_key, algorithm="RS256")


@pytest.mark.asyncio
async def test_clerk_verifier_checks_signature_issuer_audience_and_role() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = ClerkJWTVerifier(jwks_url="https://unused", issuer="https://clerk.test", audience="brandflow", jwk_client=StaticJWKClient(private_key.public_key()))
    principal = await verifier.verify(token(private_key))
    assert principal.workspace_id == str(uuid5(NAMESPACE_URL, "brandflow:clerk-org:workspace-1"))
    assert principal.role == "content_operator"
    assert principal.experience == "organization"
    with pytest.raises(jwt.InvalidAudienceError):
        await verifier.verify(token(private_key, aud="wrong"))
    with pytest.raises(jwt.InvalidIssuerError):
        await verifier.verify(token(private_key, iss="https://wrong"))


@pytest.mark.asyncio
async def test_clerk_verifier_accepts_default_session_token_and_member_role() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = ClerkJWTVerifier(jwks_url="https://unused", issuer="https://clerk.test", authorized_parties=["http://localhost:3000"], jwk_client=StaticJWKClient(private_key.public_key()))
    principal = await verifier.verify(session_token(private_key))
    assert principal.role == "content_operator"
    assert principal.workspace_id == str(uuid5(NAMESPACE_URL, "brandflow:clerk-org:org_workspace_1"))
    assert principal.experience == "organization"
    with pytest.raises(jwt.ExpiredSignatureError):
        await verifier.verify(session_token(private_key, exp=datetime.now(UTC) - timedelta(seconds=1)))


@pytest.mark.asyncio
async def test_clerk_verifier_derives_stable_personal_workspace_without_organization() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = ClerkJWTVerifier(jwks_url="https://unused", issuer="https://clerk.test", authorized_parties=["http://localhost:3000"], jwk_client=StaticJWKClient(private_key.public_key()))
    personal = await verifier.verify(session_token(private_key, o=None))
    expected_workspace = str(uuid5(NAMESPACE_URL, "brandagent:personal:user-1"))
    assert personal.experience == "personal"
    assert personal.workspace_id == expected_workspace
    assert personal.role == "admin"
    again = await verifier.verify(session_token(private_key, o=None))
    assert again.workspace_id == expected_workspace


@pytest.mark.asyncio
async def test_dev_mode_resolves_a_stable_personal_workspace() -> None:
    verifier = ClerkJWTVerifier(jwks_url="", issuer="", dev_mode=True)
    first = await verifier.verify("dev-token")
    second = await verifier.verify("dev-token")
    assert first.workspace_id == second.workspace_id
    assert first.experience == "personal"
    assert first.role == "admin"
    assert first.workspace_id == str(uuid5(NAMESPACE_URL, "brandagent:personal:anonymous"))


@pytest.mark.asyncio
async def test_clerk_verifier_rejects_unsupported_roles_and_foreign_parties() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = ClerkJWTVerifier(jwks_url="https://unused", issuer="https://clerk.test", authorized_parties=["http://localhost:3000"], jwk_client=StaticJWKClient(private_key.public_key()))
    with pytest.raises(ValueError, match="supported role"):
        await verifier.verify(session_token(private_key, o={"id": "org_workspace_1", "rol": "unknown"}))
    with pytest.raises(ValueError, match="authorized party"):
        await verifier.verify(session_token(private_key, azp="http://evil.local"))
