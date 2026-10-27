"""趋势对比：一张图可同时画多个物种，下方按钮任意开关。

设计要点：
  · 按钮是**多选**，可以同时看多种虫的此消彼长
  · 每个物种固定配色，开关时颜色不变
  · 某次检测没检出该物种时，折线**断开**而不是连过去（连过去会假装数据连续）
  · 横轴优先用采样时间，解析不出来才退回等距序号
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.times import parse_dt
from PySide6.QtCharts import QChart, QChartView, QDateTimeAxis, QLineSeries, QValueAxis
from PySide6.QtCore import QDateTime, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

# 16 个区分度较高的颜色，按物种在列表中的位置固定分配
PALETTE = [
    "#1f6feb", "#e8590c", "#2f9e44", "#c2255c", "#7048e8", "#0c8599",
    "#e67700", "#ae3ec9", "#5c940d", "#d6336c", "#1971c2", "#f08c00",
    "#37b24d", "#862e9c", "#495057", "#0b7285",
]


def _record_dt(rec) -> datetime | None:
    return parse_dt(rec.sample_time) or parse_dt(rec.imported_at)


def _sort_key(rec):
    dt = _record_dt(rec)
    if dt:
        return (0, dt, rec.id or 0)
    return (1, datetime.min, rec.id or 0)


class TrendView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._records: list = []
        self._names: list[str] = []
        self._selected: set[str] = set()
        self._mode: str = "conc"          # conc = 绝对浓度, rel = 相对丰度
        self._buttons: dict[str, QPushButton] = {}
        self._colors: dict[str, str] = {}
        self._chart = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.view = QChartView()
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        root.addWidget(self.view, 1)

        # ---- 第一行：物种开关 ----
        bar1 = QHBoxLayout()
        bar1.setSpacing(6)
        tip = QLabel("切换物种：")
        tip.setStyleSheet("color:#555;")
        bar1.addWidget(tip)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedHeight(52)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.inner = QWidget()
        self.inner_layout = QHBoxLayout(self.inner)
        self.inner_layout.setContentsMargins(0, 0, 0, 0)
        self.inner_layout.setSpacing(4)
        self.scroll.setWidget(self.inner)
        bar1.addWidget(self.scroll, 1)
        root.addLayout(bar1)

        # ---- 第二行：快捷操作 + 纵轴 ----
        bar2 = QHBoxLayout()
        bar2.setSpacing(6)
        self.btn_all = QPushButton("全选")
        self.btn_dom = QPushButton("只选优势种")
        self.btn_none = QPushButton("清空")
        self.btn_all.clicked.connect(self._select_all)
        self.btn_dom.clicked.connect(self._select_dominant)
        self.btn_none.clicked.connect(self._select_none)
        bar2.addWidget(self.btn_all)
        bar2.addWidget(self.btn_dom)
        bar2.addWidget(self.btn_none)
        bar2.addStretch(1)

        self.mode_btn = QPushButton("切换为：相对丰度")
        self.mode_btn.setToolTip("绝对浓度反映真实数量；相对丰度反映它在群落里的地位")
        self.mode_btn.clicked.connect(self._toggle_mode)
        bar2.addWidget(self.mode_btn)
        root.addLayout(bar2)

        self._render()

    # ---------------- 对外接口 ----------------
    def load(self, records) -> None:
        self._records = sorted(records, key=_sort_key)
        names: list[str] = []
        for rec in self._records:
            for n in rec.species:
                if n not in names:
                    names.append(n)
        if self._records:
            latest = self._records[-1].species
            names.sort(key=lambda n: -latest.get(n, 0.0))
        self._names = names
        self._colors = {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(names)}

        keep = {n for n in self._selected if n in names}
        self._selected = keep if keep else self._default_selection()

        self._rebuild_buttons()
        self._sync_buttons()
        self._render()

    # ---------------- 内部 ----------------
    def _default_selection(self) -> set[str]:
        """默认只勾优势种（相对丰度 ≥3%）；一个都没有就取前 3 名。"""
        if not self._records:
            return set()
        latest = self._records[-1].species
        total = sum(latest.values())
        if total <= 0:
            return set(self._names[:3])
        picked = {n for n, v in latest.items() if v / total >= 0.03}
        return picked or set(self._names[:3])

    @staticmethod
    def _clear_layout(lay) -> None:
        while lay.count():
            item = lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _rebuild_buttons(self) -> None:
        self._clear_layout(self.inner_layout)
        self._buttons.clear()
        for name in self._names:
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            color = self._colors.get(name, "#1f6feb")
            btn.setStyleSheet(
                f"QPushButton:checked{{background:{color};color:white;border:1px solid {color};}}")
            btn.clicked.connect(lambda checked, n=name: self._toggle_species(n, checked))
            self.inner_layout.addWidget(btn)
            self._buttons[name] = btn
        self.inner_layout.addStretch(1)
        self.inner.adjustSize()
        self.inner.setMinimumWidth(self.inner_layout.sizeHint().width())

    def _sync_buttons(self) -> None:
        for name, btn in self._buttons.items():
            btn.setChecked(name in self._selected)

    def _toggle_species(self, name: str, checked: bool) -> None:
        if checked:
            self._selected.add(name)
        else:
            self._selected.discard(name)
        self._render()

    def _select_all(self) -> None:
        self._selected = set(self._names)
        self._sync_buttons()
        self._render()

    def _select_none(self) -> None:
        self._selected.clear()
        self._sync_buttons()
        self._render()

    def _select_dominant(self) -> None:
        self._selected = self._default_selection()
        self._sync_buttons()
        self._render()

    def _toggle_mode(self) -> None:
        self._mode = "rel" if self._mode == "conc" else "conc"
        self.mode_btn.setText("切换为：绝对浓度" if self._mode == "rel" else "切换为：相对丰度")
        self._render()

    def _value_of(self, rec, name: str) -> float | None:
        if name not in rec.species:
            return None
        if self._mode == "conc":
            return rec.species[name]
        total = sum(rec.species.values())
        return rec.species[name] / total * 100 if total > 0 else 0.0

    @staticmethod
    def _segments(points: list) -> list[list]:
        """把 (下标, 值) 序列按"断点"切成若干连续段。"""
        segs: list[list] = []
        cur: list = []
        prev_idx = None
        for idx, val in points:
            if prev_idx is not None and idx != prev_idx + 1:
                if cur:
                    segs.append(cur)
                cur = []
            cur.append((idx, val))
            prev_idx = idx
        if cur:
            segs.append(cur)
        return segs

    def _render(self) -> None:
        chart = QChart()
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        chart.setBackgroundRoundness(0)
        self._chart = chart

        if not self._records or not self._selected:
            chart.legend().hide()
            chart.setTitle("勾选上方物种查看趋势" if self._records
                           else "历史库暂无记录——先分析几次，或用「批量导入」灌数据")
            self.view.setChart(chart)
            return

        # 收集每个物种的点：(记录下标, 值)，缺失的直接不放
        per_species: dict[str, list[tuple[int, float]]] = {}
        all_dt: dict[int, datetime | None] = {}
        for idx, rec in enumerate(self._records):
            all_dt[idx] = _record_dt(rec)
            for name in self._selected:
                v = self._value_of(rec, name)
                if v is not None:
                    per_species.setdefault(name, []).append((idx, v))

        if not per_species:
            chart.legend().hide()
            chart.setTitle("选中的物种在这些记录里都没有数据")
            self.view.setChart(chart)
            return

        use_dt = all(all_dt[i] is not None for _n, pts in per_species.items() for i, _v in pts)
        multi = len(per_species) > 1

        ymax = 0.0
        first_series = True
        for name in self._names:                      # 用 _names 顺序保证颜色稳定
            if name not in per_species:
                continue
            color = QColor(self._colors.get(name, "#1f6feb"))
            segs = self._segments(per_species[name])
            for si, seg in enumerate(segs):
                series = QLineSeries()
                series.setName(name if si == 0 else "")
                series.setPen(QPen(color, 2))
                series.setPointsVisible(len(self._records) <= 48)
                series.setMarkerSize(6.0 if multi else 7.0)
                for idx, val in seg:
                    ymax = max(ymax, val)
                    if use_dt:
                        series.append(QDateTime(all_dt[idx]).toMSecsSinceEpoch(), val)
                    else:
                        series.append(idx, val)
                chart.addSeries(series)
                if si > 0:                            # 断点续段不重复上图例
                    for marker in chart.legend().markers(series):
                        marker.setVisible(False)
                first_series = False

        # ---- 横轴 ----
        if use_dt:
            axis_x = QDateTimeAxis()
            axis_x.setFormat("MM-dd HH:mm")
            axis_x.setTitleText("时间")
            chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
            for s in chart.series():
                s.attachAxis(axis_x)
            xs = [all_dt[i] for _n, pts in per_species.items() for i, _v in pts if all_dt[i]]
            if xs:
                lo, hi = min(xs), max(xs)
                pad = (hi - lo) * 0.04 or timedelta(minutes=30)
                axis_x.setRange(QDateTime(lo - pad), QDateTime(hi + pad))
        else:
            axis_x = QValueAxis()
            axis_x.setLabelFormat("%d")
            axis_x.setTitleText("第几次检测（时间无法解析，按序号等距）")
            chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
            for s in chart.series():
                s.attachAxis(axis_x)
            axis_x.setRange(0, max(len(self._records) - 1, 1))

        # ---- 纵轴 ----
        axis_y = QValueAxis()
        axis_y.setTitleText("浓度（10^6 个/L）" if self._mode == "conc" else "相对丰度（%）")
        axis_y.setRange(0.0, ymax * 1.15 if ymax > 0 else 1.0)
        axis_y.setLabelFormat("%.2f" if self._mode == "conc" else "%.1f")
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        for s in chart.series():
            s.attachAxis(axis_y)

        # ---- 图例 ----
        if multi:
            chart.legend().setVisible(True)
            chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
            f = QFont()
            f.setPointSize(8)
            chart.legend().setFont(f)
        else:
            chart.legend().hide()

        unit = "绝对浓度" if self._mode == "conc" else "相对丰度"
        chart.setTitle(f"{len(per_species)} 个物种　|　{unit}　|　"
                       f"{len(self._records)} 次检测")
        self.view.setChart(chart)
