"""把仪器输出的一段文本解析成结构化检测数据。

只用"物种名 + 浓度 + 单位"这组保底信息，其余字段有则读、无则算。

三层容错：
  1. 宽容预处理 —— 全角转半角、各种分隔符归一、剥离序号与括号注释、去掉名字里的空格
  2. 双策略解析 —— 先按"名称:数值"扫描；不行再按行/段落的"名称 数值"松匹配
  3. 合理性校验 —— 物种数范围、浓度非负、与文本里"物种种类数"互校
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------- 第 1 层：宽容预处理 ----------
_FULL2HALF = str.maketrans({
    "：": ":", "，": ",", "、": ",", "；": ";", "（": "(", "）": ")",
    "％": "%", "＝": "=", "　": " ", "×": "*",
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
})

# 开头序号： 1. / 1、 / 1) / ① 之类
_LEADING_NO = re.compile(r"^\s*(?:\d{1,3}\s*[.、)）]|[\u2460-\u2473]|[（(]\s*\d{1,3}\s*[）)])\s*")
# 尾部括号注释：内管虫(Arcella) / 表壳虫（有壳）
_TRAILING_NOTE = re.compile(r"[（(][^（()）]{0,30}[）)]\s*$")

# ---------- 元数据（不是物种的字段） ----------
_EXTRA_RE = re.compile(
    r"(物种种类数|多样性指数\s*H\s*['\u2019]?|绝对优势种群|优势种群|种群占比|较上次变化|采样时间|设备编号)\s*[:=]\s*"
)
_UNIT_RE = re.compile(r"浓度单位\s*[(]\s*([^)]+?)\s*[)]")
_CHANGE_RE = re.compile(r"([\u4e00-\u9fff·]{1,12})\s*([+-]?\d+(?:\.\d+)?)\s*%")

# ---------- 第 2 层：两种解析策略 ----------
# 策略 A：全文本扫描"名称 : 数值"（名称限定纯中文，避免把 H' 当成物种）
_STRICT_SCAN = re.compile(r"([\u4e00-\u9fff·]{1,12})\s*[:=]\s*([+-]?\d+(?:\.\d+)?)")

# 策略 B：按行/段落松匹配"名称 <分隔> 数值[尾巴]"，要求整段以数值收尾
_SEG_SPLIT = re.compile(r"[\n\r,;]")
_LOOSE_SEG = re.compile(
    r"^\s*(?:\d{1,3}\s*[.、)）]|[\u2460-\u2473])?\s*"          # 可选序号
    r"([\u4e00-\u9fff][\u4e00-\u9fff\s·]{0,13}?)\s*"           # 名称（允许内部空格）
    r"(?:[(][^()]{0,30}[)])?\s*"                                  # 可选括号注释，如 (Arcella)
    r"[:=\s\t]+\s*"                                              # 分隔符：冒号/等号/空格/制表符
    r"([+-]?\d+(?:\.\d+)?)\s*"                                  # 数值
    r"(?:\*?10\^?\d+|[个只]\s*/?\s*[LlmM]+|%|个)?\s*$"        # 可选尾巴（单位/%）
)

_BAD_HINT = ("种群", "种类", "指数", "变化", "占比", "单位", "序号", "时间", "温度", "浓度", "编号", "设备")

MIN_SPECIES, MAX_SPECIES = 3, 60          # 合理性区间


@dataclass
class ParsedSample:
    species: dict[str, float] = field(default_factory=dict)   # 物种名 -> 浓度
    unit: str = ""                                            # 浓度单位
    extras: dict[str, str] = field(default_factory=dict)      # 文本夹带的其它字段
    change: dict[str, float] = field(default_factory=dict)    # 文本自带的"较上次变化"(%)
    strategy: str = ""                                        # 用了哪种解析策略
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(self.species.values())

    @property
    def positive_count(self) -> int:
        return sum(1 for v in self.species.values() if v > 0)

    def summary(self) -> str:
        lines = [f"识别到物种 {len(self.species)} 个（浓度>0 的 {self.positive_count} 个）",
                 f"解析策略：{self.strategy or '—'}",
                 f"浓度单位：{self.unit or '（未提供）'}",
                 f"浓度合计：{self.total:.4f}"]
        if self.change:
            lines.append(f"文本自带「较上次变化」：{len(self.change)} 个物种")
        if self.extras:
            lines.append("文本中夹带的其它字段：")
            for k, v in self.extras.items():
                lines.append(f"  · {k}：{v if len(v) <= 60 else v[:60] + '…'}")
        if self.warnings:
            lines.append("提示：")
            lines += [f"  ! {x}" for x in self.warnings]
        return "\n".join(lines)


# ---------------- 预处理 ----------------
def normalize(text: str) -> str:
    """全角转半角 + 统一分隔符。"""
    return text.translate(_FULL2HALF)


def normalize_name(name: str) -> str:
    """剥序号、剥尾部括号注释、去掉名字内部空白。"""
    s = _LEADING_NO.sub("", name)
    s = _TRAILING_NOTE.sub("", s)
    s = re.sub(r"\s+", "", s)
    return s.strip()


def _mask_metadata(text: str) -> str:
    """把"非物种"字段整段替换成逗号，剩下的才是物种区。"""
    spans: list[tuple[int, int]] = []
    matches = list(_EXTRA_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        spans.append((m.start(), end))
    for m in _UNIT_RE.finditer(text):
        spans.append((m.start(), m.end()))
    if not spans:
        return text
    spans.sort()
    out, last = [], 0
    for s, e in spans:
        if s < last:
            continue
        out.append(text[last:s])
        out.append(",")
        last = e
    out.append(text[last:])
    return "".join(out)


def _acceptable(name: str) -> bool:
    if not name or len(name) > 14:
        return False
    if any(h in name for h in _BAD_HINT):
        return False
    # 必须至少两个中文字符，且不含拉丁字母/数字
    return len(re.findall(r"[\u4e00-\u9fff]", name)) >= 2 and not re.search(r"[A-Za-z0-9]", name)


def _strategy_scan(masked: str) -> dict[str, float]:
    """策略 A：全文本扫描 名称:数值。"""
    found: dict[str, float] = {}
    for m in _STRICT_SCAN.finditer(masked):
        name = normalize_name(m.group(1))
        if _acceptable(name):
            found[name] = float(m.group(2))
    return found


def _strategy_loose(masked: str) -> dict[str, float]:
    """策略 B：按行/段落松匹配（支持没有冒号、制表符表格、两列粘贴）。"""
    found: dict[str, float] = {}
    for seg in _SEG_SPLIT.split(masked):
        if not seg.strip():
            continue
        m = _LOOSE_SEG.match(seg)
        if not m:
            continue
        name = normalize_name(m.group(1))
        if _acceptable(name):
            found[name] = float(m.group(2))
    return found


# ---------------- 主入口 ----------------
def parse(text: str) -> ParsedSample:
    result = ParsedSample()
    if not text or not text.strip():
        result.warnings.append("输入为空")
        return result

    raw = normalize(text)

    m = _UNIT_RE.search(raw)
    if m:
        result.unit = m.group(1).strip()

    matches = list(_EXTRA_RE.finditer(raw))
    for i, m in enumerate(matches):
        key = re.sub(r"\s+", "", m.group(1))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        value = raw[m.end():end].strip(" 。,;\n\t\r")
        if value:
            result.extras[key] = value

    masked = _mask_metadata(raw)

    a = _strategy_scan(masked)
    b = _strategy_loose(masked)
    if len(b) > len(a):
        result.species, result.strategy = b, "松匹配（行/段落）"
    elif a:
        result.species, result.strategy = a, "扫描（名称:数值）"
    elif b:
        result.species, result.strategy = b, "松匹配（行/段落）"
    else:
        result.strategy = "失败"

    # 较上次变化（方案 A）
    prev_text = result.extras.get("较上次变化", "")
    if prev_text:
        for m in _CHANGE_RE.finditer(prev_text):
            name = normalize_name(m.group(1))
            if _acceptable(name) or name in result.species:
                result.change[name] = float(m.group(2))

    _validate(result)
    return result


def _validate(result: ParsedSample) -> None:
    """第 3 层：合理性校验。只提示，不阻断。"""
    n = len(result.species)
    if n == 0:
        result.warnings.append("未识别到「物种名 + 浓度」数据，请检查文本格式")
        return
    if n == 1:
        result.warnings.append("只识别到 1 个物种，请确认文本是否完整")
    if n > MAX_SPECIES:
        result.warnings.append(f"识别到 {n} 个物种，超过常见范围（{MIN_SPECIES}~{MAX_SPECIES}），可能有误识别")

    negatives = [k for k, v in result.species.items() if v < 0]
    if negatives:
        result.warnings.append(f"存在负浓度：{'、'.join(negatives)}")
    zeros = [k for k, v in result.species.items() if v == 0]
    if zeros:
        result.warnings.append(f"{len(zeros)} 个物种浓度为 0：{'、'.join(zeros[:6])}{'…' if len(zeros) > 6 else ''}")

    # 与文本里自带的"物种种类数"互校
    stated = result.extras.get("物种种类数", "")
    mm = re.search(r"\d+", stated)
    if mm and int(mm.group()) != n:
        result.warnings.append(f"文本写的物种种类数是 {mm.group()}，实际解析出 {n} 个，请核对")

    if result.total <= 0:
        result.warnings.append("浓度合计为 0，无法计算相对丰度")
