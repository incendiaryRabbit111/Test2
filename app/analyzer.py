"""AI 分析：两阶段串联。

  阶段一：为本次检出的**每一个**物种生成简短评价（只讲指示意义，不科普"这是什么虫"）
  阶段二：把阶段一的**全部评价**喂回去，综合成一份整体判断
          —— 重点是提炼多个物种**共同指向**的问题（比如多条评价都提到溶解氧偏低）

设计要点：
  · 不做"查表"——甲方给的 xlsx 只是格式典范，内容不进提示词
  · 两阶段是**先后关系**，阶段二必须看到阶段一的产出
  · 一次 analyze() 发两次 API 请求
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TEMPERATURE = 0.2          # 结论稳定性优先；想更灵活可调到 0.4

SYSTEM_PROMPT = """你是污水处理厂活性污泥微生物镜检分析专家，精通各类指示生物在活性污泥法工艺判断中的意义。你服务的对象是专业人员，不需要科普基础概念。"""

# ---------------- 阶段一：逐物种评价 ----------------
STAGE1_TEMPLATE = """【本次检测数据】
浓度单位：{unit}
物种种类数：{species_count}
多样性指数 H'：{h}（均匀度 {evenness}）
优势种群（相对丰度≥3%）：{dominant}
绝对优势种群（相对丰度≥10%）：{absolute}

各物种浓度与相对丰度（按浓度降序，共 {species_count} 种）：
{species_table}

【任务】为上面**每一个**物种写一条评价，两部分都要短：

· comment（综合评价，40~60 字）：直接讲这个物种**出现、或占到这么高比例，意味着什么水质或工艺状况**
  （有机负荷、溶解氧、污泥龄、污泥解体、出水水质等），可顺带点一句本次数量在群落中的地位。
  **不要介绍这个物种本身是什么**——使用者是专业人员，默认他们知道。

· advice（指导意见，15~30 字）：一条具体、可操作的工艺建议。

【输出格式】只输出 JSON：
{{
  "species_evaluations": [
    {{"species": "物种名", "comment": "…", "advice": "…"}}
  ]
}}

【硬性要求】
1. 必须覆盖上面列出的每一个物种，一个都不能少，顺序一致；
2. 依据该物种真实的指示意义作答，把握不大就用"常见于…""通常与…相关"这类保守表述，不要编造；
3. 如果某物种的「较上次变化」幅度显著（绝对值 ≥ 30%），或是本次新检出 / 本次消失，
   要在评价里点出这个变化及其含义；没有变化数据时不必强行提及；
4. 只输出 JSON，不要用 markdown 代码块包裹，不要有任何其它文字。"""

# ---------------- 阶段二：综合报告 ----------------
STAGE2_TEMPLATE = """【本次检测概要】
物种种类数：{species_count}
多样性指数 H'：{h}（均匀度 {evenness}）
优势种群：{dominant}
绝对优势种群：{absolute}

【本次较上次的变化】
{changes}

【命中的趋势规则】
{trends}

【上一步生成的逐物种评价】
{evaluations}

【任务】
把这些零散的单物种评价，综合成一份整体判断。

**最关键的要求**：要主动找出多个物种**共同指向**的问题。
例如有多条评价都提到"溶解氧偏低""污泥龄偏长""有机负荷偏高"，就把这一点单独提炼出来、
明确指出它是本次的主要矛盾；不要只是把各物种结论罗列一遍。

【输出格式】严格按下面两段式，每一条各占一行，不要用 markdown 符号、不要加编号或小标题：

情况：<一行，150~200 字。说明整体污泥状态、有机负荷水平、溶解氧状况、出水水质趋势，并明确指出主导因素>
变化：<一行，120 字以内。说明与上次相比哪些物种发生了显著变化、命中了哪些趋势规则、意味着什么，并给出趋势判断。
       **如果上面没有提供变化数据，就不要输出这一行**>
建议：<一条建议，20~40 字>
建议：<一条建议，20~40 字>

