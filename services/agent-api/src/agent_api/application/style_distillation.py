"""Author style distillation (round-3 UX feature, six layers).

The premise (user-specified): letting an agent imitate a voice from a few
sample texts directly produces distorted copies. Instead, this service
analyzes a CORPUS of complete articles and distills the style into
REUSABLE RULES; later writing is guided by the rules, not by imitation.

Six layers:
  L1 surface language (diction, syntax, punctuation, rhythm)  -> 语言 DNA
  L2 article structure (hook / development / turn / close)    -> 结构模板
  L3 topic logic (what to write about, entry angles)          -> 选题逻辑
  L4 evidence strategy (sources, cases, data usage)           -> 素材策略
  L5 cognitive frame (worldview, value calls, assumptions)    -> 认知框架
  L6 visual style (imagery, layout, type hierarchy, color)    -> 视觉指南

L1-L2 answer "how to write", L3-L5 answer "how to think", L6 answers
"how to present" — all three together are a complete style reproduction.

Language separation: the language of the distilled RULE FILE follows the
dominant language of the corpus (CJK ratio), unless the user explicitly
requests an output language; conversation copy stays neutral.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from agent_api.api.security import Principal
from agent_api.providers.base import ModelCallResult

SUPPORTED_FORMS = ("long_form", "wechat_article", "blog", "newsletter", "xiaohongshu_note")
MIN_CORPUS_ARTICLES = 2
MAX_CORPUS_ARTICLES = 20
MAX_CORPUS_CHARACTERS = 120_000

_PROMPT_VERSION = "style-distillation:v1"

_LAYER_KEYS = ("l1_language_dna", "l2_structure_template", "l3_topic_logic", "l4_evidence_strategy", "l5_cognitive_frame", "l6_visual_guide")

_LAYER_BRIEFS = {
    "zh": {
        "l1_language_dna": "L1 表层语言：用词习惯（口语/书面/行业词）、句式长短与节奏、标点风格、段落呼吸感。给出可直接执行的规则（如「句子平均长度 X 字；每段不超过 Y 句」），并给 3 个正例与 2 个反例。",
        "l2_structure_template": "L2 文章结构：典型开头 hook 的类型、展开顺序、转折手法、收束方式。输出一个可复用的结构骨架（分节描述每节的职责与占比）。",
        "l3_topic_logic": "L3 选题逻辑：这位作者选什么话题、避开什么、常用切入角度。给出选题三问（写给谁/解决什么/为何是我）在此风格下的答案。",
        "l4_evidence_strategy": "L4 素材策略：引用来源偏好（数据/案例/轶事）、案例如何使用（开头抛出/中途佐证）、数据出现密度与呈现方式。",
        "l5_cognitive_frame": "L5 认知框架：世界观与核心假设、价值判断的倾向（如务实/理想/怀疑）、常隐含未言明的前提。这是「怎么想」的层。",
        "l6_visual_guide": "L6 视觉风格：配图风格与密度、排版层级（标题/正文/强调）、字体层级与色彩倾向（若语料可推断；不可推断则明确说无法推断，不要编造）。",
    },
    "en": {
        "l1_language_dna": "L1 Surface language: diction habits, sentence length rhythm, punctuation style, paragraph breathing. Give executable rules (e.g. 'average sentence X words; paragraphs <= Y sentences') with 3 positive and 2 negative examples.",
        "l2_structure_template": "L2 Article structure: hook type, development order, turn techniques, closing move. Output a reusable structural skeleton (per-section duty and share).",
        "l3_topic_logic": "L3 Topic logic: what this author writes about, what they avoid, recurring entry angles. Answer the three selection questions in this voice.",
        "l4_evidence_strategy": "L4 Evidence strategy: preferred sources (data/case/anecdote), how cases are deployed, data density and presentation.",
        "l5_cognitive_frame": "L5 Cognitive frame: worldview, value calls, unstated assumptions — the 'how to think' layer.",
        "l6_visual_guide": "L6 Visual style: imagery density, layout hierarchy, type scale, color tendency (state clearly if not inferable — never fabricate).",
    },
}


class StyleReportStore(Protocol):
    async def insert_style_report(
        self,
        workspace_id: str,
        form: str,
        language: str,
        layers: dict,
        corpus_digest: str,
        *,
        corpus_stats: dict | None = None,
        corpus_articles: list[dict] | None = None,
    ) -> dict: ...
    async def list_style_reports(self, workspace_id: str) -> list[dict]: ...
    async def find_by_digest(self, workspace_id: str, form: str, language: str, corpus_digest: str) -> dict | None: ...
    async def get_style_report(self, workspace_id: str, report_id: str) -> dict | None: ...


class StyleAnalysisProvider(Protocol):
    async def generate(self, *, system: str, prompt: str, prompt_version: str) -> ModelCallResult: ...


class StyleDistillationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def detect_language(text: str) -> str:
    """Dominant language of the corpus: CJK share >= 30% -> zh, else en."""
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]", text))
    total = max(len(text), 1)
    return "zh" if cjk / total >= 0.30 else "en"


def _corpus_digest(articles: list[str]) -> str:
    import hashlib

    joined = "\n\u241e\n".join(articles)
    return hashlib.sha256(f"style-corpus:v1:{len(articles)}:{joined}".encode("utf8")).hexdigest()


def _article_title(article: str) -> str:
    """First line, or first 12 chars of the first sentence — the archive's
    per-article label. Pure display derivation from the corpus itself."""
    first_line = article.splitlines()[0].strip() if article.strip() else ""
    if not first_line:
        first_line = article.strip()[:12]
    return first_line[:40]


def _corpus_provenance(clean: list[str]) -> tuple[dict, list[dict]]:
    """§3-D4: per-article metadata + aggregate stats for the archive view.
    Derived from the corpus at analyze time; nothing is invented."""
    corpus_articles = [
        {
            "index": index,
            "title": _article_title(article),
            "excerpt": article[:80],
            "char_count": len(article),
        }
        for index, article in enumerate(clean, start=1)
    ]
    corpus_stats = {
        "article_count": len(clean),
        "total_chars": sum(len(article) for article in clean),
    }
    return corpus_stats, corpus_articles


class StyleDistillationService:
    def __init__(self, *, store: StyleReportStore, provider: StyleAnalysisProvider) -> None:
        self._store = store
        self._provider = provider

    def prepare(
        self, *, articles: list[str], form: str, output_language: str | None
    ) -> tuple[list[str], str, str]:
        """Shared normalization for BOTH the digest short-circuit (route)
        and the analysis path — one canonical clean -> language -> digest
        pipeline so the two can never disagree on what 'the same corpus'
        means (P0-A).

        Returns (clean_articles, corpus_digest, language). Raises the
        same corpus/form errors as analyze.
        """
        if form not in SUPPORTED_FORMS:
            raise StyleDistillationError("STYLE_FORM_UNSUPPORTED", f"不支持的文章形态：{form}")
        clean = [article.strip() for article in articles if article and article.strip()]
        if len(clean) < MIN_CORPUS_ARTICLES:
            raise StyleDistillationError("STYLE_CORPUS_TOO_SMALL", "风格蒸馏需要至少 2 篇完整文章——单篇模仿正是会失真的做法")
        if len(clean) > MAX_CORPUS_ARTICLES:
            raise StyleDistillationError("STYLE_CORPUS_TOO_LARGE", f"一次最多分析 {MAX_CORPUS_ARTICLES} 篇")
        total = sum(len(article) for article in clean)
        if total > MAX_CORPUS_CHARACTERS:
            raise StyleDistillationError("STYLE_CORPUS_TOO_LARGE", f"语料总长超过 {MAX_CORPUS_CHARACTERS} 字，请分批分析")
        language = output_language if output_language in ("zh", "en") else detect_language("\n".join(clean))
        return clean, _corpus_digest(clean), language

    async def find_existing_report(
        self, principal: Principal, *, form: str, language: str, corpus_digest: str
    ) -> dict | None:
        """P0-A short-circuit lookup: same corpus (same form + language +
        digest) already distilled for this workspace -> return it WITHOUT
        spending another model call."""
        return await self._store.find_by_digest(principal.workspace_id, form, language, corpus_digest)

    async def get_report(self, principal: Principal, report_id: str) -> dict | None:
        """P0-B: one report by id, workspace-scoped via the store's RLS."""
        return await self._store.get_style_report(principal.workspace_id, report_id)

    async def analyze(
        self,
        principal: Principal,
        *,
        articles: list[str],
        form: str,
        output_language: str | None = None,
        usage_out: dict | None = None,
    ) -> dict:
        clean, _digest, language = self.prepare(articles=articles, form=form, output_language=output_language)
        briefs = _LAYER_BRIEFS[language]
        total = sum(len(article) for article in clean)

        # one structured pass: all six layers in a single JSON response keeps
        # the analysis consistent across layers (they reference each other)
        system = (
            "你是一位严谨的风格分析师。用户给出同一作者的多篇完整文章，你把其风格蒸馏为六层可复用规则。"
            "只依据语料中真实存在的证据，不可推断的层（如视觉风格）就写明无法推断。"
            "输出一个 JSON 对象（不要 markdown 代码块），键为 "
            "l1_language_dna, l2_structure_template, l3_topic_logic, l4_evidence_strategy, "
            "l5_cognitive_frame, l6_visual_guide，每层为一个对象，包含 rules(字符串数组) 与 summary(一句话)。"
            if language == "zh"
            else "You are a rigorous style analyst. Given multiple complete articles by one author, distill the style into six reusable layers of rules. "
            "Ground every rule in evidence from the corpus; state clearly when a layer (e.g. visual style) is not inferable. "
            "Output ONE JSON object (no markdown fence) with keys "
            "l1_language_dna, l2_structure_template, l3_topic_logic, l4_evidence_strategy, "
            "l5_cognitive_frame, l6_visual_guide; each an object with rules (array of strings) and summary (one sentence)."
        )
        prompt = (
            f"文章形态：{form}\n语料共 {len(clean)} 篇、约 {total} 字。\n\n"
            + "\n\n".join(f"【第 {index} 篇】\n{article}" for index, article in enumerate(clean, start=1))
            + "\n\n六层蒸馏要求：\n"
            + "\n".join(f"- {key}: {brief}" for key, brief in briefs.items())
        )

        result = await self._provider.generate(system=system, prompt=prompt, prompt_version=_PROMPT_VERSION)
        if usage_out is not None:
            usage_out.update(
                {
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "model": result.model,
                    "model_executed": True,
                }
            )

        layers = self._parse_layers(result.content, language)
        corpus_stats, corpus_articles = _corpus_provenance(clean)
        return await self._store.insert_style_report(
            principal.workspace_id,
            form,
            language,
            layers,
            _digest,
            corpus_stats=corpus_stats,
            corpus_articles=corpus_articles,
        )

    def _parse_layers(self, raw: str, language: str) -> dict:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as error:
            raise StyleDistillationError("STYLE_ANALYSIS_UNPARSEABLE", "风格分析结果无法解析；本次模型调用已计费，请重试一次。") from error
        layers: dict = {}
        for key in _LAYER_KEYS:
            layer = parsed.get(key)
            if not isinstance(layer, dict):
                layer = {"rules": [], "summary": ""}
            rules = [str(rule) for rule in layer.get("rules", []) if str(rule).strip()]
            summary = str(layer.get("summary", "")).strip()
            if not rules and not summary:
                # an uninferable layer is honest emptiness with a note —
                # the note follows the RULE-FILE language (the corpus's),
                # never the model's JSON scaffolding language
                summary = (
                    "依据语料无法推断该层，未生成规则。"
                    if language == "zh"
                    else "Not inferable from this corpus; no rules generated."
                )
            layers[key] = {"rules": rules, "summary": summary}
        return layers

    async def list_reports(self, principal: Principal) -> list[dict]:
        return await self._store.list_style_reports(principal.workspace_id)
