"""统计每本 PDF 里「有文字层」的页数——判断能否跳过 OCR 直接抽文本。"""
from pathlib import Path

import pymupdf

BOOKS_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "books"

for f in sorted(BOOKS_DIR.glob("*.pdf")):
    doc = pymupdf.open(f)
    with_text, chars, empty = [], 0, 0
    for i in range(doc.page_count):
        t = doc[i].get_text().strip()
        if len(t) >= 50:
            with_text.append(i + 1)
            chars += len(t)
        else:
            empty += 1

    print(f"\n=== {f.name} ===")
    print(f"  总页数 {doc.page_count}｜有文字层 {len(with_text)} 页｜无文字 {empty} 页")
    print(f"  文字总字符 {chars:,}")
    if with_text:
        pct = len(with_text) / doc.page_count * 100
        print(f"  文字页占比 {pct:.1f}%")
        print(f"  前 20 个有文字的页码：{with_text[:20]}")
        s = doc[with_text[0] - 1].get_text().strip().replace("\n", " ")
        print(f"  样例（第 {with_text[0]} 页）：{s[:130]}")
    doc.close()
