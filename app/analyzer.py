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
from datetime import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests

from app.paths import ROOT
from app.rag import KnowledgeBase, build_query, format_context, mark_cited
TEMPERATURE = 0.2          # 结论稳定性优先；想更灵活可调到 0.4

SYSTEM_PROMPT = """你是污水处理厂活性污泥微生物镜检分析专家，精通各类指示生物在活性污泥法工艺判断中的意义。你服务的对象是专业人员，不需要科普基础概念。"""

# ---------------- 阶段一：逐物种评价 ----------------
STAGE1_TEMPLATE = """【本次检测数据】
浓度单位：{unit}
物种种类数：{species_count}
Shannon 多样性 H'：{h}｜Pielou 均匀度 J：{evenness}｜Margalef 丰富度 D：{d}
优势种群（相对丰度≥3%）：{dominant}
绝对优势种群（相对丰度≥10%）：{absolute}

各物种浓度与相对丰度（按浓度降序，共 {species_count} 种）：
{species_table}

【参考资料（来自专业书籍与文献，可能相关）】
{reference_block}

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
4. 如果使用了参考资料中的具体结论，在 comment 末尾用 [R1] 这样的编号标注来源；
   没有使用就不要标注。只能引用上面列出的编号，不要编造资料中没有的内容；
5. 只输出 JSON，不要用 markdown 代码块包裹，不要有任何其它文字。"""

