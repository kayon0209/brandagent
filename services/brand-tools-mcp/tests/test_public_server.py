"""Public read-only MCP instance tests (agentization P2-1).

Security contract of the public edge:
- exactly four READ tools are registered; write/high-risk/validator tools
  are absent from the tool registry (absence is the control, not authz)
- static tokens are one trust source (malformed/duplicate/empty token
  files fail loudly at load); Clerk JWTs are the second (P2-1 OAuth
  enhancement): verified against the JWKS, workspace derived with the
  SAME uuid5 rule as agent-api, org tokens rejected on this edge
- the ASGI gate rejects: no bearer, unknown credential
- a valid credential is pinned to one workspace_id (scope["state"])
"""

from __future__ import annotations

import jwt
import pytest

from brand_tools_mcp.public_server import (
    READ_TOOLS,
    create_public_mcp,
    load_public_tokens,
    PublicAuthMiddleware,
)


class _StubRepository:
    async def search_documents(self, workspace_id, query, limit):
        return [{"document_id": "d1", "document_name": "规格", "match": query}]

    async def product_facts(self, workspace_id, product_id):
        return [{"fact_id": "f1", "fact_content": "续航 12 小时"}]

    async def brand_guidelines(self, workspace_id, brand_id):
        return {"version": "3", "tone": "克制、可靠"}

    async def channel_spec(self, workspace_id, channel):
        return {"version": "2", "length_rules": {"max": 800}}

    async def supported_channels(self, workspace_id):
        # defaults + one custom channel, mirroring the spec-table rule
        from brand_tools_mcp.default_specs import DEFAULT_CHANNEL_SPECS

        return set(DEFAULT_CHANNEL_SPECS) | {"custom_zhihu"}


def _registered_names(mcp) -> set:
    return {tool.name for tool in mcp._tool_manager.list_tools()}


def test_public_registry_contains_only_the_four_read_tools():
    mcp = create_public_mcp(_StubRepository())
    names = _registered_names(mcp)
    assert names == set(READ_TOOLS), f"unexpected public tool surface: {names}"


def test_write_and_high_risk_tools_are_absent_from_the_public_registry():
    mcp = create_public_mcp(_StubRepository())
    names = _registered_names(mcp)
    for forbidden in (
        "save_content_version",
        "export_content_package",
        "create_publish_preview",
        "validate_marketing_claims",
        "validate_channel_content",
    ):
        assert forbidden not in names


def test_token_file_requires_pairs_and_rejects_garbage(tmp_path):
    good = tmp_path / "tokens.txt"
    good.write_text("# comment\nsk-public-1 00000000-0000-0000-0000-00000000ws1\n", encoding="utf8")
    assert load_public_tokens(str(good)) == {"sk-public-1": "00000000-0000-0000-0000-00000000ws1"}

    malformed = tmp_path / "bad.txt"
    malformed.write_text("only-a-token-without-workspace\n", encoding="utf8")
    with pytest.raises(ValueError):
        load_public_tokens(str(malformed))

    duplicate = tmp_path / "dup.txt"
    duplicate.write_text(
        "sk-a 00000000-0000-0000-0000-00000000ws1\nsk-a 00000000-0000-0000-0000-00000000ws2\n",
        encoding="utf8",
    )
    with pytest.raises(ValueError):
        load_public_tokens(str(duplicate))

    empty = tmp_path / "empty.txt"
    empty.write_text("# nothing but comments\n", encoding="utf8")
    with pytest.raises(ValueError):
        load_public_tokens(str(empty))


@pytest.mark.asyncio
async def test_gate_rejects_missing_and_unknown_tokens():
    captured: dict = {}

    async def inner(scope, receive, send):
        captured["state"] = scope.get("state")

    gate = PublicAuthMiddleware(inner, {"sk-good": "ws-1"})

    # no bearer -> 401 before the app runs
    scope = {"type": "http", "path": "/mcp", "headers": []}
    sent: list = []

    async def receive():
        return {}

    async def send(message):
        sent.append(message)

    await gate(scope, receive, send)
    assert sent and sent[0]["status"] == 401
    assert "state" not in captured

    # unknown token -> 401
    sent.clear()
    scope = {"type": "http", "path": "/mcp", "headers": [(b"authorization", b"Bearer sk-wrong")]}
    await gate(scope, receive, send)
    assert sent and sent[0]["status"] == 401
    assert "state" not in captured


