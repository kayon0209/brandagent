from dataclasses import dataclass
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncio
import jwt
from jwt import PyJWKClient


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    workspace_id: str
    role: str


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> Principal: ...


class ClerkJWTVerifier:
    def __init__(
        self, *, jwks_url: str, issuer: str, audience: str | None = None,
        authorized_parties: list[str] | None = None, jwk_client: PyJWKClient | None = None,
        dev_mode: bool = False,
    ) -> None:
        if not dev_mode and (not jwks_url or not issuer):
            raise ValueError("Clerk JWKS URL and issuer are required")
        if dev_mode and not jwks_url:
            jwks_url = "https://clerk.example.com/.well-known/jwks.json"
        if dev_mode and not issuer:
            issuer = "https://clerk.example.com"
        self._issuer = issuer
        self._audience = audience
        self._authorized_parties = set(authorized_parties or [])
        self._dev_mode = dev_mode
        if not dev_mode and not audience and not self._authorized_parties:
            raise ValueError("Clerk audience or authorized parties are required")
        if dev_mode:
            self._client = None
        else:
            self._client = jwk_client or PyJWKClient(jwks_url, cache_keys=True, lifespan=300)

    async def verify(self, token: str) -> Principal:
        if self._dev_mode:
            from uuid import uuid4
            return Principal(user_id="anonymous", workspace_id=str(uuid4()), role="content_operator")
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
        if not self._dev_mode:
            authorized_party = claims.get("azp")
            if self._authorized_parties and authorized_party not in self._authorized_parties:
                raise ValueError("Token authorized party is not allowed")
        organization = claims.get("o") if isinstance(claims.get("o"), dict) else {}
        external_workspace_id = claims.get("org_id") or organization.get("id")
        raw_role = claims.get("org_role") or organization.get("rol")
        role_map = {
            "org:content_operator": "content_operator",
            "org:brand_reviewer": "brand_reviewer",
            "org:final_approver": "final_approver",
            "org:admin": "admin",
            "org:member": "content_operator",
            "content_operator": "content_operator",
            "brand_reviewer": "brand_reviewer",
            "final_approver": "final_approver",
            "admin": "admin",
            "member": "content_operator",
        }
        if not isinstance(external_workspace_id, str):
            if self._dev_mode:
                external_workspace_id = "dev-workspace-default"
            else:
                raise ValueError("Active organization context is required")
        if raw_role not in role_map:
            if self._dev_mode:
                raw_role = "org:member"
            else:
                raise ValueError("Active organization has no supported role")
        try:
            workspace_id = str(UUID(external_workspace_id))
        except ValueError:
            workspace_id = str(uuid5(NAMESPACE_URL, f"brandflow:clerk-org:{external_workspace_id}"))
        return Principal(user_id=claims["sub"], workspace_id=workspace_id, role=role_map[raw_role])
