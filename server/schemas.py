"""API 响应模型。

第一版只接受仪器/用户输入的固定文本，不要求客户端拆成 JSON 对象。
分析结果保留现有桌面端的全部字段，方便前端按需展示。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class MetricsOut(BaseModel):
    total: float
    species_count: int
    shannon_h: float
    margalef_d: float
    pielou_j: float
    dominant: list[str]
    absolute: list[str]


class ChangeOut(BaseModel):
    species: str
    pct: float | None
    text: str
    source: str


class TrendOut(BaseModel):
    rule: str
    detail: str
    meaning: str


class EvaluationOut(BaseModel):
    species: str
    comment: str
    advice: str


class EvaluateResponse(BaseModel):
    request_id: str
    status: Literal["success", "degraded"]
    degraded: bool
    sample_time: str
    time_source: str
    batch_id: str = ""
    batch_index: int = 0
    metrics: MetricsOut
    changes: list[ChangeOut]
    trends: list[TrendOut]
    evaluations: list[EvaluationOut]
    report_text: str
    warnings: list[str]
    references: list[dict[str, Any]]
    meta: dict[str, Any]


class BatchItemOut(BaseModel):
    index: int
    valid: bool
    sample_time: str
    time_source: str
    strategy: str
    unit: str
    species: dict[str, float]
    metrics: MetricsOut | None
    warnings: list[str]


class BatchPreviewResponse(BaseModel):
    segments: int
    valid: int
    items: list[BatchItemOut]
    warnings: list[str]


class BatchImportItemOut(BaseModel):
    index: int
    record_id: int
    sample_time: str
    time_source: str
    metrics: MetricsOut


class BatchImportResponse(BaseModel):
    batch_id: str
    imported: int
    skipped: int
    items: list[BatchImportItemOut]
    warnings: list[str]


class BatchAnalyzeLastResponse(BaseModel):
    batch_id: str
    record_id: int
    sample_time: str
    time_source: str
    status: Literal["success", "degraded"]
    degraded: bool
    metrics: MetricsOut
    changes: list[ChangeOut]
    trends: list[TrendOut]
    evaluations: list[EvaluationOut]
    report_text: str
    warnings: list[str]
    references: list[dict[str, Any]]
    history_context: str
    meta: dict[str, Any]


class FeedbackRequest(BaseModel):
    verdict: Literal["up", "down"]
    note: str = Field(default="", max_length=1000)


class FeedbackResponse(BaseModel):
    record_id: int
    verdict: Literal["up", "down"]
    report_hash: str
    updated_at: str


class BatchRecordOut(BaseModel):
    record_id: int
    index: int
    sample_time: str
    time_source: str
    metrics: MetricsOut | None
    changes: list[ChangeOut]
    trends: list[TrendOut]
    has_report: bool
    analysis_source: str
    error_text: str


class BatchRecordsResponse(BaseModel):
    batch_id: str
    count: int
    records: list[BatchRecordOut]


class HistoryListItem(BaseModel):
    id: int
    sample_time: str
    imported_at: str
    species_count: int
    total: float
    shannon_h: float
    has_report: bool
    analysis_source: str
    batch_id: str
    feedback: str


class HistoryListResponse(BaseModel):
    count: int
    items: list[HistoryListItem]


class HistoryDetailResponse(BaseModel):
    id: int
    sample_time: str
    imported_at: str
    unit: str
    species: dict[str, float]
    metrics: MetricsOut | None
    changes: list[ChangeOut]
    trends: list[TrendOut]
    evaluations: list[EvaluationOut]
    report_text: str
    raw_text: str
    references: list[dict[str, Any]]
    analysis_source: str
    error_text: str
    batch_id: str
    batch_index: int
    time_source: str
    feedback: str


class TrendPoint(BaseModel):
    id: int
    sample_time: str
    species: dict[str, float]
    total: float
    species_count: int
    shannon_h: float


class TrendResponse(BaseModel):
    count: int
    points: list[TrendPoint]


class KnowledgeTextRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100, description="知识标题")
    content: str = Field(min_length=1, max_length=200_000, description="知识正文")


class KnowledgeDocOut(BaseModel):
    id: str
    title: str
    kind: str
    pages: int
    chunks: int
    created_at: str


class KnowledgeImportResponse(BaseModel):
    document: KnowledgeDocOut
    status: dict[str, Any]


class KnowledgeListResponse(BaseModel):
    documents: list[KnowledgeDocOut]
    status: dict[str, Any]


class KnowledgeStatusOut(BaseModel):
    available: bool
    builtin_chunks: int
    user_chunks: int
    documents: int
    total_chunks: int
    last_updated: str


class KnowledgeSearchItem(BaseModel):
    label: str
    book: str
    author: str
    page_start: int
    page_end: int
    text: str
    score: float


class KnowledgeSearchResponse(BaseModel):
    query: str
    results: list[KnowledgeSearchItem]
