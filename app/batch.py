"""批量导入：一次粘贴多次检测的数据。

分段规则（任一即可）：
  · 连续两个及以上空行
  · 独占一行的分隔符：--- / === / ### / ***

时间来源（按优先级）：
  1. 段内第一行本身就是一个时间 → 用它作为采样时间
  2. 否则用界面给的「起始时间 + 间隔分钟」按序号推算
  3. 都没有 → 留空（后续按导入顺序排序）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

from app import parser as parser_mod
from app.times import fmt, parse_dt

_SEG_SPLIT = re.compile(
    r"\n\s*\n+"
    r"|\n\s*(?:-{3,}|={3,}|#{3,}|\*{3,}|~{3,})\s*\n"
    r"|\n\s*(?:-{3,}|={3,}|#{3,}|\*{3,}|~{3,})\s*$"
)
_SEPARATOR = re.compile(r"^(?:-{3,}|—{3,}|={3,}|#{3,}|\*{3,}|~{3,})$")


@dataclass
class BatchItem:
    index: int
    text: str = ""
    sample_time: str = ""
    time_source: str = ""          # 段内自带 / 推算 / 无
    parsed: object = None
    warning: str = ""


@dataclass
class BatchResult:
    items: list[BatchItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok_items(self) -> list[BatchItem]:
        return [it for it in self.items if it.parsed and it.parsed.species]


def split_segments(raw: str) -> list[str]:
    """按空行/独占一行的分隔符切段。

    逐行处理，避免「空行 + ---」把 --- 留在下一段开头，
    也避免连续空行产生幽灵段。
    """
    if not raw or not raw.strip():
        return []
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    segments: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if not buf:
            return
        part = "\n".join(buf).strip()
        if part:
            segments.append(part)
        buf.clear()

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if _SEPARATOR.fullmatch(stripped):
            flush()
            continue
        buf.append(line)
    flush()
    return segments


def parse_batch(raw: str, start_time: str = "", interval_min: int = 0) -> BatchResult:
    result = BatchResult()
    segments = split_segments(raw)
    if not segments:
        result.warnings.append("没有可解析的内容")
        return result

    base = parse_dt(start_time) if start_time else None
    if start_time and base is None:
        result.warnings.append(f"起始时间「{start_time}」无法识别，将不使用推算时间")

    valid_index = 0
    for i, seg in enumerate(segments):
        item = BatchItem(index=i + 1, text=seg)

        # 1) 段内第一行是不是时间
        lines = seg.splitlines()
        if lines:
            dt = parse_dt(lines[0].strip())
            if dt is not None:
                item.sample_time = fmt(dt)
                item.time_source = "段内自带"
                item.text = "\n".join(lines[1:]).strip()

        # 2) 推算；无效段不占用时间序号
        if not item.sample_time and base is not None and interval_min > 0:
            item.sample_time = fmt(
                base + timedelta(minutes=interval_min * valid_index)
            )
            item.time_source = "按起始时间+间隔推算"

        item.parsed = parser_mod.parse(item.text)
        if not item.parsed.species:
            item.warning = "未识别到物种数据"
            result.warnings.append(f"第 {i + 1} 段没解析出物种，已跳过")
        else:
            valid_index += 1
            if item.parsed.warnings:
                item.warning = "；".join(item.parsed.warnings)
            if not item.time_source:
                item.time_source = "无"

        result.items.append(item)

    if len(result.ok_items) <= 1 and len(segments) > 1:
        result.warnings.append(
            "只解析出 1 段有效数据——可能是分隔符没被识别。"
            "段与段之间请用空行或 --- 隔开。"
        )
    return result
