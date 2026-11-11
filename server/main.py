"""FastAPI 入口。

启动：
    .venv\\Scripts\\python.exe -m server

本机验证：
    http://127.0.0.1:8000/health
    http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import Body, Depends, FastAPI, File, Header, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from starlette.exceptions import HTTPException as StarletteHTTPException

from server.batch_service import (
    analyze_last,
    analyze_record,
    import_batch,
    list_records,
    preview,
)
from server.case_service import case_service, report_hash
from server.config import API_KEY, APP_NAME, DATA_DIR, VERSION
from server.history_service import delete_history, get_history, list_history, trends
from server.knowledge import MAX_PDF_BYTES, knowledge_service
from server.schemas import (
    BatchAnalyzeLastResponse,
    BatchImportResponse,
    BatchPreviewResponse,
    BatchRecordsResponse,
    EvaluateResponse,
    FeedbackRequest,
    FeedbackResponse,
    HistoryDetailResponse,
    HistoryListResponse,
    KnowledgeImportResponse,
    KnowledgeListResponse,
    KnowledgeSearchItem,
    KnowledgeSearchResponse,
    KnowledgeStatusOut,
    KnowledgeTextRequest,
    TrendResponse,
)
from server.service import evaluate, history

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("microbe.api")

OPENAPI_TAGS = [
    {
        "name": "system",
        "description": "服务健康检查。",
    },
    {
        "name": "analysis",
        "description": "单条固定文本分析：解析、指标、趋势、AI 评价和报告。",
    },
    {
        "name": "batch",
        "description": "批量导入：先本地计算并入库，最后可只对最后一条调用 AI。",
    },
    {
        "name": "history",
        "description": "历史记录与用户反馈：点赞/点踩、历史案例入库与移除。",
    },
    {
        "name": "knowledge",
        "description": "用户知识库：导入文字/文字版 PDF、查看、检索和删除。",
    },
]

API_DESCRIPTION = """
## 特征微生物分析 API

接收仪器/用户输入的固定文本，返回指标、趋势、逐物种评价和综合报告。

### 快速开始

1. 先调用 `GET /health` 确认服务正常。
2. 单条分析用 `POST /api/v1/evaluate`。
3. 批量数据用 `POST /api/v1/batch/preview` 预览，再 `POST /api/v1/batch/import` 入库。
4. 需要 AI 时，用 `POST /api/v1/batch/{batch_id}/analyze-last` 只分析最后一条。
5. 用户知识用 `/api/v1/knowledge/*`。
6. 桌面端 API 模式用 `/api/v1/history` 和 `/api/v1/trends`。
7. 点赞/点踩用 `POST /api/v1/history/{record_id}/feedback`，只有点赞会进入内部案例库。

### 鉴权

如果后端启动时设置了 `MICROBE_API_KEY`，请求需要带：

```http
X-API-Key: 你的令牌
```

本机开发未设置 Key 时，可以不填。

### 请求格式

- 单条/批量评价：`Content-Type: text/plain`，正文是固定文本。
- 知识文字：`Content-Type: application/json`。
- PDF：`multipart/form-data`，字段名 `file`。

