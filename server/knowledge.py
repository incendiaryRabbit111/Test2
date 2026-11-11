"""用户自主导入知识的运行时存储与检索。

内置知识库仍然是 knowledge/index/bm25.pkl；
用户导入的内容放在 data/api/knowledge/，启动时和内置块合并，
重新构建一个 BM25 索引，供 analyzer 的 RAG 检索使用。

第一版 PDF 只支持有文字层的文件；扫描版 PDF 需要 OCR，暂不处理。
"""
from __future__ import annotations

import json
import logging
import os
import pickle
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app import rag
from server.config import DATA_DIR

logger = logging.getLogger("microbe.api.knowledge")

KNOWLEDGE_DIR = DATA_DIR / "knowledge"
DOCS_PATH = KNOWLEDGE_DIR / "documents.json"
CHUNKS_PATH = KNOWLEDGE_DIR / "chunks.jsonl"
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 200_000
CHUNK_SIZE = 700
CHUNK_OVERLAP = 120


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()


def _chunk_text(
    text: str,
    *,
    doc_id: str,
    title: str,
    author: str,
    page_start: int,
    page_end: int,
) -> list[dict[str, Any]]:
    text = _clean_text(text)
    if not text:
        return []

    chunks: list[dict[str, Any]] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE)
        if end < len(text):
            cut = text.rfind("。", start + CHUNK_SIZE // 2, end)
            if cut > 0:
                end = cut + 1
        piece = text[start:end].strip()
        if len(piece) >= 10:
            chunks.append(
                {
                    "id": f"{doc_id}-{len(chunks) + 1:04d}",
                    "doc_id": doc_id,
                    "book": title,
                    "author": author,
                    "page_start": page_start,
                    "page_end": page_end,
                    "text": piece,
                    "source": "user",
                }
            )
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


class KnowledgeService:
    """内置知识 + 用户导入知识的内存检索服务。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.docs: list[dict[str, Any]] = []
        self.user_chunks: list[dict[str, Any]] = []
        self.chunks: list[dict[str, Any]] = []
        self.bm25 = None
        self.available = False
        self.builtin_count = 0
        self.last_updated = ""
        self.reload()

    # ---------------- 加载/构建 ----------------
    def _load_builtin_chunks(self) -> list[dict[str, Any]]:
        if not rag.INDEX_PATH.exists():
            return []
        try:
            with rag.INDEX_PATH.open("rb") as fh:
                data = pickle.load(fh)
            chunks = data.get("chunks") if isinstance(data, dict) else None
            return chunks if isinstance(chunks, list) else []
        except Exception:
            logger.exception("内置知识库索引加载失败：%s", rag.INDEX_PATH)
            return []

    def _load_user_docs(self) -> list[dict[str, Any]]:
        if not DOCS_PATH.exists():
            return []
        try:
            data = json.loads(DOCS_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            logger.exception("用户知识文档列表损坏：%s", DOCS_PATH)
            return []

    def _load_user_chunks(self) -> list[dict[str, Any]]:
        if not CHUNKS_PATH.exists():
            return []
        chunks: list[dict[str, Any]] = []
        try:
            with CHUNKS_PATH.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    item = json.loads(line)
                    if isinstance(item, dict) and item.get("text"):
                        chunks.append(item)
        except Exception:
            logger.exception("用户知识块文件损坏：%s", CHUNKS_PATH)
        return chunks

    def _save_user_data(self) -> None:
        _atomic_write_text(
            DOCS_PATH,
            json.dumps(self.docs, ensure_ascii=False, indent=2),
        )
        body = "\n".join(json.dumps(c, ensure_ascii=False) for c in self.user_chunks)
        _atomic_write_text(CHUNKS_PATH, body + ("\n" if body else ""))

    def _rebuild(self) -> None:
        builtin = self._load_builtin_chunks()
        self.builtin_count = len(builtin)
        self.chunks = builtin + self.user_chunks
        if not self.chunks:
            self.bm25 = None
            self.available = False
            return
        try:
            from rank_bm25 import BM25Okapi

            corpus = [rag.tokenize(c.get("text", "")) for c in self.chunks]
            self.bm25 = BM25Okapi(corpus)
            self.available = True
            self.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            logger.exception("知识库 BM25 索引构建失败")
            self.bm25 = None
            self.available = False

    def reload(self) -> None:
        with self._lock:
            self.docs = self._load_user_docs()
            self.user_chunks = self._load_user_chunks()
            self._rebuild()

    # ---------------- 查询 ----------------
    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "available": self.available,
                "builtin_chunks": self.builtin_count,
                "user_chunks": len(self.user_chunks),
                "documents": len(self.docs),
                "total_chunks": len(self.chunks),
                "last_updated": self.last_updated,
            }

    def list_documents(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(doc) for doc in self.docs]

    def search(self, query: str, top_k: int = 6, min_score: float = 0.0) -> list[rag.Reference]:
        with self._lock:
            if not self.available or not query.strip() or self.bm25 is None:
                return []
            tokens = rag.tokenize(query)
            if not tokens:
                return []
            scores = self.bm25.get_scores(tokens)
            ranked = sorted(enumerate(scores), key=lambda kv: kv[1], reverse=True)

            selected: list[tuple[int, float]] = []
            seen: set[int] = set()

            def add(idx: int, score: float) -> None:
                if idx in seen or len(selected) >= top_k:
                    return
                chunk = self.chunks[idx]
                if rag.KnowledgeBase._is_low_value(chunk.get("text", "")):
                    return
                selected.append((idx, score))
                seen.add(idx)

            # 用户导入的内容通常很少，如果完全按内置语料的 BM25 分数排序，
            # 很容易被 341 个内置块挤出 top_k。给匹配到的用户知识保留最多 2 个位置。
            user_slots = min(2, top_k)
            user_hits = 0
            for idx, score in ranked:
                if score <= min_score:
                    break
                if self.chunks[idx].get("source") != "user":
                    continue
                before = len(selected)
                add(idx, score)
                if len(selected) > before:
                    user_hits += 1
                if user_hits >= user_slots:
                    break

            for idx, score in ranked:
                if score <= min_score:
                    break
                add(idx, score)
                if len(selected) >= top_k:
                    break

            refs: list[rag.Reference] = []
            for idx, score in selected:
                chunk = self.chunks[idx]
                refs.append(
                    rag.Reference(
                        label=f"R{len(refs) + 1}",
                        book=str(chunk.get("book", "用户导入资料")),
                        author=str(chunk.get("author", "")),
                        page_start=int(chunk.get("page_start", 1) or 1),
                        page_end=int(chunk.get("page_end", 1) or 1),
                        text=rag.KnowledgeBase._snippet(chunk.get("text", ""), tokens),
                        score=float(score),
                    )
                )
            return refs

    # ---------------- 导入 ----------------
    def add_text(self, title: str, content: str) -> dict[str, Any]:
        title = title.strip()
        content = _clean_text(content)
        if not title:
            raise ValueError("标题不能为空")
        if not content:
            raise ValueError("知识内容不能为空")
        if len(content) > MAX_TEXT_CHARS:
            raise ValueError(f"文字内容过长（上限 {MAX_TEXT_CHARS} 字）")

        with self._lock:
            doc_id = uuid.uuid4().hex[:12]
            chunks = _chunk_text(
                content,
                doc_id=doc_id,
                title=title,
                author="用户导入",
                page_start=1,
                page_end=1,
            )
            if not chunks:
                raise ValueError("内容过短，无法形成有效知识块")
            doc = {
                "id": doc_id,
                "title": title,
                "kind": "text",
                "pages": 1,
                "chunks": len(chunks),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.docs.append(doc)
            self.user_chunks.extend(chunks)
            self._save_user_data()
            self._rebuild()
            return {"document": doc, "status": self.status()}

    def add_pdf(self, filename: str, data: bytes) -> dict[str, Any]:
        if not filename.lower().endswith(".pdf"):
            raise ValueError("只支持 .pdf 文件")
        if not data:
            raise ValueError("PDF 文件为空")
        if len(data) > MAX_PDF_BYTES:
            raise ValueError(f"PDF 过大（上限 {MAX_PDF_BYTES // 1024 // 1024} MB）")

        try:
            import pymupdf
        except Exception as exc:
            raise ValueError("服务端未安装 PDF 解析依赖 pymupdf") from exc

        title = Path(filename).stem.strip() or "用户导入 PDF"
        pages: list[tuple[int, str]] = []
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
            try:
                for index in range(doc.page_count):
                    text = _clean_text(doc[index].get_text("text"))
                    if text:
                        pages.append((index + 1, text))
            finally:
                doc.close()
        except Exception as exc:
            raise ValueError(f"PDF 解析失败：{exc}") from exc

        if not pages or sum(len(text) for _, text in pages) < 20:
            raise ValueError("PDF 没有可提取的文字；扫描版 PDF 暂不支持，请先做 OCR")

        with self._lock:
            doc_id = uuid.uuid4().hex[:12]
            all_chunks: list[dict[str, Any]] = []
            for page_no, text in pages:
                all_chunks.extend(
                    _chunk_text(
                        text,
                        doc_id=doc_id,
                        title=title,
                        author="用户导入",
                        page_start=page_no,
                        page_end=page_no,
                    )
                )
            if not all_chunks:
                raise ValueError("PDF 文字过少，无法形成有效知识块")
            meta = {
                "id": doc_id,
                "title": title,
                "kind": "pdf",
                "pages": len(pages),
                "chunks": len(all_chunks),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.docs.append(meta)
            self.user_chunks.extend(all_chunks)
            self._save_user_data()
            self._rebuild()
            return {"document": meta, "status": self.status()}

    # ---------------- 删除 ----------------
    def delete_document(self, doc_id: str) -> bool:
        with self._lock:
            old_count = len(self.docs)
            self.docs = [d for d in self.docs if d.get("id") != doc_id]
            if len(self.docs) == old_count:
                return False
            self.user_chunks = [c for c in self.user_chunks if c.get("doc_id") != doc_id]
            self._save_user_data()
            self._rebuild()
            return True


knowledge_service = KnowledgeService()
