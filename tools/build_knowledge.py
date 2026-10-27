"""构建本地知识库：PDF -> 文本/OCR -> 切块 -> BM25 索引。

用法（项目根目录下）：
    .venv\\Scripts\\python.exe tools\\build_knowledge.py --workers 8

扫描版按页 OCR；有文字层的页面直接抽文本。
结果写入 knowledge/raw/<slug>.jsonl 与 knowledge/index/，
这两个目录都在 .gitignore 中，不会提交原文。
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import pickle
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOK_DIR = ROOT / "knowledge" / "books"
RAW_DIR = ROOT / "knowledge" / "raw"
INDEX_DIR = ROOT / "knowledge" / "index"

BOOKS = [
    {
        "slug": "biological_phase",
        "title": "污水处理的生物相诊断",
        "author": "株式会社西原环境",
        "publisher": "化学工业出版社",
        "isbn": "9787122144096",
        "pdf": "污水处理的生物相诊断.pdf",
    },
    {
        "slug": "environmental_microbiology",
        "title": "环境工程微生物学",
        "author": "周群英、王士芬",
        "publisher": "高等教育出版社",
        "isbn": "9787040222654",
        "pdf": "环境工程微生物学.pdf",
    },
    {
        "slug": "sbi_paper",
        "title": "用污泥生物指数评价活性污泥的运转效能",
        "author": "周可新等",
        "publisher": "环境污染治理技术与设备, 2005(9)",
        "isbn": "",
        "pdf": "SBI论文_周可新_2005.pdf",
    },
]

_ocr_engine = None
_doc = None
_zoom = 2.0


def _init_worker(pdf_path: str, zoom: float) -> None:
    global _ocr_engine, _doc, _zoom
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    import pymupdf
    import rapidocr_onnxruntime.utils as ru
    from rapidocr_onnxruntime import RapidOCR

    # 多进程下限制每个 ORT 会话的线程数，避免 8 个进程各自开满线程造成抢占
    _orig_session_options = ru.SessionOptions

    class _LimitedSessionOptions(_orig_session_options):
        def __init__(self):
            super().__init__()
            self.intra_op_num_threads = 1
            self.inter_op_num_threads = 1

    ru.SessionOptions = _LimitedSessionOptions
    _doc = pymupdf.open(pdf_path)
    _zoom = zoom
    _ocr_engine = RapidOCR()


def _clean_text(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 纯页码行
        if re.fullmatch(r"[.．·\-\s]*\d{1,4}[.．·\-\s]*", line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _process_page(args: tuple[int, float]) -> dict:
    page_no, zoom = args
    import numpy as np
    import pymupdf

    page = _doc[page_no]
    text = page.get_text("text")
    method = "text"
    if len(text.strip()) < 40:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        if arr.shape[2] == 4:
            arr = arr[:, :, :3]
        arr = np.ascontiguousarray(arr[:, :, ::-1])  # RGB -> BGR
        result, _ = _ocr_engine(arr)
        text = "" if result is None else "".join(item[1] for item in result)
        method = "ocr"
    return {"page": page_no, "text": _clean_text(text), "method": method}


def _load_done(raw_path: Path) -> set[int]:
    done = set()
    if raw_path.exists():
        with raw_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(int(json.loads(line)["page"]))
                except (ValueError, KeyError, json.JSONDecodeError):
                    continue
    return done


def build_book(book: dict, workers: int, zoom: float, force: bool) -> None:
    pdf_path = BOOK_DIR / book["pdf"]
    if not pdf_path.exists():
        print(f"[skip] 缺少文件: {pdf_path}")
        return

    import pymupdf

    doc = pymupdf.open(pdf_path)
    page_count = doc.page_count
    doc.close()

    raw_path = RAW_DIR / f"{book['slug']}.jsonl"
    done = set() if force else _load_done(raw_path)
    todo = [p for p in range(page_count) if p not in done]
    print(f"\n=== {book['title']} ===")
    print(f"pages={page_count} done={len(done)} todo={len(todo)}")
    if not todo:
        return

    mode = "w" if force else "a"
    completed = 0
    with raw_path.open(mode, encoding="utf-8") as out:
        with mp.Pool(
            processes=workers,
            initializer=_init_worker,
            initargs=(str(pdf_path), zoom),
        ) as pool:
            for record in pool.imap_unordered(
                _process_page, [(p, zoom) for p in todo], chunksize=1
            ):
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()
                completed += 1
                if completed % 10 == 0 or completed == len(todo):
                    print(f"  {completed}/{len(todo)} pages", flush=True)


def chunk_book(book: dict, chunk_size: int = 700, overlap: int = 120) -> list[dict]:
    raw_path = RAW_DIR / f"{book['slug']}.jsonl"
    if not raw_path.exists():
        return []
    records = []
    with raw_path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                records.append(json.loads(line))
    records.sort(key=lambda r: r["page"])

    chunks: list[dict] = []
    buf = ""
    start_page = None
    end_page = None

    def emit(text: str, p_start: int, p_end: int) -> None:
        text = text.strip()
        if len(text) < 80:
            return
        chunks.append(
            {
                "id": f"{book['slug']}-{len(chunks) + 1:04d}",
                "book": book["title"],
                "author": book["author"],
                "page_start": p_start + 1,
                "page_end": p_end + 1,
                "text": text,
            }
        )

    for rec in records:
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", rec.get("text", "")).strip()
        if not text:
            continue
        page = int(rec["page"])
        if start_page is None:
            start_page = page
        buf += ("\n" if buf else "") + text
        end_page = page
        while len(buf) >= chunk_size:
            cut = buf.rfind("。", 0, chunk_size)
            if cut < chunk_size // 2:
                cut = chunk_size
            else:
                cut += 1
            emit(buf[:cut], start_page, end_page)
            buf = buf[cut - overlap :]
            if buf:
                start_page = max(end_page - 1, start_page)
    if buf.strip():
        emit(buf, start_page if start_page is not None else 0, end_page or 0)
    return chunks


STOPWORDS = set(
    "的 了 和 与 及 或 是 在 有 为 对 也 就 都 而 及 其 之 以 于 中 上 下 "
    "我们 可以 进行 通过 如图 所示 表 图 第 页".split()
)
DOMAIN_WORDS = [
    "活性污泥", "微型动物", "污泥生物指数", "生物相", "指示生物",
    "楯纤虫", "钟虫", "轮虫", "累枝虫", "盖纤虫", "表壳虫", "内管虫",
    "扭曲管叶虫", "摩门虫", "斜管虫", "袋鞭虫", "匣壳虫", "线虫", "漫游虫",
    "草履虫", "变形虫", "丝状菌", "污泥膨胀", "泡沫", "溶解氧", "污泥龄",
    "原生动物", "后生动物", "纤毛虫", "鞭毛虫", "固着", "游泳",
]


def tokenize(text: str) -> list[str]:
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


def build_index(chunks: list[dict]) -> None:
    import jieba
    from rank_bm25 import BM25Okapi

    for word in DOMAIN_WORDS:
        jieba.add_word(word)
    corpus = [tokenize(c["text"]) for c in chunks]
    bm25 = BM25Okapi(corpus)
    with (INDEX_DIR / "bm25.pkl").open("wb") as fh:
        pickle.dump({"bm25": bm25, "chunks": chunks}, fh)
    with (INDEX_DIR / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(chunk, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--zoom", type=float, default=2.0)
    parser.add_argument("--book", default="all")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    selected = [
        b for b in BOOKS if args.book in ("all", b["slug"])
    ]
    for book in selected:
        build_book(book, max(1, args.workers), args.zoom, args.force)

    all_chunks: list[dict] = []
    for book in BOOKS:
        book_chunks = chunk_book(book)
        print(f"{book['title']}: {len(book_chunks)} chunks")
        all_chunks.extend(book_chunks)

    if not all_chunks:
        print("没有生成任何文本块")
        return 1

    print(f"总块数: {len(all_chunks)}，构建 BM25 索引...")
    build_index(all_chunks)
    manifest = {
        "books": BOOKS,
        "chunks": len(all_chunks),
    }
    (INDEX_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
