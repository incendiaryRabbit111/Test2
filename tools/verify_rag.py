"""验证 RAG 检索效果（不调用 AI）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.rag import KnowledgeBase  # noqa: E402

QUERIES = [
    "表壳虫 污泥龄",
    "钟虫 溶解氧 出水",
    "轮虫 污泥解体",
    "楯纤虫 负荷",
    "活性污泥 生物相 指示",
]

kb = KnowledgeBase()
print(f"索引可用: {kb.available}")
print(f"索引路径: {kb.path}")
print(f"文本块数: {len(kb.chunks)}")
if kb.chunks:
    books = {}
    for c in kb.chunks:
        books[c["book"]] = books.get(c["book"], 0) + 1
    print("按书分布:", books)
print()

for q in QUERIES:
    refs = kb.search(q, top_k=3)
    print(f"【{q}】命中 {len(refs)} 条")
    for r in refs:
        snippet = r.text.replace("\n", " ")[:90]
        print(f"   {r.label} 《{r.book}》 第{r.page_start}-{r.page_end}页")
        print(f"      {snippet}")
    print()
