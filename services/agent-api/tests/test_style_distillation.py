"""Six-layer author style distillation tests (round-3 feature).

Pins the service contract: corpus validation (min 2 articles / max 20 /
char cap), form allowlist, language separation (CJK detection + explicit
override), the six-layer JSON parse (includ: fenced output, uninferable
layer honesty), and the provider-usage passthrough.
"""

from __future__ import annotations

import json

import pytest

from agent_api.api.security import Principal
from agent_api.application.style_distillation import (
    StyleDistillationError,
    StyleDistillationService,
    detect_language,
)
from agent_api.providers.base import ModelCallResult


def principal_for(workspace_id: str) -> Principal:
    return Principal(user_id="consumer-1", workspace_id=workspace_id, role="admin", experience="personal")


class RecordingProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[str] = []

    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult:
        self.calls.append(system)
        return ModelCallResult(
            content=self.content,
            provider="stub",
            model="stub",
            prompt_version=prompt_version,
            latency_ms=10,
            input_tokens=10,
            output_tokens=10,
            usage_source="none",
            retry_count=0,
        )


class MemoryReportStore:
    def __init__(self) -> None:
        self.reports: list[dict] = []

    async def insert_style_report(
        self, workspace_id, form, language, layers, corpus_digest, *, corpus_stats=None, corpus_articles=None
    ):
        report = {
            "report_id": "r-1",
            "workspace_id": workspace_id,
            "form": form,
            "language": language,
            "layers": layers,
            "corpus_digest": corpus_digest,
            "corpus_stats": corpus_stats or {},
            "corpus_articles": corpus_articles or [],
            "created_at": "2026-09-05T00:00:00+00:00",
        }
        self.reports.append(report)
        return dict(report)

    async def list_style_reports(self, workspace_id):
        return [dict(r) for r in self.reports if r["workspace_id"] == workspace_id]


SIX_LAYER_JSON = json.dumps(
    {
        "l1_language_dna": {"rules": ["句子平均 22 字", "多用具体名词"], "summary": "短句 + 名词驱动"},
        "l2_structure_template": {"rules": ["以提问开头", "三段展开"], "summary": "hook-展开-收束"},
        "l3_topic_logic": {"rules": ["围绕真实经历选题"], "summary": "第一人称经验切入"},
        "l4_evidence_strategy": {"rules": ["数据只引用一次", "案例放开头"], "summary": "轻数据重案例"},
        "l5_cognitive_frame": {"rules": ["假设读者聪明但忙"], "summary": "务实怀疑主义"},
        "l6_visual_guide": {"rules": [], "summary": ""},
    },
    ensure_ascii=False,
)


def make_service(content: str = SIX_LAYER_JSON):
    provider = RecordingProvider(content)
    store = MemoryReportStore()
    return StyleDistillationService(store=store, provider=provider), store, provider


@pytest.mark.asyncio
async def test_six_layers_distilled_from_a_corpus():
    service, store, _ = make_service()
    report = await service.analyze(
        principal_for("ws-1"),
        articles=["第一篇完整文章的内容，讲述产品发布。", "第二篇完整文章，讲述行业观察。"],
        form="wechat_article",
    )
    layers = report["layers"]
    assert set(layers) == {
        "l1_language_dna",
        "l2_structure_template",
        "l3_topic_logic",
        "l4_evidence_strategy",
        "l5_cognitive_frame",
        "l6_visual_guide",
    }
    assert layers["l1_language_dna"]["rules"] == ["句子平均 22 字", "多用具体名词"]
    # uninferable layer stays honest instead of fabricated rules
    assert layers["l6_visual_guide"]["rules"] == []
    assert "无法推断" in layers["l6_visual_guide"]["summary"]
    assert store.reports and store.reports[0]["language"] == "zh"


@pytest.mark.asyncio
async def test_language_follows_the_corpus_english():
    service, _, _ = make_service()
    report = await service.analyze(
        principal_for("ws-1"),
        articles=["A complete English article about shipping fast.", "Another full essay on taste and software."],
        form="blog",
    )
    assert report["language"] == "en"


@pytest.mark.asyncio
async def test_explicit_output_language_overrides_detection():
    service, _, _ = make_service()
    report = await service.analyze(
        principal_for("ws-1"),
        articles=["第一篇中文完整文章内容。", "第二篇中文完整文章内容。"],
        form="long_form",
        output_language="en",
    )
    assert report["language"] == "en"


