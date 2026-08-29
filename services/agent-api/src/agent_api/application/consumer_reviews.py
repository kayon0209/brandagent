"""Consumer review mapper (upgrade plan task 11, step 3).

Deterministic, spoken-language templates for the C-end pre-publish
review. Machine dimensions map to a small fixed vocabulary; the raw
machine messages NEVER surface in the UI text. Blocking is reserved
for exactly three cases:

1. unsupported factual claims,
2. explicit compliance prohibitions,
3. export snapshot not matching the currently adopted master.
"""

from __future__ import annotations


class ConsumerReviewMapper:
    """Map machine review rows to conversational review bubbles."""

    # spoken templates per machine dimension (fallback: generic hint)
    _TEMPLATES = {
        "factual": "这句话里的说法我们找不到来源，建议删掉或改成你素材里有的。",
        "citation": "这里的出处再核对一下会更可信。",
        "brand": "这个说法可能不太像你平时的口吻，看看要不要顺一下。",
        "channel_format": "这段对这个平台来说有点长，读起来可能不够顺。",
        "compliance": "这里有平台不允许的说法，发出去可能有风险。",
    }

    _BLOCKING_DIMENSIONS = ("factual", "compliance")

    def map_bubbles(
        self,
        reviews: list[dict],
        *,
        master_snapshot_hash: str,
        export_snapshot_hash: str,
    ) -> list[dict]:
        bubbles: list[dict] = []
        for item in reviews:
            if item.get("passed"):
                continue
            dimension = str(item.get("dimension", ""))
            severity = str(item.get("severity", "warning"))
            text = self._TEMPLATES.get(dimension, "这里可以再检查一遍。")
            is_blocking = dimension in self._BLOCKING_DIMENSIONS and severity == "critical"
            bubbles.append({"kind": "blocking" if is_blocking else "needs_fix", "text": text})
        if master_snapshot_hash != export_snapshot_hash:
            bubbles.append(
                {"kind": "blocking", "text": "你最近采用了新版稿，这个预览还是旧的，建议重新生成最新版。"}
            )
        return bubbles

    def summarize(
        self,
        reviews: list[dict],
        *,
        master_snapshot_hash: str,
        export_snapshot_hash: str,
    ) -> dict:
        bubbles = self.map_bubbles(
            reviews,
            master_snapshot_hash=master_snapshot_hash,
            export_snapshot_hash=export_snapshot_hash,
        )
        blocking = [bubble for bubble in bubbles if bubble["kind"] == "blocking"]
        if not bubbles:
            return {
                "empty": True,
                "headline": "暂未发现需要你确认的地方。",
                "blocking_count": 0,
            }
        if blocking:
            headline = f"有 {len(blocking)} 处建议发布前处理，不处理也可以预览。"
        else:
            headline = f"有 {len(bubbles)} 处小提示，都不影响发布。"
        return {"empty": False, "headline": headline, "blocking_count": len(blocking)}
