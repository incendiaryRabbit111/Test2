"""趋势对比：一个容器画一个物种的历史折线，容器下方按钮切换物种。

数据来自历史库。横轴优先用「采样时间」，解析不出来就退回「导入时间」，
两者都解析不出来时改用等距序号轴（并在轴上注明）。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.times import parse_dt
from PySide6.QtCharts import QChart, QChartView, QDateTimeAxis, QLineSeries, QValueAxis
from PySide6.QtCore import QDateTime, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

LINE_COLOR = QColor("#1f6feb")


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
        self._current: str = ""
        self._mode: str = "conc"          # conc = 绝对浓度, rel = 相对丰度
        self._buttons: dict[str, QPushButton] = {}
        self._chart = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.view = QChartView()
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        root.addWidget(self.view, 1)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        tip = QLabel("切换物种：")
        tip.setStyleSheet("color:#555;")
        bar.addWidget(tip)

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
        bar.addWidget(self.scroll, 1)

        self.mode_btn = QPushButton("切换为：相对丰度")
        self.mode_btn.setToolTip("绝对浓度反映真实数量，相对丰度反映它在群落里的地位")
        self.mode_btn.clicked.connect(self._toggle_mode)
        bar.addWidget(self.mode_btn)
        root.addLayout(bar)

        self._render()

    # ---------------- 对外接口 ----------------
    def load(self, records) -> None:
        """records：历史记录列表（顺序不限）。"""
        self._records = sorted(records, key=_sort_key)
        names: list[str] = []
        for rec in self._records:
            for n in rec.species:
                if n not in names:
                    names.append(n)
        if self._records:                      # 按最近一次的浓度降序排列，常用的排前面
            latest = self._records[-1].species
            names.sort(key=lambda n: -latest.get(n, 0.0))
        self._names = names

        self._rebuild_buttons()
        if self._current not in names:
            self._current = names[0] if names else ""
        self._select(self._current, force=True)

    # ---------------- 内部 ----------------
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
            btn.clicked.connect(lambda _=False, n=name: self._select(n))
            self.inner_layout.addWidget(btn)
            self._buttons[name] = btn
        self.inner_layout.addStretch(1)
        # 关键：不让按钮被压缩，宽度不够就让滚动条出现
        self.inner.adjustSize()
        self.inner.setMinimumWidth(self.inner_layout.sizeHint().width())

    def _select(self, name: str, force: bool = False) -> None:
        if not name:
            return
        if name == self._current and not force and self._buttons.get(name, None) is not None                 and self._buttons[name].isChecked():
            return
        self._current = name
        btn = self._buttons.get(name)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)
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

    def _render(self) -> None:
        chart = QChart()
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        chart.legend().hide()
        chart.setBackgroundRoundness(0)
        chart.setMargins(chart.margins())
        self._chart = chart

        if not self._records or not self._current:
            chart.setTitle("历史库暂无记录——先分析几次，数据攒起来这里就有图了")
            self.view.setChart(chart)
            return

        points: list[tuple[datetime | None, int, float]] = []
        all_dt = True
        for idx, rec in enumerate(self._records):
            dt = _record_dt(rec)
            if dt is None:
                all_dt = False
            value = self._value_of(rec, self._current)
            if value is None:
                continue
            points.append((dt, idx, value))

        use_dt = all_dt and all(p[0] is not None for p in points)
        series = QLineSeries()
        series.setPointsVisible(True)
        series.setMarkerSize(7.0)
        series.setPen(QPen(LINE_COLOR, 2))

        for dt, idx, value in points:
            if use_dt and dt is not None:
                series.append(QDateTime(dt).toMSecsSinceEpoch(), value)
            else:
                series.append(idx, value)

        chart.addSeries(series)

        # ---- 横轴 ----
        if use_dt:
            axis_x = QDateTimeAxis()
            axis_x.setFormat("MM-dd HH:mm")
            axis_x.setTitleText("时间")
            chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
            series.attachAxis(axis_x)
            xs = [p[0] for p in points]
            if xs:
                lo, hi = min(xs), max(xs)
                pad = (hi - lo) * 0.04 or timedelta(minutes=30)
                axis_x.setRange(QDateTime(lo - pad), QDateTime(hi + pad))
        else:
            axis_x = QValueAxis()
            axis_x.setLabelFormat("%d")
            axis_x.setTitleText("第几次检测（时间无法解析，按序号等距）")
            chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
            series.attachAxis(axis_x)
            axis_x.setRange(0, max(len(self._records) - 1, 1))

        # ---- 纵轴 ----
        axis_y = QValueAxis()
        axis_y.setTitleText("浓度（10^6 个/L）" if self._mode == "conc" else "相对丰度（%）")
        ymax = max((p[2] for p in points), default=0.0)
        axis_y.setRange(0.0, ymax * 1.15 if ymax > 0 else 1.0)
        axis_y.setLabelFormat("%.2f" if self._mode == "conc" else "%.1f")
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

        unit = "绝对浓度" if self._mode == "conc" else "相对丰度"
        chart.setTitle(f"{self._current}　|　{unit}　|　共 {len(points)} 个数据点，"
                       f"来自 {len(self._records)} 次检测")
        self.view.setChart(chart)
