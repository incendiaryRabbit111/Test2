"""API 调试客户端。

不依赖 Qt，只负责 HTTP 请求和错误转换，方便单独测试。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import requests


class ApiError(Exception):
    """带 HTTP 状态和响应内容的可读错误。"""

    def __init__(self, message: str, status: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload


class ApiClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: int = 120) -> None:
        base_url = (base_url or "").strip().rstrip("/")
        if base_url and not base_url.startswith(("http://", "https://")):
            base_url = "http://" + base_url
        self.base_url = base_url
        self.api_key = (api_key or "").strip()
        self.timeout = timeout
        # 调试客户端不读取系统代理，避免本机/LAN 请求被代理劫持
        self.session = requests.Session()
        self.session.trust_env = False

    def _headers(self, json_body: bool = False) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _request(self, method: str, path: str, **kwargs) -> Any:
        if not self.base_url:
            raise ApiError("API 地址为空")
        url = self.base_url + path
        try:
            response = self.session.request(
                method,
                url,
                timeout=kwargs.pop("timeout", self.timeout),
                **kwargs,
            )
        except requests.RequestException as exc:
            raise ApiError(f"连接失败：{type(exc).__name__}：{exc}") from exc

        try:
            data = response.json()
        except ValueError:
            data = None

        if not response.ok:
            message = ""
            if isinstance(data, dict):
                error = data.get("error")
                if isinstance(error, dict):
                    message = str(error.get("message") or "")
                if not message:
                    message = str(data.get("detail") or "")
            if not message:
                message = (response.text or "").strip()[:300]
            raise ApiError(
                f"HTTP {response.status_code}：{message or '请求失败'}",
                status=response.status_code,
                payload=data,
            )
        return data

    # ---------------- 业务接口 ----------------
    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health", timeout=10)

    def evaluate(self, text: str, sample_time: str = "") -> dict[str, Any]:
        params = {"sample_time": sample_time} if sample_time.strip() else None
        return self._request(
            "POST",
            "/api/v1/evaluate",
            params=params,
            data=text.encode("utf-8"),
            headers={
                **self._headers(),
                "Content-Type": "text/plain; charset=utf-8",
            },
            timeout=120,
        )

    def history(self, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v1/history",
            params={"limit": limit, "offset": offset},
            headers=self._headers(),
        )

    def history_detail(self, record_id: int) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/v1/history/{record_id}",
            headers=self._headers(),
        )

    def delete_history(self, record_id: int) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/api/v1/history/{record_id}",
            headers=self._headers(),
        )

    def trends(self, limit: int = 500) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v1/trends",
            params={"limit": limit},
            headers=self._headers(),
        )

    def feedback(self, record_id: int, verdict: str, note: str = "") -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/history/{record_id}/feedback",
            json={"verdict": verdict, "note": note},
            headers=self._headers(json_body=True),
        )

    def delete_feedback(self, record_id: int) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/api/v1/history/{record_id}/feedback",
            headers=self._headers(),
        )

    def import_text(self, title: str, content: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/knowledge/text",
            json={"title": title, "content": content},
            headers=self._headers(json_body=True),
            timeout=120,
        )

    def import_pdf(self, path: str | Path) -> dict[str, Any]:
        file_path = Path(path)
        if not file_path.exists():
            raise ApiError(f"文件不存在：{file_path}")
        with file_path.open("rb") as fh:
            files = {"file": (file_path.name, fh, "application/pdf")}
            return self._request(
                "POST",
                "/api/v1/knowledge/pdf",
                files=files,
                headers=self._headers(),
                timeout=180,
            )

    def list_knowledge(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/knowledge", headers=self._headers())

    def delete_knowledge(self, doc_id: str) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/api/v1/knowledge/{doc_id}",
            headers=self._headers(),
        )