（建议 2~4 条，每条单独一行。只依据上面给出的信息，不要编造任何数值）"""


@dataclass
class SpeciesEval:
    species: str
    comment: str
    advice: str = ""


@dataclass
class AnalysisResult:
    report: str = ""
    evaluations: list[SpeciesEval] = field(default_factory=list)
    source: str = "本地模拟"
    error: str = ""

    def eval_map(self) -> dict[str, SpeciesEval]:
        return {e.species: e for e in self.evaluations}


class DeepSeekAnalyzer:
    """通用「OpenAI 兼容」客户端（类名沿用，兼容旧调用）。

    DeepSeek / 通义 / Kimi / 智谱 / Ollama / LM Studio / vLLM 都是这套协议，
    差别只在 base_url + model + key。
    """

    def __init__(self, config=None, model: str | None = None) -> None:
        if config is None:
            from app.api_config import ApiConfig
            config = ApiConfig.from_env()
        self.config = config
        self.api_key = (config.api_key if config else "").strip()
        # model 可以为单次调用覆盖（同一个网关切不同模型）
        self.model = (model or (config.model if config else "")).strip()
        self.base_url = (config.base_url if config else "").strip()
        self.timeout = config.timeout if config else 180
        self.temperature = config.temperature if config else TEMPERATURE

    @property
    def is_live(self) -> bool:
        # 本地模型（Ollama）允许任意 key，所以不再校验 sk- 前缀
        return bool(self.api_key and self.base_url and self.model)

    @property
    def mode_text(self) -> str:
        if not self.is_live:
            return "本地模拟（未配置 API）"
        name = (self.config.name if self.config else "") or "API"
        return f"{name}（{self.model}）"

    # ---------------- 底层调用 ----------------
    def _chat(self, user_prompt: str, json_mode: bool = False, max_tokens: int = 8000) -> tuple[str, str]:
        """返回 (内容, 错误信息)。"""
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            resp = self._post(body)
            # 有些模型不支持 json_object，去掉该参数再试一次
            if json_mode and resp.status_code != 200:
                body.pop("response_format", None)
                resp = self._post(body)
            if resp.status_code != 200:
                return "", f"API 返回 {resp.status_code}：{resp.text[:200]}"
            return resp.json()["choices"][0]["message"]["content"].strip(), ""
        except Exception as exc:
            return "", f"{type(exc).__name__}：{exc}"

    def _post(self, body: dict):
        return requests.post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json=body,
            timeout=self.timeout,
        )

    def test_connection(self) -> tuple[bool, str]:
        """给配置界面用的连通性测试。"""
        if not self.is_live:
            return False, "配置不完整：base_url / 模型名 / API Key 都要填"
        text, err = self._chat("只回复两个字：收到", json_mode=False, max_tokens=16)
        if err:
            return False, err
        return True, f"连接成功，模型回复「{text[:30]}」"

    @staticmethod
    def _parse_json(content: str) -> dict | None:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
            text = re.sub(r"```\s*$", "", text).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                return None
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None

    # ---------------- 提示词 ----------------
    @staticmethod
    def _species_table(payload: dict) -> str:
        lines = []
        for r in payload["rows"]:
            flag = "　[绝对优势]" if r["absolute"] else ("　[优势]" if r["dominant"] else "")
            chg = r.get("change_text", "—")
            lines.append(f"  {r['name']}：浓度 {r['concentration']:.3f}，"
                         f"相对丰度 {r['percent']:.2f}%{flag}　较上次 {chg}")
        return "\n".join(lines) or "  （无）"

    @classmethod
    def build_stage1_prompt(cls, payload: dict) -> str:
        return STAGE1_TEMPLATE.format(
            unit=payload["unit"] or "未提供",
            species_count=payload["species_count"],
            h=payload["h"],
            evenness=payload["evenness"],
            dominant="、".join(payload["dominant"]) or "（无）",
            absolute="、".join(payload["absolute"]) or "（无）",
            species_table=cls._species_table(payload),
        )

    @staticmethod
    def _changes_text(payload: dict) -> str:
        rows = [r for r in payload["rows"] if r.get("change_pct") is not None]
        extra = [r for r in payload["rows"] if r.get("change_text") in ("本次未检出", "上次未检出", "上次为0，新检出")]
        if not rows and not extra:
            return "  （没有可用的变化数据——历史库无上一条记录，文本里也没有「较上次变化」字段）"
        lines = [f"  数据来源：{payload['rows'][0].get('change_source', '无')}（上一条记录时间：{payload.get('previous_time') or '—'}）"]
        for r in sorted(rows, key=lambda x: -abs(x["change_pct"]))[:12]:
            lines.append(f"  {r['name']}：{r['change_pct']:+.1f}%（本次 {r['concentration']:.3f}）")
        for r in extra:
            lines.append(f"  {r['name']}：{r['change_text']}")
        return "\n".join(lines)

    @staticmethod
    def _trends_text(payload: dict) -> str:
        hits = payload.get("trends") or []
        if not hits:
            return "  （本次没有命中任何趋势规则）"
        return "\n".join(f"  · {h['rule']}：{h['detail']} → {h['meaning']}" for h in hits)

    @staticmethod
    def build_stage2_prompt(payload: dict, evaluations: list[SpeciesEval]) -> str:
        pct = {r["name"]: r["percent"] for r in payload["rows"]}
        flag = {r["name"]: ("，绝对优势" if r["absolute"] else ("，优势" if r["dominant"] else "")) for r in payload["rows"]}
        text = "\n".join(
            f"{e.species}（相对丰度 {pct.get(e.species, 0):.2f}%{flag.get(e.species, '')}）\n"
            f"    综合评价：{e.comment}\n"
            f"    指导意见：{e.advice}"
            for e in evaluations
        )
        return STAGE2_TEMPLATE.format(
            changes=DeepSeekAnalyzer._changes_text(payload),
            trends=DeepSeekAnalyzer._trends_text(payload),
            species_count=payload["species_count"],
            h=payload["h"],
            evenness=payload["evenness"],
            dominant="、".join(payload["dominant"]) or "（无）",
            absolute="、".join(payload["absolute"]) or "（无）",
            evaluations=text,
        )

    # ---------------- 主流程 ----------------
    def analyze(self, payload: dict) -> AnalysisResult:
        if not self.is_live:
            return self._mock(payload, "未配置 DEEPSEEK_API_KEY")

        # —— 阶段一 ——
        content, err = self._chat(self.build_stage1_prompt(payload), json_mode=True)
        if not content:
            return self._mock(payload, err)
        data = self._parse_json(content)
        if data is None:
            return self._mock(payload, "阶段一返回的不是合法 JSON")

        evals = [
            SpeciesEval(
                species=str(it.get("species", "")).strip(),
                comment=str(it.get("comment", "")).strip(),
                advice=str(it.get("advice", "")).strip(),
            )
            for it in data.get("species_evaluations", [])
            if it.get("species")
        ]
        if not evals:
            return self._mock(payload, "阶段一没有返回任何物种评价")

        # —— 阶段二（必须看到阶段一的产出）——
        report, err2 = self._chat(
            self.build_stage2_prompt(payload, evals), json_mode=False, max_tokens=1500
        )
        if not report:
            report = self._fallback_report(payload, evals)
            err2 = err2 or "阶段二调用失败，已用本地模板兜底"

        return AnalysisResult(report=report, evaluations=evals, source="DeepSeek", error=err or err2)

    # ---------------- 兜底 ----------------
    @staticmethod
    def _fallback_report(payload: dict, evals: list[SpeciesEval]) -> str:
        top = payload["rows"][0] if payload["rows"] else None
        lines = [
            f"情况：本次共检出 {payload['species_count']} 种微生物，多样性指数 H' 为 {payload['h']}"
            f"（均匀度 {payload['evenness']}）。"
            + (f"第一优势种为 {top['name']}，相对丰度 {top['percent']:.1f}%。" if top else "")
        ]
        for e in evals[:3]:
            lines.append(f"建议：{e.advice}" if e.advice else f"建议：关注{e.species}的变化趋势。")
        lines.append("（阶段二综合失败，以上建议由逐物种结果直接汇总，未经融合提炼。）")
        return "\n".join(lines)

    @staticmethod
    def _mock(payload: dict, reason: str = "") -> AnalysisResult:
        rows = payload["rows"]
        evals = []
        for r in rows:
            rank = "绝对优势种" if r["absolute"] else ("优势种" if r["dominant"] else "少见种")
            evals.append(SpeciesEval(
                species=r["name"],
                comment=f"本次相对丰度 {r['percent']:.1f}%，属{rank}。（模拟模式未接入大模型）",
                advice="配置 DEEPSEEK_API_KEY 后可获得工艺建议。",
            ))
        lines = [
            f"情况：本次共检出 {payload['species_count']} 种微生物，多样性指数 H' 为 {payload['h']}，"
            f"均匀度 {payload['evenness']}。"
            + (f"第一优势种为 {rows[0]['name']}，相对丰度 {rows[0]['percent']:.1f}%。" if rows else "")
            + "（本地模拟结果，未接入大模型。）"
        ]
        return AnalysisResult(report="\n".join(lines), evaluations=evals, source="本地模拟", error=reason)


def build_payload(parsed, metrics, changes: dict | None = None,
                  trends: list | None = None, previous_time: str = "") -> dict:
    import math
    s = metrics.species_count
    h_max = round(math.log(s), 3) if s > 1 else 0.0
    evenness = round(metrics.shannon_h / h_max, 3) if h_max else 0.0
    changes = changes or {}
    rows = []
    for r in metrics.rows:
        ch = changes.get(r.name)
        rows.append({
            "name": r.name, "concentration": r.concentration, "percent": r.percent,
            "dominant": r.is_dominant, "absolute": r.is_absolute,
            "change_pct": ch.pct if ch else None,
            "change_text": ch.text if ch else "—",
            "change_source": ch.source if ch else "无",
        })
    return {
        "unit": parsed.unit,
        "species_count": s,
        "h": metrics.shannon_h,
        "h_max": h_max,
        "evenness": evenness,
        "dominant": metrics.dominant,
        "absolute": metrics.absolute,
        "previous_time": previous_time,
        "rows": rows,
        "changes": [
            {"species": c.species, "pct": c.pct, "source": c.source}
            for c in changes.values() if c.pct is not None
        ],
        "trends": [
            {"rule": t.rule, "detail": t.detail, "meaning": t.meaning} for t in (trends or [])
        ],
    }
