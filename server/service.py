"""把现有分析链路适配成 HTTP 服务。

对外只接收一段固定文本：
  表壳虫：2.15，匣壳虫：0.42，...

内部仍然走桌面端的同一条链路：
  parser -> 指标 -> 历史基准 -> 变化/趋势 -> 先存档 -> AI 两阶段 -> 回填存档
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime

from fastapi import HTTPException

from app import analyzer as analyzer_mod
from app import history as history_mod
from app import metrics as metrics_mod
from app import parser as parser_mod
from app import trend as trend_mod
from app.analyzer import AnalysisResult
from app.api_config import ApiConfigStore
from app.times import fmt, parse_dt
from server.case_service import case_service
from server.config import API_CONFIG_DB, HISTORY_DB
from server.knowledge import knowledge_service
from server.schemas import (
    ChangeOut,
    EvaluateResponse,
    EvaluationOut,
    MetricsOut,
    TrendOut,
)

logger = logging.getLogger("microbe.api")

history = history_mod.History(HISTORY_DB)
case_service.attach(history)
config_store = ApiConfigStore(API_CONFIG_DB)
try:
    config_store.seed_from_env()
except Exception:                       # 配置库不可写时仍允许启动，后续请求会给出错误
    logger.exception("API 配置库初始化失败：%s", API_CONFIG_DB)


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


def _normalize_sample_time(raw: str, source: str) -> tuple[str, str]:
    raw = (raw or "").strip()
    if not raw:
        return fmt(datetime.now()), "received"
    dt = parse_dt(raw)
    if dt is None:
        raise HTTPException(
            status_code=422,
            detail=f"采样时间无法识别：{raw}（建议 2026-11-11 08:00:00）",
        )
    return fmt(dt), source or "client"


def evaluate(
    text: str,
    sample_time: str = "",
    time_source: str = "received",
) -> EvaluateResponse:
    started = time.perf_counter()
    request_id = uuid.uuid4().hex
    sample_time, time_source = _normalize_sample_time(sample_time, time_source)

    parsed = parser_mod.parse(text)
    if not parsed.species:
        detail = "；".join(parsed.warnings) or "没有识别到任何物种数据"
        raise HTTPException(status_code=422, detail=f"文本解析失败：{detail}")

    metrics = metrics_mod.compute(parsed.species)
    if metrics.species_count == 0 or metrics.total <= 0:
        raise HTTPException(
            status_code=422,
            detail="没有可分析的有效物种浓度（浓度必须大于 0）",
        )

    last = history.previous_before(sample_time)
    changes = trend_mod.compute_changes(
        parsed.species,
        last.species if last else None,
        parsed.change or None,
    )
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

    # 与桌面端保持一致：先存一条“只有数据、没有报告”的记录。
    previous_time = (last.sample_time or last.imported_at) if last else ""
    metrics_snapshot = _metrics_out(metrics).model_dump()
    record_id = history.save(
        history_mod.Record(
            species=dict(parsed.species),
            unit=parsed.unit,
            sample_time=sample_time,
            time_source=time_source,
            total=metrics.total,
            species_count=metrics.species_count,
            shannon_h=metrics.shannon_h,
            metrics=metrics_snapshot,
            raw_text=text,
            changes=changes_list,
            trends=trends_list,
        )
    )

    config = None
    model = ""
    try:
        config = config_store.default()
        model = config.model if config else ""
        analyzer = analyzer_mod.DeepSeekAnalyzer(config)
        # 用运行时知识库（内置 + 用户导入）替换默认只读索引
        analyzer.kb = knowledge_service
        payload = analyzer_mod.build_payload(
            parsed, metrics, changes, trends, previous_time
        )
        # 历史案例只进提示词，不返回给客户端；用户点赞过的经验参考。
        case_context = case_service.context_for_payload(
            payload,
            exclude_ids={record_id},
        )
        if case_context:
            payload["history_context"] = (
                (payload.get("history_context") or "").strip()
                + "\n\n"
                + case_context
            ).strip()
        analysis = analyzer.analyze(payload)
    except Exception as exc:
        logger.exception("请求 %s 的 AI 分析失败", request_id)
        analysis = AnalysisResult(
            report="AI 分析失败，本次仅返回指标与趋势结果。",
            evaluations=[],
            source="错误",
            error=f"{type(exc).__name__}: {exc}",
        )

    history.update_analysis(
        record_id,
        history_mod.Record(
            species=dict(parsed.species),
            unit=parsed.unit,
            sample_time=sample_time,
            time_source=time_source,
            total=metrics.total,
            species_count=metrics.species_count,
            shannon_h=metrics.shannon_h,
            metrics=metrics_snapshot,
            raw_text=text,
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

    warnings = list(parsed.warnings)
    if analysis.error:
        warnings.append(analysis.error)

    degraded = bool(analysis.error) or analysis.source == "本地模拟"
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return EvaluateResponse(
        request_id=request_id,
        status="degraded" if degraded else "success",
        degraded=degraded,
        sample_time=sample_time,
        time_source=time_source,
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
        meta={
            "model": model,
            "analysis_source": analysis.source,
            "elapsed_ms": elapsed_ms,
            "history_id": record_id,
            "previous_time": previous_time,
        },
    )