> `/docs` 是开发调试页；正式客户端请按接口合同调用，不需要解析本页面。
"""

app = FastAPI(
    title=APP_NAME,
    version=VERSION,
    description=API_DESCRIPTION,
    openapi_tags=OPENAPI_TAGS,
    contact={"name": "特征微生物分析工具"},
    license_info={"name": "内部使用"},
    swagger_ui_parameters={
        "defaultModelsExpandDepth": -1,
        "defaultModelExpandDepth": 1,
        "docExpansion": "list",
        "filter": True,
        "displayRequestDuration": True,
        "tryItOutEnabled": True,
        "persistAuthorization": True,
        "deepLinking": True,
        "displayOperationId": False,
        "syntaxHighlight.theme": "obsidian",
    },
)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(provided: str | None = Depends(api_key_header)) -> None:
    """本机开发默认不校验；设置 MICROBE_API_KEY 后启用。"""
    if API_KEY and provided != API_KEY:
        raise StarletteHTTPException(status_code=401, detail="API Key 无效或缺失")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("%s %s 未处理异常", request.method, request.url.path)
        raise
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "%s %s -> %s (%.0fms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "请求参数不合法",
                "details": jsonable_encoder(exc.errors()),
            },
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        code = "UNAUTHORIZED"
    elif exc.status_code == 422:
        code = "VALIDATION_ERROR"
    else:
        code = "HTTP_ERROR"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "error": {
                "code": code,
                "message": str(exc.detail),
                "details": [],
            },
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("未处理异常：%s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务内部错误，请查看后端日志",
                "details": [],
            },
        },
    )


@app.get("/health", tags=["system"])
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "name": APP_NAME,
        "version": VERSION,
        "data_dir": str(DATA_DIR),
    }


@app.post(
    "/api/v1/evaluate",
    response_model=EvaluateResponse,
    tags=["analysis"],
    summary="提交一段固定格式文本并返回评价建议",
)
def evaluate_text(
    text: str = Body(
        ...,
        media_type="text/plain",
        description=(
            "仪器/用户输入的固定文本，例如："
            "表壳虫：2.15，匣壳虫：0.42，内管虫：0.31"
        ),
    ),
    sample_time: str = "",
    x_sample_time: str | None = Header(default=None, alias="X-Sample-Time"),
    _: None = Depends(verify_api_key),
) -> EvaluateResponse:
    raw_time = (sample_time or x_sample_time or "").strip()
    return evaluate(
        text,
        sample_time=raw_time,
        time_source="client" if raw_time else "received",
    )


@app.post(
    "/api/v1/batch/preview",
    response_model=BatchPreviewResponse,
    tags=["batch"],
    summary="预览批量文本的解析和本地指标，不写库",
)
def batch_preview(
    text: str = Body(..., media_type="text/plain"),
    start_time: str = "",
    interval_min: int = 0,
    _: None = Depends(verify_api_key),
) -> BatchPreviewResponse:
    if interval_min < 0:
        raise StarletteHTTPException(status_code=422, detail="interval_min 不能为负数")
    return preview(text, start_time=start_time, interval_min=interval_min)


@app.post(
    "/api/v1/batch/import",
    response_model=BatchImportResponse,
    tags=["batch"],
    summary="批量导入本地数据，不调用 AI",
)
def batch_import(
    text: str = Body(..., media_type="text/plain"),
    start_time: str = "",
    interval_min: int = 0,
    batch_id: str = "",
    _: None = Depends(verify_api_key),
) -> BatchImportResponse:
    if interval_min < 0:
        raise StarletteHTTPException(status_code=422, detail="interval_min 不能为负数")
    return import_batch(
        text,
        start_time=start_time,
        interval_min=interval_min,
        batch_id=batch_id,
    )


@app.get(
    "/api/v1/batch/{batch_id}/records",
    response_model=BatchRecordsResponse,
    tags=["batch"],
    summary="查看批次内的本地结果和 AI 状态",
)
def batch_records(
    batch_id: str,
    _: None = Depends(verify_api_key),
) -> BatchRecordsResponse:
    return list_records(batch_id)


@app.post(
    "/api/v1/batch/{batch_id}/analyze-last",
    response_model=BatchAnalyzeLastResponse,
    tags=["batch"],
    summary="只对批次最后一条调用 AI，前面各条只使用本地结果",
)
def batch_analyze_last(
    batch_id: str,
    _: None = Depends(verify_api_key),
) -> BatchAnalyzeLastResponse:
    return analyze_last(batch_id)


@app.post(
    "/api/v1/batch/{batch_id}/analyze/{record_id}",
    response_model=BatchAnalyzeLastResponse,
    tags=["batch"],
    summary="分析批次内指定的一条记录（历史上下文只取它之前的数据）",
)
def batch_analyze_record(
    batch_id: str,
    record_id: int,
    _: None = Depends(verify_api_key),
) -> BatchAnalyzeLastResponse:
    return analyze_record(batch_id, record_id)


@app.get(
    "/api/v1/history",
    response_model=HistoryListResponse,
    tags=["history"],
    summary="历史记录列表（桌面端 API 模式用）",
)
def history_list(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: None = Depends(verify_api_key),
) -> HistoryListResponse:
    return list_history(limit=limit, offset=offset)


@app.get(
    "/api/v1/history/{record_id}",
    response_model=HistoryDetailResponse,
    tags=["history"],
    summary="历史记录详情",
)
def history_detail(
    record_id: int,
    _: None = Depends(verify_api_key),
) -> HistoryDetailResponse:
    return get_history(record_id)


@app.delete(
    "/api/v1/history/{record_id}",
    tags=["history"],
    summary="删除历史记录，并同步移除对应历史案例",
)
def history_delete(
    record_id: int,
    _: None = Depends(verify_api_key),
) -> dict:
    return delete_history(record_id)


@app.get(
    "/api/v1/trends",
    response_model=TrendResponse,
    tags=["history"],
    summary="趋势图数据（按时间升序）",
)
def history_trends(
    limit: int = Query(500, ge=1, le=2000),
    _: None = Depends(verify_api_key),
) -> TrendResponse:
    return trends(limit=limit)


@app.post(
    "/api/v1/history/{record_id}/feedback",
    response_model=FeedbackResponse,
    tags=["history"],
    summary="对整份分析报告点赞或点踩；只有点赞会进入历史案例库",
)
def set_history_feedback(
    record_id: int,
    body: FeedbackRequest,
    _: None = Depends(verify_api_key),
) -> FeedbackResponse:
    record = history.get(record_id)
    if record is None:
        raise StarletteHTTPException(status_code=404, detail=f"记录不存在：{record_id}")
    if body.verdict == "up" and not record.report.strip():
        raise StarletteHTTPException(status_code=422, detail="该记录还没有分析报告，不能点赞")
    if body.verdict == "up" and record.analysis_source in ("错误", "本地模拟"):
        raise StarletteHTTPException(
            status_code=422,
            detail="该记录不是真实 AI 成功结果，不能进入历史案例库",
        )
    digest = report_hash(record.report)
    history.set_feedback(record_id, body.verdict, body.note, digest)
    case_service.reload()
    feedback = history.get_feedback(record_id) or {}
    return FeedbackResponse(
        record_id=record_id,
        verdict=body.verdict,
        report_hash=digest,
        updated_at=str(feedback.get("updated_at") or ""),
    )


@app.delete(
    "/api/v1/history/{record_id}/feedback",
    tags=["history"],
    summary="撤销点赞/点踩，并从历史案例库移除",
)
def delete_history_feedback(
    record_id: int,
    _: None = Depends(verify_api_key),
) -> dict:
    if history.get(record_id) is None:
        raise StarletteHTTPException(status_code=404, detail=f"记录不存在：{record_id}")
    history.delete_feedback(record_id)
    case_service.reload()
    return {"status": "ok", "record_id": record_id}


@app.post(
    "/api/v1/knowledge/text",
    response_model=KnowledgeImportResponse,
    tags=["knowledge"],
    summary="导入一段纯文字知识",
)
def import_knowledge_text(
    payload: KnowledgeTextRequest,
    _: None = Depends(verify_api_key),
) -> KnowledgeImportResponse:
    try:
        result = knowledge_service.add_text(payload.title, payload.content)
    except ValueError as exc:
        raise StarletteHTTPException(status_code=422, detail=str(exc)) from exc
    return KnowledgeImportResponse(**result)


@app.post(
    "/api/v1/knowledge/pdf",
    response_model=KnowledgeImportResponse,
    tags=["knowledge"],
    summary="导入文字版 PDF 知识",
)
async def import_knowledge_pdf(
    file: UploadFile = File(...),
    _: None = Depends(verify_api_key),
) -> KnowledgeImportResponse:
    data = await file.read(MAX_PDF_BYTES + 1)
    await file.close()
    if len(data) > MAX_PDF_BYTES:
        raise StarletteHTTPException(
            status_code=413,
            detail=f"PDF 过大（上限 {MAX_PDF_BYTES // 1024 // 1024} MB）",
        )
    try:
        result = knowledge_service.add_pdf(file.filename or "", data)
    except ValueError as exc:
        raise StarletteHTTPException(status_code=422, detail=str(exc)) from exc
    return KnowledgeImportResponse(**result)


@app.get(
    "/api/v1/knowledge",
    response_model=KnowledgeListResponse,
    tags=["knowledge"],
    summary="查看已导入知识",
)
def list_knowledge(_: None = Depends(verify_api_key)) -> KnowledgeListResponse:
    return KnowledgeListResponse(
        documents=knowledge_service.list_documents(),
        status=knowledge_service.status(),
    )


@app.get(
    "/api/v1/knowledge/status",
    response_model=KnowledgeStatusOut,
    tags=["knowledge"],
    summary="知识库状态",
)
def knowledge_status(_: None = Depends(verify_api_key)) -> KnowledgeStatusOut:
    return KnowledgeStatusOut(**knowledge_service.status())


@app.get(
    "/api/v1/knowledge/search",
    response_model=KnowledgeSearchResponse,
    tags=["knowledge"],
    summary="调试：检索知识库",
)
def search_knowledge(
    q: str,
    top_k: int = 6,
    _: None = Depends(verify_api_key),
) -> KnowledgeSearchResponse:
    top_k = max(1, min(top_k, 20))
    refs = knowledge_service.search(q, top_k=top_k)
    return KnowledgeSearchResponse(
        query=q,
        results=[
            KnowledgeSearchItem(
                label=ref.label,
                book=ref.book,
                author=ref.author,
                page_start=ref.page_start,
                page_end=ref.page_end,
                text=ref.text,
                score=ref.score,
            )
            for ref in refs
        ],
    )


@app.delete(
    "/api/v1/knowledge/{doc_id}",
    tags=["knowledge"],
    summary="删除用户导入的一篇知识",
)
def delete_knowledge(
    doc_id: str,
    _: None = Depends(verify_api_key),
) -> dict[str, Any]:
    if not knowledge_service.delete_document(doc_id):
        raise StarletteHTTPException(status_code=404, detail="没有找到这篇知识")
    return {"status": "ok", "deleted": doc_id, "knowledge": knowledge_service.status()}
