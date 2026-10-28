"""首次运行的新手引导。

做法：在主窗口上盖一层半透明遮罩（程序因此点不动），
在高亮目标控件的位置挖一个"洞"，旁边弹一张步骤卡片，并用虚线箭头指过去。
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

ACCENT = QColor("#4ADE80")       # 高亮描边 / 箭头
MASK = QColor(12, 20, 17, 168)   # 遮罩


@dataclass
class Step:
    title: str
    text: str
    target: str | None = None     # 目标控件的 objectName；None = 卡片居中


class OnboardingOverlay(QWidget):
    finished = Signal()

    def __init__(self, host: QWidget, steps: list[Step]) -> None:
        super().__init__(host)
        self.host = host
        self.steps = steps
        self.index = 0
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._build_card()

    # ---------------- UI ----------------
    def _build_card(self) -> None:
        self.card = QFrame(self)
        self.card.setObjectName("guideCard")
        self.card.setStyleSheet("""
            QFrame#guideCard {
                background: #FFFFFF;
                border: 1px solid #DEE6E1;
                border-radius: 12px;
            }
            QLabel#guideStep  { color: #2F7D5D; font-size: 10px; font-weight: 600; }
            QLabel#guideTitle { color: #1C262D; font-size: 15px; font-weight: 600; }
            QLabel#guideText  { color: #5C6C64; font-size: 11px; }
            QPushButton#guidePrimary {
                background: #2F7D5D; color: #FFFFFF; border: none;
                border-radius: 7px; padding: 7px 18px; font-weight: 600;
            }
            QPushButton#guidePrimary:hover { background: #276A4F; }
        """)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(20, 16, 20, 14)
        lay.setSpacing(8)

        self.lbl_step = QLabel()
        self.lbl_step.setObjectName("guideStep")
        self.lbl_title = QLabel()
        self.lbl_title.setObjectName("guideTitle")
        self.lbl_text = QLabel()
        self.lbl_text.setObjectName("guideText")
        self.lbl_text.setWordWrap(True)
        self.lbl_text.setMinimumHeight(46)

        for w in (self.lbl_step, self.lbl_title, self.lbl_text):
            lay.addWidget(w)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_skip = QPushButton("跳过")
        self.btn_prev = QPushButton("上一步")
        self.btn_next = QPushButton("下一步")
        self.btn_next.setObjectName("guidePrimary")
        self.btn_skip.clicked.connect(self._finish)
        self.btn_prev.clicked.connect(lambda: self._goto(self.index - 1))
        self.btn_next.clicked.connect(self._next)
        row.addWidget(self.btn_skip)
        row.addStretch(1)
        row.addWidget(self.btn_prev)
        row.addWidget(self.btn_next)
        lay.addLayout(row)

        self.card.setFixedWidth(360)

    # ---------------- 生命周期 ----------------
    def start(self) -> None:
        self.setGeometry(self.host.rect())
        self.host.installEventFilter(self)
        self.show()
        self.raise_()
        self.card.raise_()
        self.setFocus()
        self._goto(0)

    def eventFilter(self, obj, ev):
        if obj is self.host and ev.type() == QEvent.Type.Resize and self.isVisible():
            self.setGeometry(self.host.rect())
            self._place()
            self.update()
        return False

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self._finish()
        elif ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._next()
        else:
            super().keyPressEvent(ev)

    def _next(self) -> None:
        if self.index >= len(self.steps) - 1:
            self._finish()
        else:
            self._goto(self.index + 1)

    def _finish(self) -> None:
        self.host.removeEventFilter(self)
        self.hide()
        self.finished.emit()

    # ---------------- 步骤 ----------------
    def _goto(self, i: int) -> None:
        self.index = max(0, min(i, len(self.steps) - 1))
        st = self.steps[self.index]
        self.lbl_step.setText(f"第 {self.index + 1} / {len(self.steps)} 步")
        self.lbl_title.setText(st.title)
        self.lbl_text.setText(st.text)
        self.btn_prev.setEnabled(self.index > 0)
        self.btn_next.setText("开始使用" if self.index == len(self.steps) - 1 else "下一步")
        self.card.adjustSize()
        self._place()
        self.update()

    def _target_rect(self) -> QRect | None:
        target = self.steps[self.index].target
        if not target:
            return None
        w = self.host.findChild(QWidget, target)
        if w is None or not w.isVisible():
            return None
        return QRect(w.mapTo(self.host, QPoint(0, 0)), w.size()).adjusted(-8, -8, 8, 8)

    def _place(self) -> None:
        r = self._target_rect()
        cw, ch = self.card.width(), self.card.height()
        W, H = self.width(), self.height()
        m = 16
        if r is None:
            x, y = (W - cw) // 2, (H - ch) // 2
        else:
            x = r.center().x() - cw // 2
            y = r.bottom() + 16
            if y + ch > H - m:                       # 下方放不下 → 上方
                y = r.top() - ch - 16
            if y < m:                                # 上下都放不下 → 侧边
                y = max(m, min(r.center().y() - ch // 2, H - ch - m))
                x = r.right() + 20
                if x + cw > W - m:
                    x = r.left() - cw - 20
        x = max(m, min(x, W - cw - m))
        y = max(m, min(y, H - ch - m))
        self.card.move(x, y)

    # ---------------- 绘制 ----------------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        r = self._target_rect()
        if r is not None:
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(r), 10, 10)
            path = path.subtracted(hole)
        p.fillPath(path, MASK)

        if r is not None:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(ACCENT, 2))
            p.drawRoundedRect(r, 10, 10)
            self._draw_arrow(p, r)

    def _draw_arrow(self, p: QPainter, target: QRect) -> None:
        c = self.card.geometry()
        a = c.center()
        b = target.center()
        dx, dy = b.x() - a.x(), b.y() - a.y()
        if dx == 0 and dy == 0:
            return

        # 起点：卡片朝目标那一侧的中点
        if abs(dx) > abs(dy):
            start = QPoint(c.right() if dx > 0 else c.left(), a.y())
        else:
            start = QPoint(a.x(), c.bottom() if dy > 0 else c.top())

        # 终点：目标中心往后退 26px，别压住控件
        dist = max(1.0, (dx * dx + dy * dy) ** 0.5)
        ux, uy = dx / dist, dy / dist
        end = QPoint(int(b.x() - ux * 26), int(b.y() - uy * 26))

        pen = QPen(ACCENT, 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(start, end)

        left = QPoint(int(end.x() - uy * 7 - ux * 11), int(end.y() + ux * 7 - uy * 11))
        right = QPoint(int(end.x() + uy * 7 - ux * 11), int(end.y() - ux * 7 - uy * 11))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ACCENT)
        p.drawPolygon(QPolygonF([end, left, right]))
