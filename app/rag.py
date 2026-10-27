"""本地知识库检索（RAG）。

索引由 tools/build_knowledge.py 生成：BM25 + 文本块（带书名、页码）。
离线可用，不依赖外部 embedding 服务。
"""
from __future__ import annotations

import pickle
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "knowledge" / "index" / "bm25.pkl"

STOPWORDS = set(
    "的 了 和 与 及 或 是 在 有 为 对 也 就 都 而 其 之 以 于 中 上 下 "
    "我们 可以 进行 通过 如图 所示 表 图 第 页".split()
)
DOMAIN_WORDS = [
    "活性污泥", "微型动物", "污泥生物指数", "生物相", "指示生物",
    "楯纤虫", "钟虫", "轮虫", "累枝虫", "盖纤虫", "表壳虫", "内管虫",
    "扭曲管叶虫", "摩门虫", "斜管虫", "袋鞭虫", "匣壳虫", "线虫", "漫游虫",
    "草履虫", "变形虫", "丝状菌", "污泥膨胀", "泡沫", "溶解氧", "污泥龄",
    "原生动物", "后生动物", "纤毛虫", "鞭毛虫", "固着", "游泳",
]

_JIEBA_READY = False


def _ensure_jieba() -> None:
    global _JIEBA_READY
    if _JIEBA_READY:
        return
    import jieba

    for word in DOMAIN_WORDS:
        jieba.add_word(word)
    _JIEBA_READY = True


def tokenize(text: str) -> list[str]:
    _ensure_jieba()
    import jieba

    tokens = []
    for tok in jieba.lcut(text):
        tok = tok.strip().lower()
        if not tok or tok in STOPWORDS:
            continue
        if re.fullmatch(r"[\W_]+", tok):
            continue
        tokens.append(tok)
    return tokens


@dataclass
class Reference:
    label: str
    book: str
    author: str
    page_start: int
    page_end: int
    text: str
    score: float = 0.0
    cited: bool = field(default=False)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "book": self.book,
            "author": self.author,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "text": self.text,
            "score": round(self.score, 4),
            "cited": self.cited,
        }


class KnowledgeBase:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or INDEX_PATH)
        self.chunks: list[dict] = []
        self.bm25 = None
        self.available = False
        if self.path.exists():
            try:
                with self.path.open("rb") as fh:
                    data = pickle.load(fh)
                self.bm25 = data["bm25"]
                self.chunks = data["chunks"]
                self.available = bool(self.chunks)
            except Exception:
                self.bm25 = None
                self.chunks = []
                self.available = False

    def search(self, query: str, top_k: int = 6, min_score: float = 0.0) -> list[Reference]:
        if not self.available or not query.strip():
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda kv: kv[1], reverse=True)
        refs: list[Reference] = []
        for idx, score in ranked:
            if score <= min_score:
                break
            chunk = self.chunks[idx]
            if self._is_low_value(chunk["text"]):
                continue
            refs.append(
                Reference(
                    label=f"R{len(refs) + 1}",
                    book=chunk["book"],
                    author=chunk.get("author", ""),
                    page_start=chunk["page_start"],
                    page_end=chunk["page_end"],
                    text=self._snippet(chunk["text"], tokens),
                    score=float(score),
                )
            )
            if len(refs) >= top_k:
                break
        return refs

    @staticmethod
    def _is_low_value(text: str) -> bool:
        """过滤目录页/索引页：大量「(1)」编号或连续点线，信息密度低。"""
        if len(re.findall(r"[（(]\d{1,3}[）)]", text)) >= 8:
            return True
        if len(re.findall(r"\.{4,}|…{4,}", text)) >= 4:
            return True
        return False

    @staticmethod
    def _snippet(text: str, tokens: list[str], radius: int = 180) -> str:
        lowered = text.lower()
        pos = -1
        for tok in tokens:
            idx = lowered.find(tok.lower())
            if idx >= 0 and (pos < 0 or idx < pos):
                pos = idx
        if pos < 0:
            return text[: radius * 2]
        start = max(0, pos - radius)
        end = min(len(text), pos + radius)
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(text) else ""
        return prefix + text[start:end] + suffix


def build_query(payload: dict) -> str:
    """根据本次检测数据生成检索词：重点物种 + 趋势 + 固定领域词。"""
    parts: list[str] = []
    rows = payload.get("rows") or []
    ranked = sorted(
        rows,
        key=lambda r: (r.get("absolute", False), r.get("dominant", False), r.get("percent", 0)),
        reverse=True,
    )
    for row in ranked[:10]:
        name = str(row.get("name", "")).strip()
        if name:
            parts.extend([name, name])
    for hit in payload.get("trends") or []:
        parts.append(str(hit.get("rule", "")))
        parts.append(str(hit.get("detail", "")))
    parts.extend(
        [
            "活性污泥", "生物相诊断", "指示生物", "微型动物", "污泥生物指数",
            "溶解氧", "污泥膨胀", "污泥龄", "优势种群", "多样性指数",
        ]
    )
    return " ".join(p for p in parts if p)


def format_context(refs: list[Reference]) -> str:
    if not refs:
        return "（本次没有检索到可用的参考资料）"
    lines = []
    for ref in refs:
        pages = (
            f"第{ref.page_start}页"
            if ref.page_start == ref.page_end
            else f"第{ref.page_start}-{ref.page_end}页"
        )
        lines.append(
            f"[{ref.label}] 《{ref.book}》{pages}：{ref.text}"
        )
    return "\n\n".join(lines)


def mark_cited(refs: list[Reference], *texts: str) -> None:
    joined = "\n".join(t or "" for t in texts)
    cited = set(re.findall(r"\[(R\d+)\]", joined))
    for ref in refs:
        ref.cited = ref.label in cited
