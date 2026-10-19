"""【预留模块 —— 当前流程不使用】

甲方给的 xlsx 是**格式典范**，不是查询字典。当前做法是让 AI 从生物学出发
为每个物种生成评价（见 analyzer.py），所以这里不参与主流程。

保留本模块的原因：甲方提到后期数据积累多了要把这类对照表"存档数据库"，
届时这个加载器可以直接复用。现在它只做一件事：把 xlsx 解析成内存结构。

--- 原始说明 ---
知识图谱：加载 xls，把物种/趋势映射到「综合评价 + 指导意见」。

匹配规则按原表表头来：
  · 原生动物表 表头是"绝对优势物种" -> 用【绝对优势种群】去匹配
  · 后生动物表 表头是"出现物种"     -> 用【本次出现的物种】去匹配
  · 变化趋势表 本轮 demo 不启用（阈值未定）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

SECTION_KEYS = {
    "原生动物指示性判断": "原生动物",
    "后生动物指示性判断": "后生动物",
    "变化趋势指示性判断": "变化趋势",
}


@dataclass
class Judgment:
    key: str          # 物种名 / 趋势名
    comment: str      # 综合评价
    advice: str       # 指导意见
    source: str       # 原生动物 / 后生动物 / 变化趋势


@dataclass
class KnowledgeBase:
    protozoa: dict[str, Judgment] = field(default_factory=dict)
    metazoa: dict[str, Judgment] = field(default_factory=dict)
    trends: dict[str, Judgment] = field(default_factory=dict)
    notes: str = ""

    @property
    def all_species(self) -> set[str]:
        return set(self.protozoa) | set(self.metazoa)


@dataclass
class MatchResult:
    matched: list[Judgment]           # 命中知识图谱的条目
    uncovered: list[str]              # 本次出现但图谱里没有的物种
    present_metazoa: list[str]        # 本次出现的后生动物


def _clean(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def load(path: str | Path) -> KnowledgeBase:
    df = pd.read_excel(path, sheet_name=0, header=None)
    kb = KnowledgeBase()
    current = None

    for _, row in df.iterrows():
        c0, c1, c2, c3 = (_clean(row.get(i)) for i in range(4))

        if c0 in SECTION_KEYS:
            current = SECTION_KEYS[c0]
            continue
        if c0.startswith("注：") or c0.startswith("注:"):
            kb.notes = c0
            continue
        if not c0.isdigit() or not c1:
            continue

        item = Judgment(key=c1, comment=c2, advice=c3, source=current or "未知")
        if current == "原生动物":
            kb.protozoa[c1] = item
        elif current == "后生动物":
            kb.metazoa[c1] = item
        elif current == "变化趋势":
            kb.trends[c1] = item

    return kb


def match(kb: KnowledgeBase, absolute_dominant: list[str], present_species: list[str]) -> MatchResult:
    matched: list[Judgment] = []

    # 原生动物：用绝对优势种群去匹配
    for name in absolute_dominant:
        if name in kb.protozoa:
            matched.append(kb.protozoa[name])

    # 后生动物：本次出现的物种即可匹配
    present_metazoa = [s for s in present_species if s in kb.metazoa]
    for name in present_metazoa:
        matched.append(kb.metazoa[name])

    uncovered = [
        s for s in present_species
        if s not in kb.protozoa and s not in kb.metazoa
    ]
    return MatchResult(matched=matched, uncovered=uncovered, present_metazoa=present_metazoa)