def test_detect_language_threshold():
    assert detect_language("这是一段中文内容") == "zh"
    assert detect_language("plain english text only") == "en"
    assert detect_language("mixed 中英 text but english dominates more words") == "en"


@pytest.mark.asyncio
async def test_corpus_of_one_is_rejected_with_explained_reason():
    service, _, provider = make_service()
    with pytest.raises(StyleDistillationError) as error:
        await service.analyze(principal_for("ws-1"), articles=["唯一一篇文章"], form="blog")
    # single-article imitation is exactly the failure mode this feature exists to avoid
    assert "单篇模仿" in str(error.value)
    assert provider.calls == []


@pytest.mark.asyncio
async def test_over_cap_corpus_is_rejected():
    service, _, _ = make_service()
    with pytest.raises(StyleDistillationError):
        await service.analyze(
            principal_for("ws-1"),
            articles=[f"第 {i} 篇完整文章内容，长度足以构成正式语料。" for i in range(1, 23)],
            form="blog",
        )


@pytest.mark.asyncio
async def test_unsupported_form_is_rejected():
    service, _, _ = make_service()
    with pytest.raises(StyleDistillationError) as error:
        await service.analyze(
            principal_for("ws-1"),
            articles=["第一篇文章。", "第二篇文章。"],
            form="poem",
        )
    assert error.value.code == "STYLE_FORM_UNSUPPORTED"


@pytest.mark.asyncio
async def test_markdown_fenced_model_output_is_tolerated():
    fenced = f"```json\n{SIX_LAYER_JSON}\n```"
    service, _, _ = make_service(content=fenced)
    report = await service.analyze(
        principal_for("ws-1"),
        articles=["第一篇完整中文文章。", "第二篇完整中文文章。"],
        form="newsletter",
    )
    assert report["layers"]["l1_language_dna"]["rules"]


@pytest.mark.asyncio
async def test_unparseable_output_keeps_usage_for_the_completed_model_call():
    service, _, _ = make_service(content="not json at all")
    usage: dict = {}
    with pytest.raises(StyleDistillationError) as error:
        await service.analyze(
            principal_for("ws-1"),
            articles=["第一篇完整中文文章。", "第二篇完整中文文章。"],
            form="blog",
            usage_out=usage,
        )
    assert "本次模型调用已计费" in str(error.value)
    assert usage == {
        "input_tokens": 10,
        "output_tokens": 10,
        "model": "stub",
        "model_executed": True,
    }


@pytest.mark.asyncio
async def test_usage_passthrough_for_ledger_settlement():
    service, _, _ = make_service()
    usage: dict = {}
    await service.analyze(
        principal_for("ws-1"),
        articles=["第一篇完整中文文章。", "第二篇完整中文文章。"],
        form="blog",
        usage_out=usage,
    )
    assert usage["input_tokens"] == 10 and usage["output_tokens"] == 10
    assert usage["model_executed"] is True


# ---------------------------------------------------------------------
# P0-A: corpus-digest short-circuit — the same corpus must never bill twice
# ---------------------------------------------------------------------

class DigestAwareStore(MemoryReportStore):
    def __init__(self) -> None:
        super().__init__()
        self.digest_index: dict[tuple[str, str, str], dict] = {}
        self.provenance_seen: list[dict] = []

    async def insert_style_report(
        self, workspace_id, form, language, layers, corpus_digest, *, corpus_stats=None, corpus_articles=None
    ):
        report = await super().insert_style_report(
            workspace_id, form, language, layers, corpus_digest,
            corpus_stats=corpus_stats, corpus_articles=corpus_articles,
        )
        self.digest_index[(form, language, corpus_digest)] = dict(report)
        return report

    async def find_by_digest(self, workspace_id, form, language, corpus_digest):
        return dict(self.digest_index[(form, language, corpus_digest)]) if (form, language, corpus_digest) in self.digest_index else None

    async def get_style_report(self, workspace_id, report_id):
        for report in self.reports:
            if report["report_id"] == report_id:
                return dict(report)
        return None


