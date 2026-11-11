"""把一批历史记录压缩成给大模型看的历史摘要。

这里不调用 AI，也不做任何预测；只做确定性的统计和格式化。
"""
from __future__ import annotations

from collections import Counter

from app import metrics as metrics_mod


def _metric_values(rec) -> dict:
    if rec.metrics:
        return dict(rec.metrics)
    m = metrics_mod.compute(rec.species)
    return {
        "total": m.total,
        "species_count": m.species_count,
        "shannon_h": m.shannon_h,
        "margalef_d": m.margalef_d,
        "pielou_j": m.pielou_j,
        "dominant": list(m.dominant),
        "absolute": list(m.absolute),
    }


def _fmt_num(value, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _percent(rec, name: str) -> float:
    total = sum(v for v in rec.species.values() if v > 0)
    if total <= 0:
        return 0.0
    return rec.species.get(name, 0.0) / total * 100


def _top_names(rec, limit: int = 5) -> list[str]:
    return [
        name
        for name, _ in sorted(
            rec.species.items(), key=lambda kv: (-kv[1], kv[0])
        )[:limit]
    ]


def _metrics_line(rec) -> str:
    m = _metric_values(rec)
    dominant = "、".join(m.get("dominant") or []) or "无"
    return (
        f"S={m.get('species_count', 0)}，总浓度={_fmt_num(m.get('total'), 3)}，"
        f"H'={_fmt_num(m.get('shannon_h'), 3)}，"
        f"D={_fmt_num(m.get('margalef_d'), 3)}，"
        f"J={_fmt_num(m.get('pielou_j'), 3)}，优势种={dominant}"
    )


def build_batch_context(records, batch_id: str = "", max_rows: int = 8,
                        max_species: int = 6) -> str:
    """生成一段紧凑的批次历史摘要。"""
    records = [r for r in records if r.species]
    if not records:
        return "（本批次没有可用历史记录）"

    records.sort(
        key=lambda r: (
            r.batch_index if r.batch_index else 10**9,
            r.id if r.id is not None else 10**9,
        )
    )
    first, last = records[0], records[-1]
    first_m, last_m = _metric_values(first), _metric_values(last)
    times = [r.sample_time for r in records if r.sample_time]
    missing_times = len(records) - len(times)
    sources = Counter(r.time_source or "未标注" for r in records)

    lines: list[str] = [
        "【批次历史摘要】",
        f"批次号：{batch_id or '（未标注）'}｜记录数：{len(records)}",
    ]
    if times:
        lines.append(f"时间范围：{times[0]} 至 {times[-1]}")
    else:
        lines.append("时间范围：无采样时间，仅按导入顺序排列")
    lines.append("")

    lines.append("【首末对比】")
    lines.append(f"首条：{first.sample_time or '无时间'}｜{_metrics_line(first)}")
    lines.append(f"末条：{last.sample_time or '无时间'}｜{_metrics_line(last)}")
    delta_h = float(last_m.get("shannon_h") or 0) - float(first_m.get("shannon_h") or 0)
    delta_total = float(last_m.get("total") or 0) - float(first_m.get("total") or 0)
    lines.append(
        f"变化：H' {delta_h:+.3f}；总浓度 {delta_total:+.3f}；"
        f"物种数 {int(first_m.get('species_count') or 0)} → "
        f"{int(last_m.get('species_count') or 0)}"
    )
    lines.append("")

    # 最近若干条，给模型一个“近期形态”而不是 100 行原表
    lines.append(f"【最近 {min(max_rows, len(records))} 条】")
    for rec in records[-max_rows:]:
        m = _metric_values(rec)
        top = "、".join(_top_names(rec, 2)) or "无"
        lines.append(
            f"{rec.sample_time or '无时间'}｜S={m.get('species_count', 0)}｜"
            f"H'={_fmt_num(m.get('shannon_h'), 3)}｜"
            f"总浓度={_fmt_num(m.get('total'), 2)}｜优势：{top}"
        )
    lines.append("")

    # 关键物种：末条优势种 + 末条变化最大的物种
    names: list[str] = []
    for name in _top_names(last, max_species):
        if name not in names:
            names.append(name)
    changed = sorted(
        [c for c in (last.changes or []) if c.get("pct") is not None],
        key=lambda c: abs(float(c.get("pct") or 0)),
        reverse=True,
    )
    for item in changed:
        name = str(item.get("species") or "")
        if name and name not in names:
            names.append(name)
        if len(names) >= max_species:
            break
    names = names[:max_species]

    if names:
        lines.append("【关键物种轨迹】")
        for name in names:
            first_pct = _percent(first, name)
            last_pct = _percent(last, name)
            values = [rec.species.get(name, 0.0) for rec in records]
            present = sum(1 for value in values if value > 0)
            lines.append(
                f"{name}：相对丰度 {first_pct:.1f}% → {last_pct:.1f}%；"
                f"末条浓度 {last.species.get(name, 0.0):.3f}；"
                f"检出 {present}/{len(records)} 次"
            )
        lines.append("")

    # 趋势规则命中统计
    trend_counter = Counter()
    for rec in records:
        for hit in rec.trends or []:
            trend_counter[str(hit.get("rule") or "")] += 1
    lines.append("【趋势命中统计】")
    if trend_counter:
        for rule, count in trend_counter.most_common(8):
            lines.append(f"{rule}：{count} 次")
    else:
        lines.append("本批次没有命中固定趋势规则")
    if last.trends:
        lines.append("末条命中：" + "、".join(str(t.get("rule")) for t in last.trends))
    lines.append("")

    lines.append("【最近一次变化】")
    recent_changes = [
        c for c in (last.changes or []) if c.get("pct") is not None
    ]
    if recent_changes:
        for item in sorted(
            recent_changes, key=lambda c: abs(float(c.get("pct") or 0)), reverse=True
        )[:8]:
            lines.append(
                f"{item.get('species')}：{item.get('text')}"
                f"（{item.get('source')}）"
            )
    else:
        lines.append("末条没有可用的上一条变化基准")
    lines.append("")

    lines.append("【数据质量】")
    if missing_times:
        lines.append(f"{missing_times} 条没有采样时间")
    if times:
        lines.append(
            "时间来源：" + "、".join(f"{k} {v}" for k, v in sources.most_common())
        )
    if len(records) < 3:
        lines.append("记录数较少，趋势判断应保守")
    lines.append("以上均为本地计算，不是 AI 推断。")

    text = "\n".join(lines).strip()
    # 防止极端输入把提示词撑爆
    if len(text) > 4000:
        text = text[:3950].rstrip() + "\n…（历史摘要已截断）"
    return text
