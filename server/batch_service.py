"""批量导入与批次内单条分析。

- 导入：本地解析、指标、变化、趋势入库，不调用 AI；
- 任意一条分析：只取它之前的历史作为上下文，不把未来数据喂给 AI；
- 最后一条分析：只是“任意一条分析”的便捷入口。
"""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import HTTPException

from app import analyzer as analyzer_mod
from app import batch as batch_mod
from app import history as history_mod
from app import metrics as metrics_mod
from app import parser as parser_mod
from app import trend as trend_mod
from app.analyzer import AnalysisResult
from app.history_context import build_batch_context
from app.times import parse_dt
from server.case_service import case_service
from server.knowledge import knowledge_service
from server.schemas import (
    BatchAnalyzeLastResponse,
    BatchImportItemOut,
    BatchImportResponse,
    BatchItemOut,
    BatchPreviewResponse,
    BatchRecordOut,
    BatchRecordsResponse,
    ChangeOut,
    EvaluationOut,
    MetricsOut,
    TrendOut,
)
from server.service import config_store, history

logger = logging.getLogger("microbe.api.batch")


def _metrics_out(metrics: metrics_mod.MetricsResult) -> MetricsOut:
    return MetricsOut(
        total=metrics.total,
        species_count=metrics.species_count,
        shannon_h=metrics.shannon_h,
        margalef_d=metrics.margalef_d,
        pielou_j=metrics.pielou_j,
        dominant=list(metrics.dominant),
        absolute=list(metrics.absolute),
    )


def _change_out(item: dict) -> ChangeOut:
    return ChangeOut(
        species=str(item.get("species") or ""),
        pct=item.get("pct"),
        text=str(item.get("text") or "—"),
        source=str(item.get("source") or ""),
    )


def _trend_out(item: dict) -> TrendOut:
    return TrendOut(
        rule=str(item.get("rule") or ""),
        detail=str(item.get("detail") or ""),
        meaning=str(item.get("meaning") or ""),
    )


def _item_warnings(item) -> list[str]:
    if item.warning:
        return [item.warning]
    if item.parsed and item.parsed.warnings:
        return list(item.parsed.warnings)
    return []


def _validate_start_time(start_time: str) -> None:
    if start_time.strip() and parse_dt(start_time) is None:
        raise HTTPException(
            status_code=422,
            detail=f"起始时间无法识别：{start_time}（建议 2026-10-09 08:00:00）",
        )


def preview(text: str, start_time: str = "", interval_min: int = 0) -> BatchPreviewResponse:
    _validate_start_time(start_time)
    result = batch_mod.parse_batch(
        text,
        start_time=start_time,
        interval_min=interval_min,
    )
    items: list[BatchItemOut] = []
    for item in result.items:
        parsed = item.parsed
        valid = bool(parsed and parsed.species)
        metrics = metrics_mod.compute(parsed.species) if valid else None
        items.append(
            BatchItemOut(
                index=item.index,
                valid=valid,
                sample_time=item.sample_time,
                time_source=item.time_source or "无",
                strategy=parsed.strategy if parsed else "",
                unit=parsed.unit if parsed else "",
                species=dict(parsed.species) if parsed else {},
                metrics=_metrics_out(metrics) if metrics else None,
                warnings=_item_warnings(item),
            )
        )
    return BatchPreviewResponse(
        segments=len(result.items),
        valid=len(result.ok_items),
        items=items,
        warnings=list(result.warnings),
    )