@pytest.mark.asyncio
async def test_valid_token_pins_its_workspace_into_scope_state():
    captured: dict = {}

    async def inner(scope, receive, send):
        captured["state"] = scope.get("state")

    gate = PublicAuthMiddleware(inner, {"sk-good": "ws-42"})
    scope = {"type": "http", "path": "/mcp", "headers": [(b"authorization", b"Bearer sk-good")]}

    async def receive():
        return {}

    async def send(message):
        pass

    await gate(scope, receive, send)
    # the ONLY workspace reachable under this token is ws-42; the tool
    # layer (and the RLS store below it) enforces the binding
    assert captured["state"] == {"public_workspace_id": "ws-42"}


@pytest.mark.asyncio
async def test_non_mcp_paths_bypass_the_gate():
    hits: list = []

    async def inner(scope, receive, send):
        hits.append(scope.get("path"))

    gate = PublicAuthMiddleware(inner, {"sk": "ws"})
    scope = {"type": "http", "path": "/health", "headers": []}

    async def receive():
        return {}

    async def send(message):
        pass

    await gate(scope, receive, send)
    assert hits == ["/health"]


@pytest.mark.asyncio
async def test_real_transport_serves_four_read_tools_and_gates_unknown_tokens() -> None:
    """End-to-end over the real streamable-http transport: a session with
    no/unknown bearer must never reach the tool registry; the client sees
    the four read tools and can call one against the stub store."""
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    mcp = create_public_mcp(_StubRepository())
    inner_app = mcp.streamable_http_app()
    app = PublicAuthMiddleware(inner_app, {"sk-public-1": "ws-42"})
    transport = httpx.ASGITransport(app=app)
    # the FastMCP session task group only initializes under the app's
    # lifespan context (same pattern as test_transport_contract.py)
    async with inner_app.router.lifespan_context(inner_app):
        # headers ride on the AsyncClient (the SDK's streamable_http_client
        # takes no headers kwarg; agent-api's RealMCPClient does the same)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://mcp.test", headers={"Authorization": "Bearer sk-public-1"}
        ) as http_client:
            # 1. without a token the MCP handshake itself fails with 401
            async with httpx.AsyncClient(transport=transport, base_url="http://mcp.test") as bare_client:
                rejected = await bare_client.post(
                    "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
                )
                assert rejected.status_code == 401

            # 2. with the token the session initializes and lists only the read tools
            async with streamable_http_client("http://mcp.test/mcp", http_client=http_client) as (
                read_stream,
                write_stream,
                _session_id,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    discovered = await session.list_tools()
                    assert {tool.name for tool in discovered.tools} == set(READ_TOOLS)
                    result = await session.call_tool(
                        "search_brand_documents", {"workspace_id": "ws-42", "query": "规格"}
                    )
                    assert result.isError is False
                    assert result.structuredContent["data"]["items"][0]["document_id"] == "d1"


# ---------------------------------------------------------------------
# OAuth-style credential (P2-1 enhancement): Clerk JWT acceptance
# ---------------------------------------------------------------------

def _rsa_key():
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _StaticJWKClient:
    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token):
        class _K:
            pass

        holder = _K()
        holder.key = self.public_key
        return holder


def _personal_token(private_key, **overrides):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    claims = {
        "sub": "user-77",
        "iss": "https://clerk.test",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        **overrides,
    }
    return jwt.encode(claims, private_key, algorithm="RS256")


