"""派生指标计算。

demo 阶段只做：物种数、Shannon 多样性指数 H'、相对丰度、优势种群、绝对优势种群。
阈值先写死，后期再开修改入口。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# 优势种：优势度 Y = (n_i / N) × f_i > 0.05
#   —— 《污水处理的生物相诊断》1.4.3
#   单样本检测时该物种要么出现（f=1）要么不出现，故 Y = 相对丰度。
#   将来若按多期数据算出现频率，把 freq 传进来即可。
THRESHOLD_DOMINANT = 0.05

# 绝对优势种群：本项目的自定义分档（该文献未定义），仍按 10%
THRESHOLD_ABSOLUTE = 0.10


@dataclass
class SpeciesMetric:
    name: str
    concentration: float
    relative: float          # 0~1
    dominance: float = 0.0   # Y = (n_i/N) × f_i

    @property
    def is_dominant(self) -> bool:
        return self.dominance > THRESHOLD_DOMINANT

    @property
    def is_absolute(self) -> bool:
        return self.relative >= THRESHOLD_ABSOLUTE

    @property
    def percent(self) -> float:
        return self.relative * 100


@dataclass
class MetricsResult:
    total: float
    species_count: int
    shannon_h: float
    rows: list[SpeciesMetric]        # 按浓度降序
    dominant: list[str]
    absolute: list[str]
    margalef_d: float = 0.0          # D = (S-1)/lnN
    pielou_j: float = 0.0            # J = H'/ln(S)


def compute(species: dict[str, float], freq: dict[str, float] | None = None) -> MetricsResult:
    """freq：各物种的出现频率 f_i（0~1）。单样本时缺省为 1.0。"""
    positive = {k: v for k, v in species.items() if v > 0}
    total = sum(positive.values())

    if total <= 0:
        return MetricsResult(0.0, 0, 0.0, [], [], [])

    freq = freq or {}
    rows = []
    for k, v in sorted(positive.items(), key=lambda x: -x[1]):
        rel = v / total
        rows.append(SpeciesMetric(name=k, concentration=v, relative=rel,
                                  dominance=rel * freq.get(k, 1.0)))

    s_count = len(rows)
    shannon = -sum(r.relative * math.log(r.relative) for r in rows if r.relative > 0)

    # Margalef 丰富度：D = (S-1)/lnN，N 为个体数（浓度按 10^6 个/L 换算成 个/L）
    n_individuals = total * 1_000_000
    margalef = (s_count - 1) / math.log(n_individuals) if s_count > 1 and n_individuals > 1 else 0.0
    # Pielou 均匀度：J = H'/ln(S)
    pielou = shannon / math.log(s_count) if s_count > 1 else 0.0

    return MetricsResult(
        total=total,
        species_count=s_count,
        shannon_h=round(shannon, 3),
        rows=rows,
        dominant=[r.name for r in rows if r.is_dominant],
        absolute=[r.name for r in rows if r.is_absolute],
        margalef_d=round(margalef, 3),
        pielou_j=round(pielou, 3),
    )
