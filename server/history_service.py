"""历史记录查询接口：桌面端 API 模式的数据来源。"""
from __future__ import annotations

from fastapi import HTTPException

from app import metrics as metrics_mod
from server.case_service import case_service
from server.schemas import (
    ChangeOut,
    EvaluationOut,
    HistoryDetailResponse,
    HistoryListItem,
    HistoryListResponse,
    MetricsOut,
    TrendOut,
    TrendPoint,
    TrendResponse,
)
from server.service import history


def _feedback(rec_id: int) -> str:
    item = history.get_feedback(rec_id)
    return str(item.get("verdict") or "") if item else ""


def list_history(limit: int = 100, offset: int = 0) -> HistoryListResponse:
    records = history.list_desc(limit=limit, offset=offset)
    items = [
        HistoryListItem(
            id=rec.id or 0,
            sample_time=rec.sample_time,
            imported_at=rec.imported_at,
            species_count=rec.species_count,
            total=rec.total,
            shannon_h=rec.shannon_h,
            has_report=bool(rec.report),
            analysis_source=rec.analysis_source,
            batch_id=rec.batch_id,
            feedback=_feedback(rec.id or 0),
        )
        for rec in records
    ]
    return HistoryListResponse(count=len(items), items=items)


def get_history(record_id: int) -> HistoryDetailResponse:
    rec = history.get(record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"记录不存在：{record_id}")
    if rec.metrics:
        metrics = MetricsOut(**rec.metrics)
    else:
        m = metrics_mod.compute(rec.species)
        metrics = MetricsOut(
            total=m.total,
            species_count=m.species_count,
            shannon_h=m.shannon_h,
            margalef_d=m.margalef_d,
            pielou_j=m.pielou_j,
            dominant=list(m.dominant),
            absolute=list(m.absolute),
        )
    return HistoryDetailResponse(
        id=rec.id or 0,
        sample_time=rec.sample_time,
        imported_at=rec.imported_at,
        unit=rec.unit,
        species=dict(rec.species),
        metrics=metrics,
        changes=[ChangeOut(**item) for item in (rec.changes or [])],
        trends=[TrendOut(**item) for item in (rec.trends or [])],
        evaluations=[
            EvaluationOut(
                species=str(item.get("species") or ""),
                comment=str(item.get("comment") or ""),
                advice=str(item.get("advice") or ""),
            )
            for item in (rec.evaluations or [])
        ],
        report_text=rec.report,
        raw_text=rec.raw_text,
        references=rec.references,
        analysis_source=rec.analysis_source,
        error_text=rec.error_text,
        batch_id=rec.batch_id,
        batch_index=rec.batch_index,
        time_source=rec.time_source,
        feedback=_feedback(rec.id or 0),
    )


def delete_history(record_id: int) -> dict:
    rec = history.get(record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"记录不存在：{record_id}")
    history.delete(record_id)
    case_service.reload()
    return {"status": "ok", "record_id": record_id}


def trends(limit: int = 500) -> TrendResponse:
    records = history.recent(limit=limit)
    return TrendResponse(
        count=len(records),
        points=[
            TrendPoint(
                id=rec.id or 0,
                sample_time=rec.sample_time,
                species=dict(rec.species),
                total=rec.total,
                species_count=rec.species_count,
                shannon_h=rec.shannon_h,
            )
            for rec in records
        ],
    )
