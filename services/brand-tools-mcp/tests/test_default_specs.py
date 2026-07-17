from brand_tools_mcp.default_specs import CHANNEL_SPEC_VERSION, DEFAULT_CHANNEL_SPECS


def test_all_four_channel_specs_are_versioned_and_complete() -> None:
    assert set(DEFAULT_CHANNEL_SPECS) == {"wechat_website", "xiaohongshu", "video_script_60s", "marketing_email"}
    for specification in DEFAULT_CHANNEL_SPECS.values():
        assert specification["version"] == CHANNEL_SPEC_VERSION
        assert specification["required_fields"]
        assert specification["length_rules"]["max_characters"] > specification["length_rules"]["min_characters"]
