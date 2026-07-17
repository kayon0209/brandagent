from __future__ import annotations

import difflib


def version_diff(parent: dict, current: dict) -> dict:
    before = str(parent.get("content", "")).splitlines()
    after = str(current.get("content", "")).splitlines()
    operations = []
    for line in difflib.ndiff(before, after):
        if line.startswith("- "):
            operations.append({"operation": "remove", "text": line[2:], "change_type": "text"})
        elif line.startswith("+ "):
            operations.append({"operation": "add", "text": line[2:], "change_type": _classify(line[2:])})
    creator = current.get("created_by_type")
    return {
        "parent_version_id": str(parent.get("content_version_id")),
        "current_version_id": str(current.get("content_version_id")),
        "created_by": creator,
        "edit_origin": "human_edit" if creator == "human" else "ai_generated" if creator == "model" else "workflow_generated",
        "operations": operations,
        "summary": {
            "additions": sum(item["operation"] == "add" for item in operations),
            "removals": sum(item["operation"] == "remove" for item in operations),
        },
    }


def _classify(text: str) -> str:
    lowered = text.casefold()
    if any(token in lowered for token in ("%", "￥", "$", "fact", "数据", "参数")):
        return "fact"
    if any(token in lowered for token in ("必须", "禁止", "合规", "风险")):
        return "compliance_correction"
    if text.startswith(("#", "一、", "二、", "1.", "2.")):
        return "structure"
    if any(token in lowered for token in ("cta", "主题：", "subject:", "#")):
        return "channel_format"
    return "text"
