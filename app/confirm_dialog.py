"""解析结果人工确认对话框（第 3 层防御）。

格式差异是穷举不完的，所以给一个"人一眼能核对、能改"的关口：
程序解析完先摆出来，用户可以改浓度、删错识别的、补漏掉的，确认后才往下走。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

COLOR_ROW_WARN = QColor("#fff5d6")


class ConfirmDialog(QDialog):
    """返回核对/修改后的 {物种: 浓度}。"""

    def __init__(self, parsed, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("核对解析结果")
        self.resize(560, 620)
        self._parsed = parsed

        layout = QVBoxLayout(self)

        head = QLabel(f"识别到 <b>{len(parsed.species)}</b> 个物种"
                      f"（解析策略：{parsed.strategy or '—'}）<br>"
                      "请核对下面的物种和浓度，可以直接双击修改；<b>确认后即以表格内容为准</b>。")
        head.setWordWrap(True)
        layout.addWidget(head)

        if parsed.warnings:
            warn = QLabel("⚠ " + "<br>⚠ ".join(parsed.warnings))
            warn.setWordWrap(True)
            warn.setStyleSheet("color:#b26a00; background:#fff8e6; padding:6px; border-radius:4px;")
            layout.addWidget(warn)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["物种", "浓度"])
        self.table.verticalHeader().setVisible(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 120)
        layout.addWidget(self.table)

        for name, value in parsed.species.items():
            self._append_row(name, f"{value:g}")

        row_btns = QHBoxLayout()
        btn_add = QPushButton("添加一行")
        btn_del = QPushButton("删除选中行")
        btn_reset = QPushButton("恢复原始解析")
        btn_add.clicked.connect(lambda: self._append_row("", ""))
        btn_del.clicked.connect(self._remove_selected)
        btn_reset.clicked.connect(self._reset)
        row_btns.addWidget(btn_add)
        row_btns.addWidget(btn_del)
        row_btns.addWidget(btn_reset)
        row_btns.addStretch(1)
        layout.addLayout(row_btns)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("确认，开始分析")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        self.species: dict[str, float] = {}

    # ---------------- 表格操作 ----------------
    def _append_row(self, name: str, value: str) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(name))
        item = QTableWidgetItem(value)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(r, 1, item)

    def _remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def _reset(self) -> None:
        self.table.setRowCount(0)
        for name, value in self._parsed.species.items():
            self._append_row(name, f"{value:g}")

    # ---------------- 校验 ----------------
    def _collect(self) -> tuple[dict[str, float], list[str]]:
        data: dict[str, float] = {}
        problems: list[str] = []
        for r in range(self.table.rowCount()):
            name_item = self.table.item(r, 0)
            val_item = self.table.item(r, 1)
            name = (name_item.text() if name_item else "").strip()
            raw = (val_item.text() if val_item else "").strip()
            if not name and not raw:
                continue
            if not name:
                problems.append(f"第 {r + 1} 行：物种名为空")
                continue
            if raw == "":
                problems.append(f"第 {r + 1} 行「{name}」：浓度为空")
                continue
            try:
                value = float(raw)
            except ValueError:
                problems.append(f"第 {r + 1} 行「{name}」：浓度「{raw}」不是数字")
                continue
            if value < 0:
                problems.append(f"第 {r + 1} 行「{name}」：浓度为负")
                continue
            if name in data:
                problems.append(f"第 {r + 1} 行「{name}」：物种重复")
                continue
            data[name] = value
        if not data and not problems:
            problems.append("表格是空的，至少需要一个物种")
        return data, problems

    def _on_accept(self) -> None:
        # 第一关：数据本身能不能用（不能修就不能继续）
        data, problems = self._collect()
        if problems:
            QMessageBox.warning(
                self, "数据有问题",
                "以下问题必须先修正：\n\n" + "\n".join(f"• {p}" for p in problems[:10]),
            )
            return

        # 第二关：解析阶段的告警（能用，但可能不准）——再弹一次让人确认
        if self._parsed.warnings:
            reply = QMessageBox.warning(
                self, "检测到异常",
                "解析阶段发现以下异常：\n\n"
                + "\n".join(f"• {w}" for w in self._parsed.warnings)
                + "\n\n数据仍可用于分析，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.species = data
        self.accept()
