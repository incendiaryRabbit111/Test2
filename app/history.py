"""会话记录库（SQLite）。

一次检测 = 一条会话记录，完整保存：原始输入、解析结果、指标、变化快照、
逐物种评价、整体报告。这样点开任意一条就能还原当时的全部内容。

（原「设备编号」已取消：当前阶段只有一台设备，全部记录按时间排成一条序列。）
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.paths import ROOT
DB_PATH = ROOT / "data" / "history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    device           TEXT    NOT NULL DEFAULT '',
    sample_time      TEXT    NOT NULL DEFAULT '',
    imported_at      TEXT    NOT NULL,
    unit             TEXT    NOT NULL DEFAULT '',
    total            REAL,
    species_count    INTEGER,
    shannon_h        REAL,
    species_json     TEXT    NOT NULL,
    report           TEXT,
    raw_text         TEXT,
    evaluations_json TEXT,
    changes_json     TEXT,
    trends_json      TEXT,
    analysis_source  TEXT,
    error_text       TEXT,
    references_json  TEXT
);
CREATE INDEX IF NOT EXISTS idx_id ON samples(id DESC);
"""

# 老库缺的列，启动时补齐
_EXTRA_COLUMNS = {
    "raw_text": "TEXT",
    "evaluations_json": "TEXT",
    "changes_json": "TEXT",
    "trends_json": "TEXT",
    "analysis_source": "TEXT",
    "error_text": "TEXT",
    "references_json": "TEXT",
}

_COLS = ("id, device, sample_time, imported_at, unit, total, species_count, shannon_h, "
         "species_json, report, raw_text, evaluations_json, changes_json, trends_json, "
         "analysis_source, error_text, references_json")

DUMMY_DEVICE = ""          # 已废弃，保留列以兼容老库


@dataclass
class Record:
    id: int | None = None
    sample_time: str = ""
    imported_at: str = ""
    unit: str = ""
    total: float = 0.0
    species_count: int = 0
    shannon_h: float = 0.0
    species: dict[str, float] = field(default_factory=dict)
    report: str = ""
    raw_text: str = ""
    evaluations: list = field(default_factory=list)     # [{species, comment, advice}]
    changes: list = field(default_factory=list)         # [{species, pct, source, text}]
    trends: list = field(default_factory=list)          # [{rule, detail, meaning}]
    analysis_source: str = ""
    error_text: str = ""
    references: list = field(default_factory=list)      # [{label, book, pages, text, cited}]

    @property
    def title(self) -> str:
        """会话列表里显示的名字。"""
        return self.sample_time or self.imported_at or "（无时间）"

    @property
    def subtitle(self) -> str:
        bits = []
        if self.species_count:
            bits.append(f"{self.species_count} 种")
        if self.shannon_h:
            bits.append(f"H'={self.shannon_h}")
        if not self.report:
            bits.append("未分析")
        return "　".join(bits)


class History:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            self._migrate(conn)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(samples)")}
        for name, typ in _EXTRA_COLUMNS.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE samples ADD COLUMN {name} {typ}")

    # ---------------- 写 ----------------
    def save(self, rec: Record) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO samples(device, sample_time, imported_at, unit, total,"
                " species_count, shannon_h, species_json, report, raw_text,"
                " evaluations_json, changes_json, trends_json, analysis_source, error_text,"
                " references_json)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    DUMMY_DEVICE,
                    rec.sample_time,
                    rec.imported_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    rec.unit, rec.total, rec.species_count, rec.shannon_h,
                    json.dumps(rec.species, ensure_ascii=False),
                    rec.report, rec.raw_text,
                    json.dumps(rec.evaluations, ensure_ascii=False),
                    json.dumps(rec.changes, ensure_ascii=False),
                    json.dumps(rec.trends, ensure_ascii=False),
                    rec.analysis_source, rec.error_text,
                    json.dumps(rec.references, ensure_ascii=False),
                ),
            )
            return int(cur.lastrowid or 0)

    def update_analysis(self, rec_id: int, rec: Record) -> None:
        """分析完成后回填报告/评价（批量导入的记录只有前半部分）。"""
        with self._conn() as conn:
            conn.execute(
                "UPDATE samples SET report=?, raw_text=?, evaluations_json=?,"
                " changes_json=?, trends_json=?, analysis_source=?, error_text=?, sample_time=?,"
                " total=?, species_count=?, shannon_h=?, references_json=? WHERE id=?",
                (
                    rec.report, rec.raw_text,
                    json.dumps(rec.evaluations, ensure_ascii=False),
                    json.dumps(rec.changes, ensure_ascii=False),
                    json.dumps(rec.trends, ensure_ascii=False),
                    rec.analysis_source, rec.error_text, rec.sample_time,
                    rec.total, rec.species_count, rec.shannon_h,
                    json.dumps(rec.references, ensure_ascii=False), rec_id,
                ),
            )

    # ---------------- 读 ----------------
    def get(self, rec_id: int) -> Record | None:
        with self._conn() as conn:
            row = conn.execute(f"SELECT {_COLS} FROM samples WHERE id=?", (rec_id,)).fetchone()
        return self._to_record(row) if row else None

    def last(self) -> Record | None:
        """上一条记录（「较上次变化」的基准）。"""
        with self._conn() as conn:
            row = conn.execute(f"SELECT {_COLS} FROM samples ORDER BY id DESC LIMIT 1").fetchone()
        return self._to_record(row) if row else None

    def recent(self, limit: int = 500) -> list[Record]:
        """按时间升序返回（趋势图用）。"""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM samples ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._to_record(r) for r in reversed(rows)]

    def all_desc(self) -> list[Record]:
        """按时间倒序返回（会话列表用，最新的在最上面）。"""
        with self._conn() as conn:
            rows = conn.execute(f"SELECT {_COLS} FROM samples ORDER BY id DESC").fetchall()
        return [self._to_record(r) for r in rows]

    def count(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0])

    def delete(self, rec_id: int) -> int:
        with self._conn() as conn:
            return conn.execute("DELETE FROM samples WHERE id=?", (rec_id,)).rowcount

    def clear(self) -> int:
        with self._conn() as conn:
            return conn.execute("DELETE FROM samples").rowcount

    # ---------------- 转换 ----------------
    @staticmethod
    def _loads(text, default):
        if not text:
            return default
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return default

    @classmethod
    def _to_record(cls, row) -> Record:
        return Record(
            id=row[0], sample_time=row[2], imported_at=row[3], unit=row[4],
            total=row[5] or 0.0, species_count=row[6] or 0, shannon_h=row[7] or 0.0,
            species=cls._loads(row[8], {}),
            report=row[9] or "",
            raw_text=row[10] or "",
            evaluations=cls._loads(row[11], []),
            changes=cls._loads(row[12], []),
            trends=cls._loads(row[13], []),
            analysis_source=row[14] or "",
            error_text=row[15] or "",
            references=cls._loads(row[16], []),
        )