def import_batch(
    text: str,
    start_time: str = "",
    interval_min: int = 0,
    batch_id: str = "",
) -> BatchImportResponse:
    _validate_start_time(start_time)
    result = batch_mod.parse_batch(
        text,
        start_time=start_time,
        interval_min=interval_min,
    )
    valid_items = result.ok_items
    if not valid_items:
        raise HTTPException(
            status_code=422,
            detail="没有解析出任何有效数据：" + "；".join(result.warnings),
        )

    batch_id = (batch_id or uuid.uuid4().hex[:12]).strip()
    warnings = list(result.warnings)
    records: list[history_mod.Record] = []
    source_indexes: list[int] = []
    previous_species: dict[str, float] | None = None

    for item in valid_items:
        parsed = item.parsed
        metrics = metrics_mod.compute(parsed.species)
        if metrics.species_count == 0 or metrics.total <= 0:
            warnings.append(f"第 {item.index} 段没有有效浓度，已跳过")
            continue
        if item.warning:
            warnings.append(f"第 {item.index} 段：{item.warning}")

        # 决策 A：批次内第一条不与批次外历史比较；之后和批次内上一条比较。
        changes = trend_mod.compute_changes(
            parsed.species,
            previous_species,
            None,
        )
        for change in changes.values():
            if change.source == "历史库":
                change.source = "批次"
        trends = trend_mod.detect_trends(changes)
        changes_list = [
            {
                "species": change.species,
                "pct": change.pct,
                "source": change.source,
                "text": change.text,
            }
            for change in changes.values()
        ]
        trends_list = [
            {
                "rule": hit.rule,
                "detail": hit.detail,
                "meaning": hit.meaning,
            }
            for hit in trends
        ]

        time_source = item.time_source or "无"
        if not item.sample_time:
            warnings.append(f"第 {item.index} 段没有采样时间")

        records.append(
            history_mod.Record(
                species=dict(parsed.species),
                unit=parsed.unit,
                sample_time=item.sample_time,
                time_source=time_source,
                total=metrics.total,
                species_count=metrics.species_count,
                shannon_h=metrics.shannon_h,
                metrics=_metrics_out(metrics).model_dump(),
                raw_text=item.text,
                changes=changes_list,
                trends=trends_list,
                batch_id=batch_id,
                batch_index=len(records) + 1,
            )
        )
        source_indexes.append(item.index)
        previous_species = dict(parsed.species)

    if not records:
        raise HTTPException(status_code=422, detail="没有可入库的有效记录")

    ids = history.save_many(records)
    imported: list[BatchImportItemOut] = []
    for source_index, rec, rec_id in zip(source_indexes, records, ids):
        imported.append(
            BatchImportItemOut(
                index=source_index,
                record_id=rec_id,
                sample_time=rec.sample_time,
                time_source=rec.time_source,
                metrics=_metrics_out(metrics_mod.compute(rec.species)),
            )
        )

    return BatchImportResponse(
        batch_id=batch_id,
        imported=len(imported),
        skipped=len(result.items) - len(valid_items),
        items=imported,
        warnings=warnings,
    )


def list_records(batch_id: str) -> BatchRecordsResponse:
    """返回批次内的本地结果，供前端做勾选和分析。"""
    records = history.by_batch(batch_id)
    if not records:
        raise HTTPException(status_code=404, detail=f"没有找到批次：{batch_id}")

    items: list[BatchRecordOut] = []
    for rec in records:
        metrics = metrics_mod.compute(rec.species) if rec.species else None
        items.append(
            BatchRecordOut(
                record_id=rec.id or 0,
                index=rec.batch_index,
                sample_time=rec.sample_time,
                time_source=rec.time_source,
                metrics=_metrics_out(metrics) if metrics else None,
                changes=[_change_out(item) for item in (rec.changes or [])],
                trends=[_trend_out(item) for item in (rec.trends or [])],
                has_report=bool(rec.report),
                analysis_source=rec.analysis_source,
                error_text=rec.error_text,
            )
        )
    return BatchRecordsResponse(
        batch_id=batch_id,
        count=len(items),
        records=items,
    )


