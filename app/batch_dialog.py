"""批量导入对话框：粘贴多段文本 -> 预览 -> 一次性入库。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.batch import parse_batch

PLACEHOLDER = """每段一次检测，段与段之间用空行或 --- 隔开。段内第一行可以写时间。

2026-10-09 09:00
内管虫: 0.301, 表壳虫: 1.052, 轮虫: 0.022
---
2026-10-09 10:00
内管虫: 0.312, 表壳虫: 1.088, 轮虫: 0.024
---
（时间也可以不写，改用下面的「起始时间 + 间隔」自动推算）"""


class BatchDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("批量导入")
        self.resize(900, 660)
        self.items: list = []

        root = QVBoxLayout(self)

        head = QLabel("粘贴多段检测数据，点「解析预览」核对无误后再导入。<br>"
                      "<b>批量导入只做解析 + 计算 + 存档（用于趋势图），不调用 AI。</b>")
        head.setWordWrap(True)
        head.setStyleSheet("color:#444;")
        root.addWidget(head)

        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(PLACEHOLDER)
        root.addWidget(self.text, 3)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("起始时间："))
        self.start = QLineEdit()
        self.start.setPlaceholderText("例 2026-10-09 09:00（段内自带时间时可留空）")
        self.start.setMaximumWidth(240)
        ctrl.addWidget(self.start)
        ctrl.addSpacing(12)
        ctrl.addWidget(QLabel("间隔（分钟）："))
        self.interval = QSpinBox()
        self.interval.setRange(0, 100000)
        self.interval.setValue(60)
        self.interval.setMaximumWidth(100)
        ctrl.addWidget(self.interval)
        ctrl.addSpacing(12)
        self.btn_preview = QPushButton("解析预览")
        self.btn_preview.clicked.connect(self._on_preview)
        ctrl.addWidget(self.btn_preview)
        ctrl.addStretch(1)
        root.addLayout(ctrl)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["序号", "采样时间", "物种数", "浓度合计", "时间来源 / 提示"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 2)

        self.tip = QLabel("尚未解析")
        self.tip.setStyleSheet("color:#555;")
        root.addWidget(self.tip)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("确认导入")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    # ---------------- 解析预览 ----------------
    def _on_preview(self) -> bool:
        res = parse_batch(
            self.text.toPlainText(),
            start_time=self.start.text().strip(),
            interval_min=self.interval.value(),
        )
        self.items = res.items

        self.table.setRowCount(len(res.items))
        for r, it in enumerate(res.items):
            p = it.parsed
            n = len(p.species) if p else 0
            total = p.total if p else 0.0
            note = it.time_source or "无时间"
            if it.warning:
                note += "｜" + it.warning
            if n == 0:
                note = "⚠ " + note
            values = [str(it.index), it.sample_time or "—", str(n), f"{total:.3f}", note]
            for c, v in enumerate(values):
                item = QTableWidgetItem(v)
                if c in (0, 2, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if it.warning or n == 0:
                    item.setForeground(Qt.GlobalColor.darkYellow)
                self.table.setItem(r, c, item)

        ok = len(res.ok_items)
        self.tip.setText(f"共 {len(res.items)} 段，其中有效 {ok} 段。"
                         + (("问题：" + "；".join(res.warnings)) if res.warnings else ""))
        return ok > 0

    def _on_accept(self) -> None:
        if not self.items and not self._on_preview():
            QMessageBox.warning(self, "无法导入", "没有解析出任何有效数据。")
            return
        ok = [it for it in self.items if it.parsed and it.parsed.species]
        if not ok:
            QMessageBox.warning(self, "无法导入", "没有解析出任何有效数据。")
            return
        missing = [it.index for it in ok if not it.sample_time]
        if missing:
            reply = QMessageBox.question(
                self, "部分记录没有时间",
                f"第 {missing[:8]} 条没有采样时间，趋势图会按导入顺序排列。\n仍要导入吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.accept()
