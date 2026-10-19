"""变化计算 + 趋势规则判断。

趋势规则来自甲方 xlsx 的「变化趋势指示性判断」表，阈值照原表：

  1. 楯纤虫急速变少   本次数量较上次减少 70%~100%
  2. 钟虫急速变少     本次数量较上次减少 70%~100%
  3. 轮虫变多         本次数量较上次增加大于 300%
  4. 游泳纤毛虫占比变多  占比较上次增加大于 50%   ← 需要「物种→生态类群」对照表，暂缺
  5. 固着纤毛虫占比变多  占比较上次增加大于 50%   ← 同上

规则命中与否是**确定性判断**（纯阈值），命中的规则再交给 AI 写评价，
所以这里只负责"检测"，不负责"解释"。
"""
from __future__ import annotations

from dataclasses import dataclass

DECREASE_LO, DECREASE_HI = 70.0, 100.0     # 减少 70%~100%
ROTIFER_INCREASE_MIN = 300.0               # 增加 > 300%
GROUP_INCREASE_MIN = 50.0                  # 占比增加 > 50%（暂未启用）

SPECIES_RULES = [
    {"name": "楯纤虫急速变少", "species": "楯纤虫", "kind": "decrease",
     "lo": DECREASE_LO, "hi": DECREASE_HI, "meaning": "可能存在负荷过高或毒物流入"},
    {"name": "钟虫急速变少", "species": "钟虫", "kind": "decrease",
     "lo": DECREASE_LO, "hi": DECREASE_HI, "meaning": "可能存在负荷过高或毒物流入"},
    {"name": "轮虫变多", "species": "轮虫", "kind": "increase",
     "min": ROTIFER_INCREASE_MIN, "meaning": "污泥解体加剧"},
]

PENDING_RULES = [
    {"name": "游泳纤毛虫占比变多", "reason": "需要「物种 → 生态类群」对照表"},
    {"name": "固着纤毛虫占比变多", "reason": "需要「物种 → 生态类群」对照表"},
]


@dataclass
class Change:
    species: str
    current: float
    previous: float | None      # None = 历史库里没有该物种
    pct: float | None           # 变化率(%)；None = 算不出来
    source: str                 # "历史库" / "文本自带" / "无"
    note: str = ""

    @property
    def text(self) -> str:
        if self.pct is None:
            return self.note or "—"
        return f"{self.pct:+.1f}%"


@dataclass
class TrendHit:
    rule: str
    detail: str
    meaning: str


def compute_changes(
    current: dict[str, float],
    previous: dict[str, float] | None = None,
    fallback: dict[str, float] | None = None,
) -> dict[str, Change]:
    """逐物种算变化。

    previous —— 历史库里上一条记录的物种浓度（方案 B，优先）
    fallback —— 文本自带的"较上次变化"百分比（方案 A，兜底）
    """
    result: dict[str, Change] = {}

    if previous:
        for name, cur in current.items():
            prev = previous.get(name)
            if prev is None:
                result[name] = Change(name, cur, None, None, "历史库", "上次未检出")
            elif prev > 0:
                result[name] = Change(name, cur, prev, (cur - prev) / prev * 100, "历史库")
            elif cur > 0:
                result[name] = Change(name, cur, 0.0, None, "历史库", "上次为0，新检出")
            else:
                result[name] = Change(name, cur, 0.0, 0.0, "历史库")
        # 本次消失、但上次有的物种
        for name, prev in previous.items():
            if name not in current and prev > 0:
                result[name] = Change(name, 0.0, prev, -100.0, "历史库", "本次未检出")
        return result

    if fallback:
        for name, cur in current.items():
            pct = fallback.get(name)
            if pct is None:
                result[name] = Change(name, cur, None, None, "无", "文本未提供")
            else:
                prev = cur / (1 + pct / 100) if pct != -100 else None
                result[name] = Change(name, cur, prev, pct, "文本自带")
        return result

    for name, cur in current.items():
        result[name] = Change(name, cur, None, None, "无", "无对比数据")
    return result


def detect_trends(changes: dict[str, Change]) -> list[TrendHit]:
    """按 xlsx 里的阈值判断哪些趋势规则被命中。"""
    hits: list[TrendHit] = []
    for rule in SPECIES_RULES:
        ch = changes.get(rule["species"])
        if ch is None or ch.pct is None:
            continue
        pct = ch.pct
        if rule["kind"] == "decrease":
            if -rule["hi"] <= pct <= -rule["lo"]:
                hits.append(TrendHit(
                    rule=rule["name"],
                    detail=f"{rule['species']} 较上次减少 {abs(pct):.1f}%（阈值 -{rule['lo']:.0f}%~-{rule['hi']:.0f}%）",
                    meaning=rule["meaning"],
                ))
        elif rule["kind"] == "increase":
            if pct > rule["min"]:
                hits.append(TrendHit(
                    rule=rule["name"],
                    detail=f"{rule['species']} 较上次增加 {pct:.1f}%（阈值 >{rule['min']:.0f}%）",
                    meaning=rule["meaning"],
                ))
    return hits
