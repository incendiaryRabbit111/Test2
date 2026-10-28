"""只用指定的几本书构建索引（跳过尚未 OCR 完的大部头）。

用法：
    .venv\\Scripts\\python.exe tools\\build_index_subset.py biological_phase sbi_paper
不带参数则使用默认的两本。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import build_knowledge as bk  # noqa: E402

DEFAULT = ["biological_phase", "sbi_paper"]


def main() -> int:
    wanted = sys.argv[1:] or DEFAULT
    print(f"只索引：{wanted}\n")

    chunks: list[dict] = []
    used_books: list[dict] = []
    for book in bk.BOOKS:
        if book["slug"] not in wanted:
            continue
        raw = bk.RAW_DIR / f"{book['slug']}.jsonl"
        if not raw.exists():
            print(f"{book['title']}: 还没有 raw，先抽取/OCR…")
            bk.build_book(book, 4, 2.0, False)
        pages = 0
        if raw.exists():
            with raw.open(encoding="utf-8") as fh:
                pages = sum(1 for line in fh if line.strip())
        book_chunks = bk.chunk_book(book)
        print(f"{book['title']}: {pages} 页 -> {len(book_chunks)} 块")
        if book_chunks:
            used_books.append(book)
            chunks.extend(book_chunks)

    if not chunks:
        print("\n没有生成任何文本块，检查 knowledge/raw/ 是否有对应 jsonl")
        return 1

    bk.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n共 {len(chunks)} 块，构建 BM25 索引…")
    bk.build_index(chunks)

    manifest = {"books": used_books, "chunks": len(chunks)}
    (bk.INDEX_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"完成：{bk.INDEX_DIR / 'bm25.pkl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