@pytest.mark.asyncio
async def test_same_corpus_second_analysis_short_circuits_without_a_model_call():
    provider = RecordingProvider(SIX_LAYER_JSON)
    store = DigestAwareStore()
    service = StyleDistillationService(store=store, provider=provider)
    articles = ["第一篇完整中文文章的内容。", "第二篇完整中文文章的内容。"]

    first = await service.analyze(principal_for("ws-1"), articles=articles, form="blog")
    clean, digest, language = service.prepare(articles=articles, form="blog", output_language=None)
    second = await service.find_existing_report(principal_for("ws-1"), form="blog", language=language, corpus_digest=digest)

    # the route uses prepare()+find_existing_report() BEFORE ledgered_call;
    # this pins the exact contract: second lookup returns the same report
    assert second is not None and second["report_id"] == first["report_id"]
    assert provider.calls == ["<system>"] or len(provider.calls) == 1  # exactly one model call


@pytest.mark.asyncio
async def test_different_corpus_does_not_short_circuit():
    provider = RecordingProvider(SIX_LAYER_JSON)
    store = DigestAwareStore()
    service = StyleDistillationService(store=store, provider=provider)

    first = await service.analyze(
        principal_for("ws-1"), articles=["第一篇文章内容。", "第二篇文章内容。"], form="blog"
    )
    _, digest_first, language = service.prepare(articles=["第一篇文章内容。", "第二篇文章内容。"], form="blog", output_language=None)
    changed_lookup = await service.find_existing_report(
        principal_for("ws-1"),
        form="blog",
        language=language,
        corpus_digest=digest_first + "-changed",  # a different corpus digest
    )
    assert changed_lookup is None  # a DIFFERENT corpus must miss and analyze anew


@pytest.mark.asyncio
async def test_prepare_is_the_single_digest_parity_source():
    """prepare() digest must equal what analyze() stored — otherwise the
    route short-circuit and the service could disagree on 'same corpus'."""
    provider = RecordingProvider(SIX_LAYER_JSON)
    store = DigestAwareStore()
    service = StyleDistillationService(store=store, provider=provider)
    articles = ["甲文章完整内容一。", "乙文章完整内容二。"]
    report = await service.analyze(principal_for("ws-1"), articles=articles, form="blog")
    clean, digest, language = service.prepare(articles=articles, form="blog", output_language=None)
    assert report["corpus_digest"] == digest
    assert report["language"] == language
    # whitespace-only edits must still hit the digest (clean happens first)
    padded = ["  甲文章完整内容一。  ", "\n乙文章完整内容二。\n"]
    _, padded_digest, _ = service.prepare(articles=padded, form="blog", output_language=None)
    assert padded_digest == digest


@pytest.mark.asyncio
async def test_get_report_scopes_to_none_for_unknown_ids():
    provider = RecordingProvider(SIX_LAYER_JSON)
    store = DigestAwareStore()
    service = StyleDistillationService(store=store, provider=provider)
    report = await service.analyze(principal_for("ws-1"), articles=["第一篇文章内容。", "第二篇文章内容。"], form="blog")
    fetched = await service.get_report(principal_for("ws-1"), report["report_id"])
    assert fetched is not None and fetched["report_id"] == report["report_id"]
    assert await service.get_report(principal_for("ws-1"), "00000000-0000-0000-0000-000000000000") is None
    assert len(provider.calls) == 1  # reads never spend model calls


# ---------------------------------------------------------------------
# §3-D4: corpus provenance is captured at analyze time
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_persists_corpus_stats_and_articles():
    service, store, _ = make_service()
    articles = ["第一篇标题行\n完整内容若干字。", "第二篇另一篇内容。"]
    report = await service.analyze(principal_for("ws-1"), articles=articles, form="blog")
    assert report["corpus_stats"] == {"article_count": 2, "total_chars": sum(len(a) for a in articles)}
    arts = report["corpus_articles"]
    assert len(arts) == 2
    assert arts[0]["index"] == 1 and arts[1]["index"] == 2
    assert arts[0]["title"] == "第一篇标题行"  # first line is the label
    assert arts[0]["excerpt"] == articles[0][:80]
    assert arts[0]["char_count"] == len(articles[0])


@pytest.mark.asyncio
async def test_provenance_excerpt_never_exceeds_80_chars():
    long_article = "很长的一行没有换行。" + "x" * 500
    service, _, _ = make_service()
    report = await service.analyze(
        principal_for("ws-1"), articles=[long_article, "第二篇内容。"], form="blog"
    )
    for article in report["corpus_articles"]:
        assert len(article["excerpt"]) <= 80
        assert article["char_count"] == len(long_article) or article["char_count"] == len("第二篇内容。")