# ---------------- 阶段二：综合报告 ----------------
STAGE2_TEMPLATE = """【本次检测概要】
物种种类数：{species_count}
Shannon 多样性 H'：{h}｜Pielou 均匀度 J：{evenness}｜Margalef 丰富度 D：{d}
优势种群：{dominant}
绝对优势种群：{absolute}

【本次较上次的变化】
{changes}

【命中的趋势规则】
{trends}

【上一步生成的逐物种评价】
{evaluations}

【参考资料（来自专业书籍与文献，可能相关）】
{reference_block}

【任务】
把这些零散的单物种评价，综合成一份整体判断。

判断群落结构时，请在「情况」里结合 H'、J、D 三个指数说明：
J 偏低说明群落被少数种垄断，D 偏低说明种类贫乏，二者与 H' 合起来反映系统稳定性。

**最关键的要求**：要主动找出多个物种**共同指向**的问题。
例如有多条评价都提到"溶解氧偏低""污泥龄偏长""有机负荷偏高"，就把这一点单独提炼出来、
明确指出它是本次的主要矛盾；不要只是把各物种结论罗列一遍。

【输出格式】严格按下面两段式，每一条各占一行，不要用 markdown 符号、不要加编号或小标题：

情况：<一行，150~200 字。说明整体污泥状态、有机负荷水平、溶解氧状况、出水水质趋势，并明确指出主导因素>
变化：<一行，120 字以内。说明与上次相比哪些物种发生了显著变化、命中了哪些趋势规则、意味着什么，并给出趋势判断。
       **如果上面没有提供变化数据，就不要输出这一行**>
建议：<一条建议，20~40 字>
建议：<一条建议，20~40 字>

（建议 2~4 条，每条单独一行。只依据上面给出的信息，不要编造任何数值。
  如果某条判断引用了参考资料，在句末标注 [R1] 这样的编号；没有引用就不要标注。
        引用时只写「据《书名》第X页」+ 一句话概括，**不要摘抄原文段落**。）"""


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
    references: list[dict] = field(default_factory=list)

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
        self.kb = KnowledgeBase()

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
    def _chat(self, user_prompt: str, json_mode: bool = False,
              max_tokens: int = 8000, label: str = "") -> tuple[str, str]:
        """返回 (内容, 错误信息)。

        容错顺序：
          1. 带 response_format 请求
          2. 若「非 200」**或「200 但正文为空」** → 去掉 response_format 再试一次
             （很多中转站不认识这个参数，会返回 200 + content=null 而不是报错）
          3. 仍然失败 → 返回可读的错误，并把原始响应 dump 到 data/last_error.txt
        """
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
        except Exception as exc:
            msg = f"网络错误：{type(exc).__name__}：{exc}"
            self._dump(label, body, None, msg)
            return "", msg

        content, err = self._extract(resp, allow_reasoning=json_mode)

        # 关键修复：不仅"非 200"要重试，"200 但空正文"也要重试
        if json_mode and (err or not content):
            body.pop("response_format", None)
            try:
                resp = self._post(body)
            except Exception as exc:
                msg = f"网络错误：{type(exc).__name__}：{exc}"
                self._dump(label, body, None, msg)
                return "", msg
            retry_content, retry_err = self._extract(resp, allow_reasoning=False)
            if retry_content:
                content, err = retry_content, ""
            elif not err:
                err = retry_err

        if content:
            return content, ""

        msg = err or self._empty_hint(resp)
        self._dump(label, body, resp, msg)
        return "", msg

    @staticmethod
    def _extract(resp, allow_reasoning: bool = False) -> tuple[str, str]:
        """从响应里抠出正文。返回 (content, 错误信息)。"""
        if resp.status_code != 200:
            return "", f"HTTP {resp.status_code}：{(resp.text or '')[:300]}"
        try:
            data = resp.json()
        except Exception:
            return "", f"返回的不是 JSON：{(resp.text or '')[:300]}"
        if not isinstance(data, dict):
            return "", f"返回结构异常：{str(data)[:200]}"

        choices = data.get("choices") or []
        if not choices:
            return "", f"返回里没有 choices：{str(data)[:300]}"
        message = choices[0].get("message") or {}

        content = message.get("content")
        if isinstance(content, list):          # 多模态分段格式
            buf = []
            for part in content:
                if isinstance(part, dict):
                    buf.append(part.get("text") or "")
                elif isinstance(part, str):
                    buf.append(part)
            content = "".join(buf)
        content = (content or "").strip()

        if not content and allow_reasoning:
            # 推理模型：正文为空，但思考过程里有内容（JSON 阶段可以抢救）
            content = (message.get("reasoning_content") or "").strip()

        return content, ""

    @staticmethod
    def _empty_hint(resp) -> str:
        """正文为空时，给出能直接定位原因的提示。"""
        usage, finish = "", ""
        try:
            data = resp.json()
            u = data.get("usage") or {}
            bits = []
            if u.get("prompt_tokens") is not None:
                bits.append(f"prompt={u.get('prompt_tokens')}")
            if u.get("completion_tokens") is not None:
                bits.append(f"completion={u.get('completion_tokens')}")
            detail = u.get("completion_tokens_details") or {}
            if detail.get("reasoning_tokens"):
                bits.append(f"reasoning={detail['reasoning_tokens']}")
            usage = "，".join(bits)
            finish = str((data.get("choices") or [{}])[0].get("finish_reason") or "")
        except Exception:
            pass

        msg = "模型返回了空正文（HTTP 200，但 content 为空）"
        if usage:
            msg += f"\n用量：{usage}" + (f"｜finish_reason={finish}" if finish else "")
        if finish == "length":
            msg += ("\n→ 输出被 max_tokens 截断：推理模型会先消耗 reasoning tokens。"
                    "请在「API 设置」把超时/预算调大，或改用非推理模型。")
        else:
            msg += ("\n→ 可能原因：① 推理模型把 token 花在思考上；"
                    "② 中转站不支持某些参数；③ 该服务只支持流式返回。")
        return msg

    def _dump(self, label: str, body: dict, resp, err: str) -> None:
        """把出错时的原始响应写进 data/last_error.txt，方便排查中转站。"""
        try:
            path = ROOT / "data" / "last_error.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            brief = {k: v for k, v in body.items() if k != "messages"}
            lines = [
                f"时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
                f"阶段：{label or '未标注'}",
                f"URL：{self.base_url.rstrip('/')}/chat/completions",
                f"模型：{self.model}",
                f"请求参数：{json.dumps(brief, ensure_ascii=False)}",
                f"messages 条数：{len(body.get('messages') or [])}",
                "",
                "---- 错误 ----",
                err,
            ]
            if resp is not None:
                lines += ["", f"---- HTTP {resp.status_code} 原始响应（前 4000 字）----",
                          (resp.text or "")[:4000]]
            path.write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            pass

    def _post(self, body: dict):
        return requests.post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json=body,
            timeout=self.timeout,
        )

    def test_connection(self) -> tuple[bool, str]:
        """给配置界面用的连通性测试。

        注意：**HTTP 200 就算连通**，即使正文是空的（推理模型很常见）。
        """
        if not self.is_live:
            return False, "配置不完整：base_url / 模型名 / API Key 都要填"
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": "只回复两个字：收到"}],
            "temperature": 0,
            "max_tokens": 256,
        }
        try:
            resp = self._post(body)
        except Exception as exc:
            return False, f"网络错误：{type(exc).__name__}：{exc}"

        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}：{(resp.text or '')[:200]}"

        content, err = self._extract(resp, allow_reasoning=True)
        if content:
            return True, f"连接成功，模型回复「{content[:30]}」"
        if err:
            return False, err
        return True, ("连接成功（HTTP 200），但模型没返回正文——可能是推理模型，"
                      "实际分析时请留意 max_tokens 是否够用")

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
    def build_stage1_prompt(cls, payload: dict, reference_block: str = "（无）") -> str:
        return STAGE1_TEMPLATE.format(
            unit=payload["unit"] or "未提供",
            species_count=payload["species_count"],
            h=payload["h"],
            evenness=payload["evenness"],
            d=payload.get("d", 0.0),
            dominant="、".join(payload["dominant"]) or "（无）",
            absolute="、".join(payload["absolute"]) or "（无）",
            species_table=cls._species_table(payload),
            reference_block=reference_block or "（无）",
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
    def build_stage2_prompt(
        payload: dict,
        evaluations: list[SpeciesEval],
        reference_block: str = "（无）",
    ) -> str:
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
            d=payload.get("d", 0.0),
            dominant="、".join(payload["dominant"]) or "（无）",
            absolute="、".join(payload["absolute"]) or "（无）",
            evaluations=text,
            reference_block=reference_block or "（无）",
        )

    # ---------------- 主流程 ----------------
    def analyze(self, payload: dict) -> AnalysisResult:
        refs = []
        reference_block = "（无）"
        if self.kb.available:
            refs = self.kb.search(build_query(payload), top_k=6)
            if refs:
                reference_block = format_context(refs)

        if not self.is_live:
            return self._mock(payload, "未配置 DEEPSEEK_API_KEY", refs)

        # —— 阶段一 ——
        content, err = self._chat(
            self.build_stage1_prompt(payload, reference_block), json_mode=True,
            max_tokens=8000, label="阶段一：逐物种评价")
        if not content:
            return self._mock(payload, err, refs)
        data = self._parse_json(content)
        if data is None:
            return self._mock(payload, "阶段一返回的不是合法 JSON", refs)

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
            return self._mock(payload, "阶段一没有返回任何物种评价", refs)

        # —— 阶段二（必须看到阶段一的产出）——
        report, err2 = self._chat(
            self.build_stage2_prompt(payload, evals, reference_block), json_mode=False,
            max_tokens=4000, label="阶段二：综合报告",
        )
        if not report:
            report = self._fallback_report(payload, evals)
            err2 = err2 or "阶段二调用失败，已用本地模板兜底"

        if refs:
            mark_cited(refs, content, report)
        return AnalysisResult(
            report=report,
            evaluations=evals,
            source="DeepSeek",
            error=err or err2,
            references=[r.to_dict() for r in refs],
        )

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

    def _mock(self, payload: dict, reason: str = "", refs=None) -> AnalysisResult:
        refs = refs or []
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
        return AnalysisResult(
            report="\n".join(lines),
            evaluations=evals,
            source="本地模拟",
            error=reason,
            references=[r.to_dict() for r in refs],
        )


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
        "evenness": metrics.pielou_j or evenness,
        "d": metrics.margalef_d,
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
