from agent_api.evaluation.diffing import version_diff


def test_diff_classifies_human_fact_and_structure_edits() -> None:
    result = version_diff(
        {"content_version_id": "v1", "content": "标题\n旧文案"},
        {"content_version_id": "v2", "content": "# 新标题\n参数提升 20%", "created_by_type": "human"},
    )
    assert result["edit_origin"] == "human_edit"
    assert {item["change_type"] for item in result["operations"] if item["operation"] == "add"} == {"structure", "fact"}
