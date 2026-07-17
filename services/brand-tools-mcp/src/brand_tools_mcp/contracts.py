from enum import StrEnum


class Capability(StrEnum):
    READ = "read"
    WRITE = "write"
    HIGH_RISK = "high_risk"


TOOL_CAPABILITIES = {
    "search_brand_documents": Capability.READ,
    "get_product_facts": Capability.READ,
    "get_brand_guidelines": Capability.READ,
    "get_channel_spec": Capability.READ,
    "validate_marketing_claims": Capability.READ,
    "validate_channel_content": Capability.READ,
    "save_content_version": Capability.WRITE,
    "export_content_package": Capability.HIGH_RISK,
    "create_publish_preview": Capability.HIGH_RISK,
}
