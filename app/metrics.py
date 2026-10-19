"""派生指标计算。

demo 阶段只做：物种数、Shannon 多样性指数 H'、相对丰度、优势种群、绝对优势种群。
阈值先写死，后期再开修改入口。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

THRESHOLD_DOMINANT = 0.03   # 优势种群：相对丰度 >= 3%
THRESHOLD_ABSOLUTE = 0.10   # 绝对优势种群：相对丰度 >= 10%


@dataclass
class SpeciesMetric:
    name: str
    concentration: float
    relative: float          # 0~1

    @property
    def is_dominant(self) -> bool:
        return self.relative >= THRESHOLD_DOMINANT

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


def compute(species: dict[str, float]) -> MetricsResult:
    positive = {k: v for k, v in species.items() if v > 0}
    total = sum(positive.values())

    if total <= 0:
        return MetricsResult(0.0, 0, 0.0, [], [], [])

    rows = [
        SpeciesMetric(name=k, concentration=v, relative=v / total)
        for k, v in sorted(positive.items(), key=lambda x: -x[1])
    ]

    shannon = -sum(r.relative * math.log(r.relative) for r in rows if r.relative > 0)

    return MetricsResult(
        total=total,
        species_count=len(rows),
        shannon_h=round(shannon, 3),
        rows=rows,
        dominant=[r.name for r in rows if r.is_dominant],
        absolute=[r.name for r in rows if r.is_absolute],
    )
