"""API 模式下的历史数据适配器。

界面只依赖 History 的常用方法：count/all_desc/get/delete/recent/last。
这里把 HTTP 响应转换成现有 Record，避免大改界面展示代码。
"""
from __future__ import annotations

from app.api_client import ApiClient
from app.history import Record


class ApiHistory:
    def __init__(self, client: ApiClient) -> None:
        self.client = client
        self._cache: list[Record] = []

    @staticmethod
    def _from_list_item(item: dict) -> Record:
        return Record(
            id=int(item.get("id") or 0),
            sample_time=str(item.get("sample_time") or ""),
            imported_at=str(item.get("imported_at") or ""),
            total=float(item.get("total") or 0.0),
            species_count=int(item.get("species_count") or 0),
            shannon_h=float(item.get("shannon_h") or 0.0),
            report="已分析" if item.get("has_report") else "",
            analysis_source=str(item.get("analysis_source") or ""),
            batch_id=str(item.get("batch_id") or ""),
            feedback=str(item.get("feedback") or ""),
        )

    @staticmethod
    def _from_detail(data: dict) -> Record:
        return Record(
            id=int(data.get("id") or 0),
            sample_time=str(data.get("sample_time") or ""),
            imported_at=str(data.get("imported_at") or ""),
            unit=str(data.get("unit") or ""),
            total=float((data.get("metrics") or {}).get("total") or 0.0),
            species_count=int((data.get("metrics") or {}).get("species_count") or 0),
            shannon_h=float((data.get("metrics") or {}).get("shannon_h") or 0.0),
            species=dict(data.get("species") or {}),
            report=str(data.get("report_text") or ""),
            raw_text=str(data.get("raw_text") or ""),
            evaluations=list(data.get("evaluations") or []),
            changes=list(data.get("changes") or []),
            trends=list(data.get("trends") or []),
            analysis_source=str(data.get("analysis_source") or ""),
            error_text=str(data.get("error_text") or ""),
            references=list(data.get("references") or []),
            batch_id=str(data.get("batch_id") or ""),
            batch_index=int(data.get("batch_index") or 0),
            time_source=str(data.get("time_source") or ""),
            metrics=dict(data.get("metrics") or {}),
            feedback=str(data.get("feedback") or ""),
        )

    @staticmethod
    def _from_trend_point(point: dict) -> Record:
        return Record(
            id=int(point.get("id") or 0),
            sample_time=str(point.get("sample_time") or ""),
            total=float(point.get("total") or 0.0),
            species_count=int(point.get("species_count") or 0),
            shannon_h=float(point.get("shannon_h") or 0.0),
            species=dict(point.get("species") or {}),
        )

    def refresh(self) -> None:
        data = self.client.history(limit=500)
        self._cache = [
            self._from_list_item(item) for item in (data.get("items") or [])
        ]

    def count(self) -> int:
        self.refresh()
        return len(self._cache)

    def all_desc(self) -> list[Record]:
        self.refresh()
        return list(self._cache)

    def get(self, rec_id: int) -> Record | None:
        try:
            return self._from_detail(self.client.history_detail(rec_id))
        except Exception:
            return None

    def delete(self, rec_id: int) -> int:
        self.client.delete_history(rec_id)
        self._cache = [rec for rec in self._cache if rec.id != rec_id]
        return 1

    def recent(self, limit: int = 500) -> list[Record]:
        data = self.client.trends(limit=limit)
        return [self._from_trend_point(p) for p in (data.get("points") or [])]

    def last(self) -> Record | None:
        records = self.all_desc()
        return records[0] if records else None

    def set_feedback(self, rec_id: int, verdict: str, note: str = "") -> dict:
        return self.client.feedback(rec_id, verdict, note)

    def delete_feedback(self, rec_id: int) -> dict:
        return self.client.delete_feedback(rec_id)
