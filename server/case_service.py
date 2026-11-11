"""用户点赞过的分析结果，作为内部历史案例检索（不是文献）。

设计原则：
- 只有用户点赞、报告非空、真实 AI 成功的结果才进入案例库；
- 案例索引是派生数据，可随时从 history.db 重建；
- 历史案例只在提示词里作为“经验”使用，不向客户端展示引用；
- 点赞撤销/删除历史后，案例立即从索引移除。
"""
from __future__ import annotations

import hashlib
import logging
import threading

from app import rag

logger = logging.getLogger("microbe.api.cases")

MAX_CASES = 300


def report_hash(report: str) -> str:
    return hashlib.sha256((report or "").encode("utf-8")).hexdigest()[:24]


def _fmt(value, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


class CaseService:
    def __init__(self) -> None:
        self.history = None
        self.cases: list[dict] = []
        self.bm25 = None
        self._lock = threading.Lock()

    def attach(self, history) -> None:
        self.history = history
        self.reload()

    def reload(self) -> None:
        with self._lock:
            if self.history is None:
                self.cases = []
                self.bm25 = None
                return
            records = self.history.liked_records()
            cases: list[dict] = []
            for rec in records[-MAX_CASES:]:
                if not rec.report or not rec.species:
                    continue
                if rec.analysis_source in ("错误", "本地模拟"):
                    continue
                feedback = self.history.get_feedback(rec.id or 0)
                if not feedback or feedback.get("verdict") != "up":
                    continue
                # 重新分析后报告变了，旧点赞自动失效，避免拿旧结论当案例。
                if feedback.get("report_hash") != report_hash(rec.report):
                    continue
                cases.append(self._make_case(rec))
            self.cases = cases
            self.bm25 = None
            if cases:
                from rank_bm25 import BM25Plus

                corpus = [rag.tokenize(case["text"]) for case in cases]
                if any(corpus):
                    # BM25Okapi 在只有一两条案例时 IDF 可能为负；
                    # BM25Plus 对小案例库更稳定。
                    self.bm25 = BM25Plus(corpus)

    def _make_case(self, rec) -> dict:
        metrics = rec.metrics or {}
        dominant = "、".join(metrics.get("dominant") or []) or "无"
        changed = sorted(
            [c for c in (rec.changes or []) if c.get("pct") is not None],
            key=lambda c: abs(float(c.get("pct") or 0)),
            reverse=True,
        )[:6]
        change_text = "；".join(
            f"{c.get('species')} {c.get('text')}" for c in changed
        ) or "无"
        trend_text = "、".join(
            str(t.get("rule") or "") for t in (rec.trends or [])
        ) or "无"
        report = " ".join((rec.report or "").split())
        if len(report) > 500:
            report = report[:500] + "…"
        text = (
            f"时间：{rec.sample_time or '无时间'}；"
            f"物种数：{metrics.get('species_count', rec.species_count)}；"
            f"H'：{_fmt(metrics.get('shannon_h', rec.shannon_h), 3)}；"
            f"总浓度：{_fmt(metrics.get('total', rec.total), 3)}；"
            f"优势种：{dominant}；"
            f"关键变化：{change_text}；"
            f"趋势：{trend_text}；"
            f"AI结论：{report}"
        )
        return {
            "record_id": rec.id,
            "sample_time": rec.sample_time,
            "text": text,
            "report": report,
        }

    def search(self, query: str, top_k: int = 3, exclude_ids: set[int] | None = None) -> list[dict]:
        exclude_ids = exclude_ids or set()
        with self._lock:
            cases = list(self.cases)
            bm25 = self.bm25
        if not cases or bm25 is None or not query.strip():
            return []
        tokens = rag.tokenize(query)
        if not tokens:
            return []
        scores = bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda kv: kv[1], reverse=True)
        hits: list[dict] = []
        for idx, score in ranked:
            if score <= 0:
                break
            case = cases[idx]
            if case.get("record_id") in exclude_ids:
                continue
            hits.append(case)
            if len(hits) >= top_k:
                break
        return hits

    @staticmethod
    def format_context(hits: list[dict]) -> str:
        if not hits:
            return ""
        lines = ["【历史相似案例（用户认可的经验，不是文献）】"]
        for index, case in enumerate(hits, 1):
            lines.append(
                f"[H{index}] {case.get('sample_time') or '无时间'}："
                f"{case.get('text', '')}"
            )
        lines.append(
            "请把这些案例作为经验参考，不要照抄；"
            "如果与本次数据矛盾，以本次数据为准。"
        )
        return "\n".join(lines)

    def context_for_payload(self, payload: dict, exclude_ids: set[int] | None = None) -> str:
        query = rag.build_query(payload)
        hits = self.search(query, top_k=3, exclude_ids=exclude_ids)
        return self.format_context(hits)


case_service = CaseService()