def _analyze_at(
    records: list[history_mod.Record],
    target_index: int,
    batch_id: str,
) -> BatchAnalyzeLastResponse:
    """分析 records[target_index]；上下文只取它之前的记录。"""
    started = time.perf_counter()
    target = records[target_index]
    if not target.species:
        raise HTTPException(status_code=422, detail="目标记录没有有效物种浓度")

    prior = [rec for rec in records[:target_index] if rec.species]
    previous = prior[-1] if prior else None
    metrics = metrics_mod.compute(target.species)
    if metrics.species_count == 0 or metrics.total <= 0:
        raise HTTPException(status_code=422, detail="目标记录没有有效浓度")

    changes = trend_mod.compute_changes(
        target.species,
        previous.species if previous else None,
        None,
    )
    for change in changes.values():
        if change.source == "历史库":
            change.source = "批次"
    trends = trend_mod.detect_trends(changes)
    changes_list = [
        {
            "species": change.species,
            "pct": change.pct,
            "source": change.source,
            "text": change.text,
        }
        for change in changes.values()
    ]
    trends_list = [
        {
            "rule": hit.rule,
            "detail": hit.detail,
            "meaning": hit.meaning,
        }
        for hit in trends
    ]

    # 关键：只用目标之前的记录，绝不包含未来数据。
    context = build_batch_context(prior, batch_id)
    parsed = parser_mod.ParsedSample(
        species=dict(target.species),
        unit=target.unit,
    )
    previous_time = (
        (previous.sample_time or previous.imported_at) if previous else ""
    )
    metrics_snapshot = _metrics_out(metrics).model_dump()

    config = None
    model = ""
    try:
        config = config_store.default()
        model = config.model if config else ""
        analyzer = analyzer_mod.DeepSeekAnalyzer(config)
        analyzer.kb = knowledge_service
        payload = analyzer_mod.build_payload(
            parsed,
            metrics,
            changes,
            trends,
            previous_time,
            history_context=context,
        )
        case_context = case_service.context_for_payload(
            payload,
            exclude_ids={target.id} if target.id else set(),
        )
        if case_context:
            payload["history_context"] = (
                (payload.get("history_context") or "").strip()
                + "\n\n"
                + case_context
            ).strip()
        analysis = analyzer.analyze(payload)
    except Exception as exc:
        logger.exception("批次 %s 第 %s 条 AI 分析失败", batch_id, target.id)
        analysis = AnalysisResult(
            report="AI 分析失败，本次仅返回批次本地结果。",
            evaluations=[],
            source="错误",
            error=f"{type(exc).__name__}: {exc}",
        )

    history.update_analysis(
        target.id or 0,
        history_mod.Record(
            species=dict(target.species),
            unit=target.unit,
            sample_time=target.sample_time,
            time_source=target.time_source,
            batch_id=target.batch_id,
            batch_index=target.batch_index,
            total=metrics.total,
            species_count=metrics.species_count,
            shannon_h=metrics.shannon_h,
            metrics=metrics_snapshot,
            raw_text=target.raw_text,
            report=analysis.report,
            evaluations=[
                {
                    "species": item.species,
                    "comment": item.comment,
                    "advice": item.advice,
                }
                for item in analysis.evaluations
            ],
            changes=changes_list,
            trends=trends_list,
            analysis_source=analysis.source,
            error_text=analysis.error,
            references=analysis.references,
        ),
    )

    warnings: list[str] = []
    if analysis.error:
        warnings.append(analysis.error)
    degraded = bool(analysis.error) or analysis.source == "本地模拟"
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return BatchAnalyzeLastResponse(
        batch_id=batch_id,
        record_id=target.id or 0,
        sample_time=target.sample_time,
        time_source=target.time_source,
        status="degraded" if degraded else "success",
        degraded=degraded,
        metrics=_metrics_out(metrics),
        changes=[ChangeOut(**item) for item in changes_list],
        trends=[TrendOut(**item) for item in trends_list],
        evaluations=[
            EvaluationOut(
                species=item.species,
                comment=item.comment,
                advice=item.advice,
            )
            for item in analysis.evaluations
        ],
        report_text=analysis.report,
        warnings=warnings,
        references=analysis.references,
        history_context=context,
        meta={
            "model": model,
            "analysis_source": analysis.source,
            "elapsed_ms": elapsed_ms,
            "history_id": target.id,
            "batch_records": len(records),
            "target_index": target.batch_index,
            "previous_time": previous_time,
        },
    )


def analyze_record(batch_id: str, record_id: int) -> BatchAnalyzeLastResponse:
    records = history.by_batch(batch_id)
    if not records:
        raise HTTPException(status_code=404, detail=f"没有找到批次：{batch_id}")
    for index, rec in enumerate(records):
        if rec.id == record_id:
            return _analyze_at(records, index, batch_id)
    raise HTTPException(
        status_code=404,
        detail=f"批次 {batch_id} 中没有记录 {record_id}",
    )


def analyze_last(batch_id: str) -> BatchAnalyzeLastResponse:
    records = history.by_batch(batch_id)
    if not records:
        raise HTTPException(status_code=404, detail=f"没有找到批次：{batch_id}")
    for index in range(len(records) - 1, -1, -1):
        if records[index].species:
            return _analyze_at(records, index, batch_id)
    raise HTTPException(status_code=404, detail=f"批次 {batch_id} 没有有效记录")
