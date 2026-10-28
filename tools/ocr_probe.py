"""OCR 每本 PDF 的第一页，确认书名。"""
from pathlib import Path

import pymupdf
from rapidocr_onnxruntime import RapidOCR

d = Path(r"E:\huan cun\microbe-analyzer\knowledge\books")
engine = RapidOCR()

for f in sorted(d.glob("*.pdf")):
    doc = pymupdf.open(f)
    page = doc[0]
    txt = page.get_text().strip()

    if len(txt) > 80:
        print(f"\n=== {f.name} ===")
        print("  （有文字层，直接读）")
        print(" ", txt[:160].replace("\n", " "))
        doc.close()
        continue

    # 扫描件：渲染成图再 OCR
    pix = page.get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0))
    png = pix.tobytes("png")
    result, _ = engine(png)
    lines = [r[1] for r in result] if result else []
    print(f"\n=== {f.name} ===")
    print("  （扫描件，OCR 结果）")
    print(" ", " / ".join(lines[:6])[:200])
    doc.close()
