"""Clerk JWT verification for the PUBLIC read-only MCP instance.

Deliberately a small, self-contained verifier (the MCP service must not
import agent-api): RS256 via the Clerk JWKS endpoint, exp/iat/iss checks,
and the SAME personal-workspace derivation rule agent-api uses
(uuid5("brandagent:personal:{sub}")) so a creator's BrandAgent session
identity maps to one workspace on both services.

Organization claims (org_id/org role) are intentionally NOT handled here:
the public edge serves personal workspaces only. An org-bound token is
rejected - org knowledge stays on the internal instance.
"""

from __future__ import annotations

import asyncio
from uuid import NAMESPACE_URL, uuid5

import jwt
from jwt import PyJWKClient


class PublicClerkVerifier:
    def __init__(
        self,
        *,
        jwks_url: str,
        issuer: str,
        audience: str | None = None,
        authorized_parties: list[str] | None = None,
        jwk_client: PyJWKClient | None = None,
    ) -> None:
        if not jwks_url.startswith("https://"):
            raise ValueError("public Clerk JWKS URL must be https")
        self._issuer = issuer
        self._audience = audience
        self._authorized_parties = set(authorized_parties or [])
        self._client = jwk_client or PyJWKClient(jwks_url, cache_keys=True, lifespan=300)

    async def verify(self, token: str) -> str:
        """Verify the bearer JWT and return the caller's personal workspace_id."""
        signing_key = await asyncio.to_thread(self._client.get_signing_key_from_jwt, token)
        kwargs = {"issuer": self._issuer}
        required = ["exp", "iat", "iss", "sub"]
        if self._audience:
            kwargs["audience"] = self._audience
            required.append("aud")
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"require": required, "verify_aud": bool(self._audience)},
            **kwargs,
        )
        if "azp" in claims and self._authorized_parties and claims["azp"] not in self._authorized_parties:
            raise ValueError("Token authorized party is not allowed")
        if claims.get("org_id") or (isinstance(claims.get("o"), dict) and claims["o"].get("id")):
            # public edge serves personal workspaces only
            raise ValueError("organization tokens are not accepted on the public instance")
        return str(uuid5(NAMESPACE_URL, f"brandagent:personal:{claims['sub']}"))