@pytest.mark.asyncio
async def test_clerk_jwt_resolves_to_the_personal_workspace():
    from brand_tools_mcp.public_clerk import PublicClerkVerifier
    from uuid import NAMESPACE_URL, uuid5

    key = _rsa_key()
    verifier = PublicClerkVerifier(
        jwks_url="https://unused", issuer="https://clerk.test", jwk_client=_StaticJWKClient(key.public_key())
    )
    workspace = await verifier.verify(_personal_token(key))
    # SAME derivation rule as agent-api ClerkJWTVerifier.verify
    assert workspace == str(uuid5(NAMESPACE_URL, "brandagent:personal:user-77"))


@pytest.mark.asyncio
async def test_gate_accepts_jwt_via_verifier_and_rejects_bad_signature():
    from brand_tools_mcp.public_clerk import PublicClerkVerifier

    key = _rsa_key()
    verifier = PublicClerkVerifier(
        jwks_url="https://unused", issuer="https://clerk.test", jwk_client=_StaticJWKClient(key.public_key())
    )
    gate = PublicAuthMiddleware(_never_app(), {"sk-static": "ws-static"}, jwt_verifier=verifier)

    # valid JWT -> the SAME derived personal workspace as agent-api would mint
    from uuid import NAMESPACE_URL, uuid5

    expected = str(uuid5(NAMESPACE_URL, "brandagent:personal:user-77"))
    state = await _run_gate(gate, {"Authorization": f"Bearer {_personal_token(key)}"})
    assert state["public_workspace_id"] == expected

    # tampered token (different signing key) -> 401
    other_key = _rsa_key()
    status = await _run_gate_status(gate, {"Authorization": f"Bearer {_personal_token(other_key)}"})
    assert status == 401

    # static table still works in parallel
    state = await _run_gate(gate, {"Authorization": "Bearer sk-static"})
    assert state["public_workspace_id"] == "ws-static"


@pytest.mark.asyncio
async def test_org_tokens_are_rejected_on_the_public_edge():
    from brand_tools_mcp.public_clerk import PublicClerkVerifier

    key = _rsa_key()
    verifier = PublicClerkVerifier(
        jwks_url="https://unused", issuer="https://clerk.test", jwk_client=_StaticJWKClient(key.public_key())
    )
    with pytest.raises(ValueError):
        await verifier.verify(_personal_token(key, org_id="org-1"))


def _never_app():
    async def app(scope, receive, send):
        raise AssertionError("must not reach the app unauthenticated")

    return app


async def _run_gate(gate, headers):
    captured = {}

    async def inner(scope, receive, send):
        captured["state"] = scope.get("state")

    wrapped = gate
    # re-wrap to capture: reuse gate internals by swapping application
    gate._application = inner
    scope = {"type": "http", "path": "/mcp", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}

    async def receive():
        return {}

    async def send(message):
        pass

    await wrapped(scope, receive, send)
    return captured["state"]


async def _run_gate_status(gate, headers):
    status_box = {}

    async def send(message):
        if message["type"] == "http.response.start":
            status_box["status"] = message["status"]

    scope = {"type": "http", "path": "/mcp", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}

    async def receive():
        return {}

    await gate(scope, receive, send)
    return status_box.get("status")


def test_no_credential_source_fails_loudly(monkeypatch):
    """App factory must refuse to start with neither static tokens nor Clerk."""
    from brand_tools_mcp import public_server

    class _EmptySettings:
        public_tokens_path = None
        public_clerk_jwks_url = None
        host = "127.0.0.1"
        public_port = 8200

        def require_database_url(self):
            return "postgresql://unused"

    monkeypatch.setattr(public_server, "Settings", lambda: _EmptySettings())
    with pytest.raises(RuntimeError, match="credential source"):
        public_server.create_public_app()


def test_malformed_clerk_config_fails_loudly(monkeypatch):
    from brand_tools_mcp import public_server

    class _BadSettings:
        public_tokens_path = None
        public_clerk_jwks_url = "http://insecure.example/jwks"  # not https
        public_clerk_issuer = "https://clerk.test"
        host = "127.0.0.1"
        public_port = 8200

        def require_database_url(self):
            return "postgresql://unused"

    monkeypatch.setattr(public_server, "Settings", lambda: _BadSettings())
    with pytest.raises(RuntimeError):
        public_server.create_public_app()
