"""探测 PDF 是否有文字层（文字版 vs 扫描件）。"""
from pathlib import Path

import pymupdf

d = Path(__file__).resolve().parent.parent / "knowledge" / "books"
files = sorted(d.glob("*.pdf"))
print(f"找到 {len(files)} 个 PDF\n")

for f in files:
    try:
        doc = pymupdf.open(f)
        n = doc.page_count
        sample = []
        for i in [0, n // 2, n - 1] if n >= 3 else range(n):
            txt = doc[i].get_text().strip()
            sample.append(len(txt))
        # 再抽一页看看实际内容
        first = doc[0].get_text().strip().replace("\n", " ")[:60]
        print(f"{f.name}")
        print(f"   页数 {n} | 抽样页字符数 {sample} | 大小 {f.stat().st_size/1024/1024:.1f} MB")
        print(f"   首行：{first!r}")
        doc.close()
    except Exception as exc:
        print(f"{f.name}  ❌ {type(exc).__name__}: {exc}")
