from __future__ import annotations

import base64
import html
import io
import json
import zipfile


SUPPORTED_FORMATS = {"json", "markdown", "docx", "preview"}


def _markdown(package: dict) -> str:
    sections = [f"# BrandFlow content package\n\nTask: `{package['task_id']}`"]
    for version in package["versions"]:
        label = version.get("channel") or "canonical-master"
        sections.append(f"## {label}\n\n{version['content']}")
    return "\n\n".join(sections) + "\n"


def _docx_base64(package: dict) -> str:
    paragraphs = ["BrandFlow content package", f"Task: {package['task_id']}"]
    for version in package["versions"]:
        paragraphs.extend([version.get("channel") or "Canonical master", version["content"]])
    document_xml = "".join(
        f"<w:p><w:r><w:t xml:space=\"preserve\">{html.escape(paragraph)}</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    content = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{document_xml}<w:sectPr/></w:body></w:document>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr("word/document.xml", content)
    return base64.b64encode(buffer.getvalue()).decode()


def render_package(package: dict, formats: list[str]) -> dict[str, dict]:
    requested = sorted(set(formats))
    unsupported = set(requested) - SUPPORTED_FORMATS
    if unsupported:
        raise ValueError(f"Unsupported export formats: {', '.join(sorted(unsupported))}")
    artifacts: dict[str, dict] = {}
    if "json" in requested:
        artifacts["json"] = {"media_type": "application/json", "encoding": "utf-8", "content": json.dumps(package, ensure_ascii=False, sort_keys=True)}
    if "markdown" in requested:
        artifacts["markdown"] = {"media_type": "text/markdown", "encoding": "utf-8", "content": _markdown(package)}
    if "docx" in requested:
        artifacts["docx"] = {"media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "encoding": "base64", "content": _docx_base64(package)}
    if "preview" in requested:
        body = "".join(f"<article><h2>{html.escape(version.get('channel') or 'Canonical master')}</h2><pre>{html.escape(version['content'])}</pre></article>" for version in package["versions"])
        artifacts["preview"] = {"media_type": "text/html", "encoding": "utf-8", "content": f"<!doctype html><html><body>{body}</body></html>"}
    return artifacts
