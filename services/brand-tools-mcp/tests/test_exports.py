import base64
import io
import zipfile

from brand_tools_mcp.exports import render_package


def test_renders_json_markdown_docx_and_safe_preview() -> None:
    package = {"task_id": "task-1", "versions": [{"channel": "wechat_website", "content": "<script>alert(1)</script>正文"}]}
    artifacts = render_package(package, ["json", "markdown", "docx", "preview"])
    assert set(artifacts) == {"json", "markdown", "docx", "preview"}
    assert "正文" in artifacts["markdown"]["content"]
    assert "<script>" not in artifacts["preview"]["content"]
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(artifacts["docx"]["content"]))) as archive:
        assert "word/document.xml" in archive.namelist()
