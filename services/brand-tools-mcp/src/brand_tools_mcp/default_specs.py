CHANNEL_SPEC_VERSION = "brandflow-channel-v1"


DEFAULT_CHANNEL_SPECS = {
    "wechat_website": {
        "version": CHANNEL_SPEC_VERSION,
        "length_rules": {"min_characters": 600, "max_characters": 4000},
        "required_fields": ["title", "body", "cta"],
        "tone": ["credible", "editorial", "clear"],
        "cta_style": {"max": 1, "style": "explicit_next_step"},
        "hashtag_rules": {"allowed": False},
        "forbidden_patterns": ["点击暴富", "100%保证"],
    },
    "xiaohongshu": {
        "version": CHANNEL_SPEC_VERSION,
        "length_rules": {"min_characters": 300, "max_characters": 1000},
        "required_fields": ["title", "body", "cta"],
        "tone": ["specific", "human", "concise"],
        "cta_style": {"max": 1, "style": "conversation_prompt"},
        "hashtag_rules": {"max": 8, "required": False},
        "forbidden_patterns": ["绝对有效", "全网第一"],
    },
    "video_script_60s": {
        "version": CHANNEL_SPEC_VERSION,
        "length_rules": {"min_characters": 180, "max_characters": 420},
        "required_fields": ["hook", "body", "cta"],
        "tone": ["spoken", "precise", "paced"],
        "cta_style": {"max": 1, "style": "spoken_next_step"},
        "hashtag_rules": {"allowed": False},
        "forbidden_patterns": ["无敌", "零风险"],
    },
    "marketing_email": {
        "version": CHANNEL_SPEC_VERSION,
        "length_rules": {"min_characters": 250, "max_characters": 1600},
        "required_fields": ["subject", "preview_text", "body", "cta"],
        "tone": ["professional", "direct", "helpful"],
        "cta_style": {"max": 1, "style": "single_primary_action"},
        "hashtag_rules": {"allowed": False},
        "forbidden_patterns": ["立即发财", "永久有效"],
    },
}
