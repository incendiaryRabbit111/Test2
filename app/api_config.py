"""AI API 配置：增删改查 + 默认项。

只支持「OpenAI 兼容」一种协议——DeepSeek / 通义 / Kimi / 智谱 /
Ollama / LM Studio / vLLM 都是这套，覆盖 95% 的场景。

配置存在 data/api_configs.db，API Key 用 DPAPI 加密。
如果一条配置都没有，会回退读 .env（保证老环境不坏）。
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "api_configs.db"

# 新增配置时的预填项
PRESETS = [
    {"name": "DeepSeek", "base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
    {"name": "通义千问", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "model": "qwen-plus"},
    {"name": "Kimi", "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    {"name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash"},
    {"name": "本地 Ollama", "base_url": "http://localhost:11434/v1", "model": "qwen2.5:14b"},
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_configs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    base_url    TEXT    NOT NULL,
    model       TEXT    NOT NULL,
    api_key_enc TEXT    NOT NULL DEFAULT '',
    temperature REAL    NOT NULL DEFAULT 0.2,
    timeout     INTEGER NOT NULL DEFAULT 180,
    is_default  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT
);
"""

_COLS = ("id, name, base_url, model, models_json, api_key_enc, temperature, timeout, is_default")


@dataclass
class ApiConfig:
    id: int | None = None
    name: str = ""
    base_url: str = ""
    model: str = ""                # 主模型（= models[0]）
    models: list[str] = field(default_factory=list)   # 该网关下可切换的全部模型
    api_key: str = ""              # 内存中是明文
    temperature: float = 0.2
    timeout: int = 180
    is_default: bool = False
    source: str = "db"             # db / env

    def normalize(self) -> None:
        """保证 models 和 model 一致：model 永远是 models[0]。"""
        self.models = [m.strip() for m in self.models if m and m.strip()]
        if self.model and self.model not in self.models:
            self.models.insert(0, self.model)
        if not self.model and self.models:
            self.model = self.models[0]
        # 去重保序
        seen, uniq = set(), []
        for m in self.models:
            if m not in seen:
                seen.add(m)
                uniq.append(m)
        self.models = uniq
        if self.models:
            self.model = self.models[0]

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)

    @property
    def masked_key(self) -> str:
        from app.secure_store import mask
        return mask(self.api_key)

    @property
    def label(self) -> str:
        return f"{self.name}（{self.model}）" if self.name else self.model

    # ---------------- 从 .env 兜底 ----------------
    @classmethod
    def from_env(cls) -> "ApiConfig | None":
        env_file = ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not key:
            return None
        return cls(
            name=".env", base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat").strip(),
            api_key=key, source="env",
        )


def fetch_models(base_url: str, api_key: str, timeout: int = 20) -> tuple[list[str], str]:
    """调 GET {base_url}/models 拉取该 key 可用的模型清单。

    OpenAI 兼容接口都支持这个端点（DeepSeek / Ollama / vLLM / 多数国内厂商）。
    返回 (模型列表, 错误信息)。
    """
    import requests

    if not base_url:
        return [], "Base URL 为空"
    url = base_url.rstrip("/") + "/models"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=timeout,
        )
    except Exception as exc:
        return [], f"{type(exc).__name__}：{exc}"

    if resp.status_code != 200:
        return [], f"HTTP {resp.status_code}：{resp.text[:150]}"
    try:
        data = resp.json()
    except Exception:
        return [], "返回的不是 JSON"

    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return [], "返回格式里没有 data 列表"
    ids = [str(m.get("id")) for m in items if isinstance(m, dict) and m.get("id")]
    if not ids:
        return [], "没有取到任何模型"
    return ids, ""


class ApiConfigStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(api_configs)")}
            if "models_json" not in cols:
                conn.execute("ALTER TABLE api_configs ADD COLUMN models_json TEXT")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------------- 读 ----------------
    def all(self) -> list[ApiConfig]:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM api_configs ORDER BY is_default DESC, id ASC").fetchall()
        return [self._to_config(r) for r in rows]

    def get(self, cid: int) -> ApiConfig | None:
        with self._conn() as conn:
            row = conn.execute(f"SELECT {_COLS} FROM api_configs WHERE id=?", (cid,)).fetchone()
        return self._to_config(row) if row else None

    def default(self) -> ApiConfig | None:
        """默认配置；库里没有就回退 .env；都没有返回 None。"""
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT {_COLS} FROM api_configs WHERE is_default=1 LIMIT 1").fetchone()
            if row is None:
                row = conn.execute(f"SELECT {_COLS} FROM api_configs LIMIT 1").fetchone()
        if row:
            return self._to_config(row)
        return ApiConfig.from_env()

    def count(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM api_configs").fetchone()[0])

    # ---------------- 写 ----------------
    def save(self, cfg: ApiConfig) -> int:
        from app.secure_store import encrypt
        cfg.normalize()
        enc = encrypt(cfg.api_key)
        models_json = json.dumps(cfg.models, ensure_ascii=False)
        with self._conn() as conn:
            if cfg.id is None:
                cur = conn.execute(
                    "INSERT INTO api_configs(name, base_url, model, models_json, api_key_enc,"
                    " temperature, timeout, is_default, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (cfg.name, cfg.base_url, cfg.model, models_json, enc,
                     cfg.temperature, cfg.timeout, 1 if cfg.is_default else 0,
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                cfg.id = int(cur.lastrowid or 0)
            else:
                conn.execute(
                    "UPDATE api_configs SET name=?, base_url=?, model=?, models_json=?, api_key_enc=?,"
                    " temperature=?, timeout=?, is_default=? WHERE id=?",
                    (cfg.name, cfg.base_url, cfg.model, models_json, enc,
                     cfg.temperature, cfg.timeout, 1 if cfg.is_default else 0, cfg.id))
        if cfg.is_default:
            self.set_default(cfg.id)
        return cfg.id or 0

    def set_default(self, cid: int) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE api_configs SET is_default=0")
            conn.execute("UPDATE api_configs SET is_default=1 WHERE id=?", (cid,))

    def delete(self, cid: int) -> int:
        with self._conn() as conn:
            was_default = conn.execute(
                "SELECT is_default FROM api_configs WHERE id=?", (cid,)).fetchone()
            n = conn.execute("DELETE FROM api_configs WHERE id=?", (cid,)).rowcount
            if was_default and was_default[0]:
                first = conn.execute(
                    f"SELECT id FROM api_configs ORDER BY id LIMIT 1").fetchone()
                if first:
                    conn.execute("UPDATE api_configs SET is_default=1 WHERE id=?", (first[0],))
            return n

    # ---------------- 首次运行：把 .env 里的 key 导进来 ----------------
    def seed_from_env(self) -> ApiConfig | None:
        if self.count() > 0:
            return None
        env_cfg = ApiConfig.from_env()
        if env_cfg is None:
            return None
        env_cfg.name = "DeepSeek"
        env_cfg.is_default = True
        env_cfg.source = "db"
        self.save(env_cfg)
        return env_cfg

    # ---------------- 转换 ----------------
    @staticmethod
    def _to_config(row) -> ApiConfig:
        from app.secure_store import decrypt
        try:
            models = json.loads(row[4]) if row[4] else []
        except (json.JSONDecodeError, TypeError):
            models = []
        cfg = ApiConfig(
            id=row[0], name=row[1], base_url=row[2], model=row[3], models=models,
            api_key=decrypt(row[5] or ""), temperature=row[6],
            timeout=row[7], is_default=bool(row[8]), source="db",
        )
        cfg.normalize()
        return cfg
