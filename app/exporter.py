"""导出 Excel。

三个工作表，主表按甲方 xlsx 的纵向格式（一个物种一行），不再每个物种单开一列：

  1. 物种评价   —— 序号 | 物种 | 浓度 | 相对丰度 | 等级 | 较上次变化 | 综合评价 | 指导意见
  2. 检测概要   —— 一行一次检测的总体信息（时间/设备/物种数/H'/优势种群/趋势命中…）
  3. AI 分析报告 —— 情况 / 变化 / 建议
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEAD_FILL = PatternFill("solid", fgColor="DCE6F1")
HEAD_FONT = Font(bold=True)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center")
ROW_ABS = PatternFill("solid", fgColor="FDE2E2")     # 绝对优势
ROW_DOM = PatternFill("solid", fgColor="EAF6EA")     # 优势


def _write_header(ws, headers: list[str]) -> None:
    ws.append(headers)
    for idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=idx)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = CENTER
    ws.freeze_panes = "A2"


def _autosize(ws, caps: dict[int, int] | None = None) -> None:
    caps = caps or {}
    for idx, col in enumerate(ws.columns, start=1):
        width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[get_column_letter(idx)].width = min(max(width + 2, 9), caps.get(idx, 40))


def export(path, sample_time: str = "", parsed=None, metrics=None, analysis=None,
           changes=None, device: str = "", trends=None, previous_time: str = "") -> Path:
    """changes：{物种名: 变化文本}；trends：TrendHit 列表。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    eval_map = analysis.eval_map()
    changes = changes or {}
    trends = trends or []

    # ---- Sheet 1 物种评价（主表） ----
    ws = wb.active
    ws.title = "物种评价"
    _write_header(ws, ["序号", "物种", "浓度", "相对丰度(%)", "等级", "较上次变化",
                       "综合评价", "指导意见"])
    for i, r in enumerate(metrics.rows, start=1):
        ev = eval_map.get(r.name)
        level = "绝对优势" if r.is_absolute else ("优势" if r.is_dominant else "常见")
        ws.append([
            i, r.name, round(r.concentration, 4), round(r.percent, 2), level,
            changes.get(r.name, "—"),
            ev.comment if ev else "", ev.advice if ev else "",
        ])
        if r.is_absolute:
            fill = ROW_ABS
        elif r.is_dominant:
            fill = ROW_DOM
        else:
            fill = None
        if fill:
            for col in range(1, 9):
                ws.cell(row=i + 1, column=col).fill = fill
        for col in (7, 8):
            ws.cell(row=i + 1, column=col).alignment = WRAP
        for col in (1, 3, 4, 5, 6):
            ws.cell(row=i + 1, column=col).alignment = CENTER
    _autosize(ws, caps={2: 16, 7: 70, 8: 50})

    # ---- Sheet 2 检测概要 ----
    ws2 = wb.create_sheet("检测概要")
    s = metrics.species_count
    h_max = round(math.log(s), 3) if s > 1 else 0.0
    evenness = round(metrics.shannon_h / h_max, 3) if h_max else 0.0
    _write_header(ws2, ["设备编号", "采样时间", "导出时间", "浓度单位", "浓度合计",
                        "物种种类数", "多样性指数H'", "均匀度", "优势种群", "绝对优势种群",
                        "对比基准时间", "命中趋势规则"])
    ws2.append([
        device or "", sample_time or "", datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        parsed.unit or "", round(metrics.total, 4), s, metrics.shannon_h, evenness,
        "、".join(metrics.dominant), "、".join(metrics.absolute),
        previous_time or "（无）",
        "；".join(f"{t.rule}（{t.detail}）" for t in trends) or "（无）",
    ])
    for cell in ws2[2]:
        cell.alignment = WRAP
    _autosize(ws2, caps={9: 40, 10: 24, 12: 40})

    # ---- Sheet 3 AI 分析报告 ----
    ws3 = wb.create_sheet("AI分析报告")
    _write_header(ws3, ["分析来源", "报告正文"])
    ws3.append([analysis.source, analysis.report])
    ws3.cell(row=2, column=2).alignment = WRAP
    ws3.column_dimensions["A"].width = 18
    ws3.column_dimensions["B"].width = 100
    ws3.row_dimensions[2].height = 230
    if analysis.error:
        ws3.append(["调用异常", analysis.error])

    wb.save(path)
    return path
