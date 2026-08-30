"""Hardening regression tests (security review P2 fixes)."""

from __future__ import annotations

import pytest

from agent_api.domain.consumer import assert_safe_material_url, material_checksum, MaterialValidationError


class TestNumericIpSsrf:
    @pytest.mark.parametrize(
        "url",
        [
            "http://2130706433/secret",  # integer 127.0.0.1
            "http://0x7f000001/secret",  # hex loopback
            "http://0177.0.0.1/secret",  # octal loopback
            "http://0x7f.0.0.1/secret",  # hex octet loopback
            "http://3232235777/secret",  # integer 192.168.1.1
        ],
    )
    def test_numeric_ip_spellings_are_rejected(self, url: str) -> None:
        with pytest.raises(MaterialValidationError):
            assert_safe_material_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/article",
            "http://1.1.1.1/",
        ],
    )
    def test_public_hosts_still_pass(self, url: str) -> None:
        assert assert_safe_material_url(url) == url


class TestWorkspaceSeededChecksum:
    def test_identical_content_in_two_workspaces_gets_different_checksums(self) -> None:
        first = material_checksum("ws-a", "同样的内容")
        second = material_checksum("ws-b", "同样的内容")
        assert first != second, "checksum must be workspace-scoped to prevent global chunk collisions"

    def test_same_workspace_same_content_is_stable(self) -> None:
        assert material_checksum("ws-a", "内容") == material_checksum("ws-a", "内容")
