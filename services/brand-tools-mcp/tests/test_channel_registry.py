"""Spec-table-driven channel support (agentization P2-2).

Until P2-2 the channel surface was the hardcoded CHANNELS enum; now a
workspace's usable channels = active channel_spec_versions rows UNION
the four built-in defaults. These tests pin the new contract:

- a custom channel with an active spec row is supported by every
  channel-consuming tool (get spec / validate / save channel version)
- a channel with neither a spec row nor a default stays rejected
- the built-in four keep working with no seeding step
"""

from __future__ import annotations

import pytest

from brand_tools_mcp.default_specs import DEFAULT_CHANNEL_SPECS
from brand_tools_mcp.tools import create_mcp


BUILTIN = set(DEFAULT_CHANNEL_SPECS)


class SpecTableStore:
    """Fake store simulating channel_spec_versions rows for one workspace."""

    def __init__(self, *, rows: dict[str, dict | None]) -> None:
        # rows: channel -> spec dict (active row) ; None means no row
        self._rows = rows
        self.saved: list[tuple] = []

    async def open(self):
        return None

    async def close(self):
        return None

    async def search_documents(self, workspace_id, query, limit):
        return []

    async def product_facts(self, workspace_id, product_id):
        return []

    async def brand_guidelines(self, workspace_id, brand_id):
        return None

    async def channel_spec(self, workspace_id, channel):
        return self._rows.get(channel)

    async def supported_channels(self, workspace_id):
        # exactly the repository rule: active rows UNION built-ins
        return {c for c, spec in self._rows.items() if spec is not None} | BUILTIN

    async def save_version(self, workspace_id, task_id, content_type, content, parent_version_id, actor_id, idempotency_key, channel, master_content_version_id):
        self.saved.append((content_type, channel, master_content_version_id))
        return {"content_version_id": "cv-1", "version_number": 1, "immutable_hash": "a" * 64}, False

    async def authorized_package(self, **kwargs):
        raise AssertionError("high-risk path must not be touched by these tests")


def mcp_of(store) -> object:
    return create_mcp(store, require_trusted_scope=False)


async def call_tool(mcp, name: str, arguments: dict) -> dict:
    """Invoke a registered tool through its raw function (registry-level
    test: no transport needed; transport behavior is covered elsewhere)."""
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    return await tools[name].fn(**arguments)


@pytest.mark.asyncio
async def test_custom_channel_with_active_spec_is_supported():
    store = SpecTableStore(rows={"custom_zhihu": {"version": "z1", "length_rules": {"max": 500}, "forbidden_patterns": []}})
    mcp = mcp_of(store)

    result = await call_tool(mcp, "get_channel_spec", {"workspace_id": "ws-1", "channel": "custom_zhihu"})
    assert result["status"] == "succeeded"
    assert result["data"]["version"] == "z1"


@pytest.mark.asyncio
async def test_channel_without_spec_row_and_not_default_stays_rejected():
    store = SpecTableStore(rows={})
    mcp = mcp_of(store)
    with pytest.raises(Exception, match="Unsupported channel"):
        await call_tool(mcp, "get_channel_spec", {"workspace_id": "ws-1", "channel": "telegram_broadcast"})


@pytest.mark.asyncio
async def test_builtin_channels_work_without_any_seeding():
    store = SpecTableStore(rows={})  # no rows at all
    mcp = mcp_of(store)
    for channel in BUILTIN:
        result = await call_tool(mcp, "get_channel_spec", {"workspace_id": "ws-1", "channel": channel})
        # degraded (no row) is fine — the channel is still SUPPORTED;
        # the internal pipeline seeds defaults elsewhere
        assert result["status"] in ("succeeded", "degraded")


@pytest.mark.asyncio
async def test_save_channel_version_accepts_custom_channel():
    store = SpecTableStore(rows={"custom_zhihu": {"version": "z1", "length_rules": {}, "forbidden_patterns": []}})
    mcp = mcp_of(store)
    result = await call_tool(
        mcp,
        "save_content_version",
        {
            "workspace_id": "ws-1",
            "task_id": "t-1",
            "content_type": "channel_draft",
            "content": "自定义渠道内容",
            "actor_id": "user-1",
            "idempotency_key": "idem-" + "k" * 20,
            "channel": "custom_zhihu",
            "master_content_version_id": "mv-1",
        },
    )
    assert result["status"] == "succeeded"
    assert store.saved == [("channel_draft", "custom_zhihu", "mv-1")]


@pytest.mark.asyncio
async def test_validate_channel_content_runs_against_custom_spec_rules():
    store = SpecTableStore(
        rows={"custom_zhihu": {"version": "z1", "length_rules": {"max": 10}, "forbidden_patterns": ["加微信"]}}
    )
    mcp = mcp_of(store)
    result = await call_tool(
        mcp,
        "validate_channel_content",
        {"workspace_id": "ws-1", "channel": "custom_zhihu", "content": "这是一条超过十个字的内容，还带着加微信"},
    )
    assert result["status"] == "succeeded"
    assert result["data"]["passed"] is False
    assert "content_too_long" in result["data"]["issues"]
    assert "forbidden_pattern:加微信" in result["data"]["issues"]


@pytest.mark.asyncio
async def test_spec_table_scope_is_per_workspace():
    """The supported set must come from the CALLING workspace's rows —
    a stub-level pin of the repository contract documented on
    supported_channels()."""
    store = SpecTableStore(rows={"custom_zhihu": {"version": "z1", "length_rules": {}, "forbidden_patterns": []}})
    seen: list[str] = []

    async def spy(workspace_id):
        seen.append(workspace_id)
        return await SpecTableStore.supported_channels(store, workspace_id)

    store.supported_channels = spy  # type: ignore[method-assign]
    mcp = mcp_of(store)
    await call_tool(mcp, "get_channel_spec", {"workspace_id": "ws-target", "channel": "custom_zhihu"})
    assert seen == ["ws-target"]
