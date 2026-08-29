"""Build consumer_golden_v1.jsonl (upgrade plan task 14).

Generates the planned minimum dataset (15 x 6 actions + 10 refusals +
10 stale/conflict engineering cases) from SYNTHETIC templates only — no
production material is ever embedded. Outputs are deterministic baseline
references so the gate is computable offline.
"""

from __future__ import annotations

import json
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "evaluation" / "consumer_golden_v1.jsonl"
DATASET_VERSION = "consumer_golden_v1"

CORE_IDEAS = [
    "把复杂的方法讲成普通人能上手的步骤",
    "用真实场景代替空泛的形容词",
    "让读者在三句话内知道能获得什么",
    "把长内容拆成可随手完成的小动作",
    "强调选择权始终在读者手里",
    "用提问开头代替结论开头",
    "把专业术语翻译成生活语言",
    "承认局限比夸大效果更可信",
    "结构服务于阅读节奏而不是炫技",
    "结尾给出一个立刻能做的小事",
    "数据要配场景才有说服力",
    "删除一切不推进观点的句子",
    "对比是最高效的解释方式",
    "例子要具体到能想象画面",
    "语气平等，不端着",
]

SELECTED_TEXTS = [
    "这个方法可以帮助你显著提升效率并且节省大量时间。",
    "很多人在第一步就放弃了，因为说明实在太长。",
    "我们需要更多的时间来验证这个观点是否成立。",
    "这份报告的结论其实非常简单，就是坚持做下去。",
    "把内容写得短一点，读者反而更愿意读完。",
    "工具不能替代判断，但能减少无谓的重复。",
    "每次只改一个变量，观察结果的变化。",
    "先完成，再完美，这个顺序不能颠倒。",
    "好的标题不是标题党，而是准确加上一点好奇。",
    "把结论放在开头，读者才知道要不要继续。",
    "素材越具体，论证越省力。",
    "沉默的证据往往比热闹的成功学更有价值。",
    "先写给一个人看，再写给所有人看。",
    "记录比记忆可靠，复盘比记录可靠。",
    "简单不等于偷懒，而是删到只剩必要。",
]


def suggestion_case(index: int, action: str) -> dict:
    selected = SELECTED_TEXTS[index % len(SELECTED_TEXTS)]
    idea = CORE_IDEAS[index % len(CORE_IDEAS)]
    if action == "expand":
        content = f"{idea}。{selected}"
    elif action == "replace_example":
        content = f"{idea}。换个说法：{selected[:10]}…"
    else:  # shorten
        content = idea[:8]  # strictly shorter than the selected sentence
    return {
        "dataset_version": DATASET_VERSION,
        "case_id": f"suggestion-{action}-{index:03d}",
        "kind": "suggestion",
        "input": {"action": action, "selected_text": selected, "block_id": f"b{index % 3 + 1}", "base_revision": index},
        "output": {"content": content, "supportingExcerptIds": [f"ex-{index % 5:02d}"]},
        "expected_constraints": {
            "core_idea": idea,
            "source_texts": [f"素材原文 {index % 5:02d}：{idea}。"],
        },
        "source_excerpt_ids": [f"ex-{index % 5:02d}"],
    }


def channel_case(index: int, channel: str) -> dict:
    idea = "把复杂的方法讲成普通人能上手的步骤"
    if channel == "wechat_website":
        content = f"第一段：{idea}。\n第二段：给出立刻能做的小事。"
        fmt = "wechat_paragraphs"
    elif channel == "xiaohongshu":
        content = f"{idea}，一句话讲清。 #方法 #上手"
        fmt = "xiaohongshu_tags"
    else:  # video_script_60s
        content = f"开场口播：{idea}。\n核心卖点：三步讲完。"
        fmt = "video_script_lines"
    return {
        "dataset_version": DATASET_VERSION,
        "case_id": f"channel-{channel}-{index:03d}",
        "kind": "channel",
        "input": {"channel": channel, "master_content": "母稿：核心观点与素材。"},
        "output": {"content": content, "supportingExcerptIds": [f"ex-{index % 5:02d}"]},
        "expected_constraints": {
            "core_idea": idea,
            "channel_format": fmt,
            "source_texts": [f"素材原文：{idea}"],
        },
        "source_excerpt_ids": [f"ex-{index % 5:02d}"],
    }


def refusal_case(index: int) -> dict:
    return {
        "dataset_version": DATASET_VERSION,
        "case_id": f"refusal-{index:03d}",
        "kind": "refusal",
        "input": {
            "action": "expand",
            "selected_text": SELECTED_TEXTS[index % len(SELECTED_TEXTS)],
            "block_id": "b1",
            "base_revision": index,
        },
        "output": {"content": "", "supportingExcerptIds": [], "refused": True, "reason": "SUGGESTION_REFUSED"},
        "expected_constraints": {
            "core_idea": CORE_IDEAS[index % len(CORE_IDEAS)],
            "must_refuse": True,
            "source_texts": ["素材原文：不含任何数字。"],
        },
        "source_excerpt_ids": [],
    }


def stale_case(index: int) -> dict:
    return {
        "dataset_version": DATASET_VERSION,
        "case_id": f"engineering-stale-{index:03d}",
        "kind": "engineering",
        "input": {
            "action": "shorten",
            "selected_text": SELECTED_TEXTS[index % len(SELECTED_TEXTS)],
            "block_id": "b1",
            "base_revision": index,
        },
        "output": {"content": "", "supportingExcerptIds": [], "conflict": "SELECTION_STALE", "draft_unchanged": True},
        "expected_constraints": {
            "core_idea": CORE_IDEAS[index % len(CORE_IDEAS)],
            "must_keep_draft": True,
            "source_texts": ["素材原文：任何内容。"],
        },
        "source_excerpt_ids": [],
    }


def build() -> list[dict]:
    cases: list[dict] = []
    for action in ("expand", "replace_example", "shorten"):
        cases.extend(suggestion_case(i, action) for i in range(15))
    cases.extend(channel_case(i, "wechat_website") for i in range(15))
    cases.extend(channel_case(i, "xiaohongshu") for i in range(15))
    cases.extend(channel_case(i, "video_script_60s") for i in range(15))
    cases.extend(refusal_case(i) for i in range(10))
    cases.extend(stale_case(i) for i in range(10))
    return cases


def main() -> None:
    cases = build()
    target = TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"wrote {len(cases)} cases to {target}")


if __name__ == "__main__":
    main()
