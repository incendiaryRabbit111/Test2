"""API 调试台。

用途：
  - 不启动/不修改本地分析流程，直接测试 HTTP API；
  - 裸文本评价；
  - 用户知识（文字/PDF）导入、查看、删除。

这是开发调试工具，不做产品化界面。
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QSettings, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient


class _ApiWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self.fn())
        except Exception as exc:  # noqa: BLE001 - 调试工具需要把错误交给界面
            self.failed.emit(str(exc))


class ApiDebugDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("API 调试台 / 知识库")
        self.resize(980, 780)

        self.settings = QSettings("MicrobeAnalyzer", "ApiDebug")
        self._worker: _ApiWorker | None = None
        self._pending_callback: Callable[[Any], None] | None = None
        self._refresh_after_finish = False
        self._busy_buttons: list[QPushButton] = []

        self._build_ui()
        self._load_settings()

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        conn = QGroupBox("API 连接")
        form = QFormLayout(conn)
        self.base_edit = QLineEdit()
        self.base_edit.setPlaceholderText("http://127.0.0.1:8000")
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("可选；服务端设置了 MICROBE_API_KEY 时必填")
        form.addRow("API 地址", self.base_edit)
        form.addRow("X-API-Key", self.key_edit)

        conn_row = QHBoxLayout()
        self.btn_save = QPushButton("保存设置")
        self.btn_test = QPushButton("测试连接")
        self.btn_save.clicked.connect(self._save_settings)
        self.btn_test.clicked.connect(self._test_connection)
        conn_row.addWidget(self.btn_save)
        conn_row.addWidget(self.btn_test)
        conn_row.addStretch(1)
        self.conn_status = QLabel("未测试")
        self.conn_status.setStyleSheet("color:#666;")
        conn_row.addWidget(self.conn_status)
        form.addRow("", conn_row)
        root.addWidget(conn)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_analyze_tab(), "分析调试")
        self.tabs.addTab(self._build_knowledge_tab(), "知识库")
        root.addWidget(self.tabs, 1)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        box.rejected.connect(self.reject)
        root.addWidget(box)

        self._busy_buttons = [
            self.btn_save,
            self.btn_test,
            self.btn_analyze,
            self.btn_import_text,
            self.btn_import_pdf,
            self.btn_refresh,
            self.btn_delete,
        ]

    def _build_analyze_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        tip = QLabel(
            "输入仪器/用户的固定文本，直接调用后端 <b>POST /api/v1/evaluate</b>。"
            "这里不经过本地 parser，能验证真实 API 链路。"
        )
        tip.setWordWrap(True)
        lay.addWidget(tip)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("采样时间："))
        self.sample_time_edit = QLineEdit()
        self.sample_time_edit.setPlaceholderText(
            "可选，例如 2026-11-11 08:00:00；留空则使用服务器接收时间"
        )
        time_row.addWidget(self.sample_time_edit, 1)
        lay.addLayout(time_row)

        split = QSplitter(Qt.Orientation.Vertical)
        self.input_text = QPlainTextEdit()
        self.input_text.setPlaceholderText(
            "表壳虫：2.15，匣壳虫：0.42，内管虫：0.31，..."
        )
        self.input_text.setPlainText(
            "表壳虫：2.15，匣壳虫：0.42，内管虫：0.31，轮虫：0.21，"
            "线虫：0.15，袋鞭虫：0.12，扭曲管叶虫：0.09，钟虫：0.06，"
            "盖纤虫：0.05，累枝虫：0.04，楯纤虫：0.03，摩门虫：0.02，斜管虫：0.02"
        )
        split.addWidget(self.input_text)

        result_wrap = QWidget()
        rl = QVBoxLayout(result_wrap)
        rl.setContentsMargins(0, 0, 0, 0)
        self.result_text = QPlainTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setPlaceholderText("调用结果会显示在这里")
        rl.addWidget(self.result_text)
        split.addWidget(result_wrap)
        split.setSizes([230, 430])
        lay.addWidget(split, 1)

        row = QHBoxLayout()
        self.btn_analyze = QPushButton("调用 API 分析")
        self.btn_analyze.clicked.connect(self._analyze)
        row.addWidget(self.btn_analyze)
        self.analyze_status = QLabel("就绪")
        self.analyze_status.setStyleSheet("color:#666;")
        row.addWidget(self.analyze_status, 1)
        lay.addLayout(row)
        return page

    def _build_knowledge_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        text_box = QGroupBox("导入纯文字")
        tf = QVBoxLayout(text_box)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("标题，例如：现场经验：表壳虫")
        self.content_edit = QPlainTextEdit()
        self.content_edit.setPlaceholderText("粘贴一小段知识文字")
        self.content_edit.setMaximumHeight(120)
        tf.addWidget(self.title_edit)
        tf.addWidget(self.content_edit)
        text_row = QHBoxLayout()
        self.btn_import_text = QPushButton("导入文字")
        self.btn_import_text.clicked.connect(self._import_text)
        text_row.addWidget(self.btn_import_text)
        text_row.addStretch(1)
        tf.addLayout(text_row)
        lay.addWidget(text_box)

        pdf_box = QGroupBox("导入文字版 PDF")
        pf = QHBoxLayout(pdf_box)
        self.btn_import_pdf = QPushButton("选择 PDF 并导入")
        self.btn_import_pdf.clicked.connect(self._import_pdf)
        pf.addWidget(self.btn_import_pdf)
        pf.addWidget(QLabel("扫描版 PDF 暂不支持；会提示需要 OCR。"))
        pf.addStretch(1)
        lay.addWidget(pdf_box)

        list_box = QGroupBox("已导入的用户知识")
        ll = QVBoxLayout(list_box)
        self.knowledge_table = QTableWidget(0, 5)
        self.knowledge_table.setHorizontalHeaderLabels(
            ["标题", "类型", "页数", "块数", "文档 ID"]
        )
        self.knowledge_table.verticalHeader().setVisible(False)
        self.knowledge_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.knowledge_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        header = self.knowledge_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        ll.addWidget(self.knowledge_table, 1)

        row = QHBoxLayout()
        self.btn_refresh = QPushButton("刷新列表")
        self.btn_delete = QPushButton("删除选中")
        self.btn_refresh.clicked.connect(self._refresh_knowledge)
        self.btn_delete.clicked.connect(self._delete_knowledge)
        row.addWidget(self.btn_refresh)
        row.addWidget(self.btn_delete)
        self.knowledge_status = QLabel("点「刷新列表」查看已导入知识")
        self.knowledge_status.setStyleSheet("color:#666;")
        row.addWidget(self.knowledge_status, 1)
        ll.addLayout(row)
        lay.addWidget(list_box, 1)
        return page

    # ---------------- 配置 ----------------
    def _load_settings(self) -> None:
        self.base_edit.setText(
            str(self.settings.value("base_url", "http://127.0.0.1:8000"))
        )
        self.key_edit.setText(str(self.settings.value("api_key", "")))

    def _save_settings(self) -> None:
        self.settings.setValue("base_url", self.base_edit.text().strip())
        self.settings.setValue("api_key", self.key_edit.text().strip())
        self.conn_status.setText("已保存")
        self.conn_status.setStyleSheet("color:#1a7f37;")

    def _client(self) -> ApiClient:
        self._save_settings()
        return ApiClient(
            self.base_edit.text().strip(),
            self.key_edit.text().strip(),
        )

    # ---------------- 后台请求 ----------------
    def _set_busy(self, busy: bool) -> None:
        for button in self._busy_buttons:
            button.setEnabled(not busy)

    def _run(
        self,
        fn: Callable[[], Any],
        on_done: Callable[[Any], None],
        status: str,
    ) -> None:
        if self._worker is not None:
            QMessageBox.information(self, "请稍候", "上一个请求还在进行中。")
            return
        self._pending_callback = on_done
        self._set_busy(True)
        self.analyze_status.setText(status)
        self.analyze_status.setStyleSheet("color:#666;")

        worker = _ApiWorker(fn)
        self._worker = worker
        worker.done.connect(self._on_worker_done)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(self._on_worker_finished)
        worker.start()

    def _on_worker_done(self, result: Any) -> None:
        self._set_busy(False)
        callback = self._pending_callback
        self._pending_callback = None
        if callback is not None:
            callback(result)

    def _on_worker_failed(self, message: str) -> None:
        self._set_busy(False)
        self._pending_callback = None
        self._refresh_after_finish = False
        self.analyze_status.setText("请求失败")
        self.analyze_status.setStyleSheet("color:#c0392b;")
        QMessageBox.warning(self, "API 调用失败", message)

    def _on_worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        if self._refresh_after_finish:
            self._refresh_after_finish = False
            QTimer.singleShot(0, self._refresh_knowledge)

    # ---------------- 分析 ----------------
    def _test_connection(self) -> None:
        self._run(
            lambda: self._client().health(),
            self._on_test_done,
            "测试连接中…",
        )

    def _on_test_done(self, data: Any) -> None:
        version = ""
        if isinstance(data, dict):
            version = str(data.get("version") or "")
        self.conn_status.setText("连接成功" + (f"（v{version}）" if version else ""))
        self.conn_status.setStyleSheet("color:#1a7f37;")

    def _analyze(self) -> None:
        text = self.input_text.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "提示", "请先输入固定文本。")
            return
        sample_time = self.sample_time_edit.text().strip()
        self._run(
            lambda: self._client().evaluate(text, sample_time=sample_time),
            self._on_analyze_done,
            "分析中（AI 可能需要十几秒）…",
        )

    def _on_analyze_done(self, data: Any) -> None:
        self.analyze_status.setText("完成")
        self.analyze_status.setStyleSheet("color:#1a7f37;")
        self.result_text.setPlainText(self._format_result(data))

    @staticmethod
    def _format_result(data: Any) -> str:
        if not isinstance(data, dict):
            return str(data)
        lines: list[str] = []
        lines.append(f"状态：{data.get('status')}    降级：{data.get('degraded')}")
        lines.append(f"请求号：{data.get('request_id', '')}")
        lines.append(
            f"采样时间：{data.get('sample_time', '')}    "
            f"来源：{data.get('time_source', '')}"
        )
        lines.append("")

        metrics = data.get("metrics") or {}
        if metrics:
            lines.append("【指标】")
            lines.append(
                f"物种数：{metrics.get('species_count')}    "
                f"总浓度：{metrics.get('total')}"
            )
            lines.append(
                f"H'：{metrics.get('shannon_h')}    "
                f"D：{metrics.get('margalef_d')}    "
                f"J：{metrics.get('pielou_j')}"
            )
            lines.append(
                "优势种：" + "、".join(metrics.get("dominant") or [])
            )
            lines.append(
                "绝对优势种：" + "、".join(metrics.get("absolute") or [])
            )
            lines.append("")

        changes = data.get("changes") or []
        if changes:
            lines.append("【较上次变化】")
            for item in changes:
                lines.append(
                    f"{item.get('species')}：{item.get('text')}"
                    f"（{item.get('source')}）"
                )
            lines.append("")

        trends = data.get("trends") or []
        if trends:
            lines.append("【趋势命中】")
            for item in trends:
                lines.append(
                    f"{item.get('rule')}：{item.get('detail')}"
                    f" → {item.get('meaning')}"
                )
            lines.append("")

        evaluations = data.get("evaluations") or []
        if evaluations:
            lines.append("【逐物种评价】")
            for item in evaluations:
                lines.append(f"{item.get('species')}：{item.get('comment')}")
                advice = item.get("advice")
                if advice:
                    lines.append(f"  建议：{advice}")
            lines.append("")

        report = data.get("report_text")
        if report:
            lines.append("【综合报告】")
            lines.append(str(report))
            lines.append("")

        references = data.get("references") or []
        if references:
            lines.append("【参考来源】")
            for ref in references:
                start = ref.get("page_start")
                end = ref.get("page_end")
                pages = f"第{start}页" if start == end else f"第{start}-{end}页"
                cited = " ✔已引用" if ref.get("cited") else ""
                lines.append(
                    f"[{ref.get('label', '')}] 《{ref.get('book', '')}》"
                    f"{pages}{cited}"
                )
            lines.append("")

        warnings = data.get("warnings") or []
        if warnings:
            lines.append("【警告】")
            for item in warnings:
                lines.append(f"- {item}")

        return "\n".join(lines).strip()

    # ---------------- 知识库 ----------------
    def _import_text(self) -> None:
        title = self.title_edit.text().strip()
        content = self.content_edit.toPlainText().strip()
        if not title or not content:
            QMessageBox.information(self, "提示", "标题和内容都要填写。")
            return
        self._run(
            lambda: self._client().import_text(title, content),
            self._on_import_done,
            "导入文字知识…",
        )

    def _import_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择文字版 PDF", "", "PDF 文件 (*.pdf)"
        )
        if not path:
            return
        self._run(
            lambda: self._client().import_pdf(path),
            self._on_import_done,
            "上传并解析 PDF…",
        )

    def _on_import_done(self, data: Any) -> None:
        doc = data.get("document", {}) if isinstance(data, dict) else {}
        title = doc.get("title", "")
        self.knowledge_status.setText(f"已导入：{title}")
        self.knowledge_status.setStyleSheet("color:#1a7f37;")
        # 先设标记：QMessageBox 会进入嵌套事件循环，finished 可能在这期间到达。
        self._refresh_after_finish = True
        QMessageBox.information(
            self,
            "导入成功",
            f"已导入：{title}\n块数：{doc.get('chunks', '')}",
        )

    def _refresh_knowledge(self) -> None:
        self._run(
            lambda: self._client().list_knowledge(),
            self._on_knowledge_list,
            "读取知识列表…",
        )

    def _on_knowledge_list(self, data: Any) -> None:
        documents = data.get("documents", []) if isinstance(data, dict) else []
        status = data.get("status", {}) if isinstance(data, dict) else {}
        self.knowledge_table.setRowCount(len(documents))
        for row, doc in enumerate(documents):
            values = [
                str(doc.get("title", "")),
                str(doc.get("kind", "")),
                str(doc.get("pages", "")),
                str(doc.get("chunks", "")),
                str(doc.get("id", "")),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in (1, 2, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.knowledge_table.setItem(row, col, item)
        self.knowledge_status.setText(
            f"内置知识块：{status.get('builtin_chunks', '—')}；"
            f"用户知识块：{status.get('user_chunks', '—')}；"
            f"用户文档：{status.get('documents', '—')}"
        )
        self.knowledge_status.setStyleSheet("color:#666;")

    def _delete_knowledge(self) -> None:
        row = self.knowledge_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "先选中一篇知识。")
            return
        item = self.knowledge_table.item(row, 4)
        doc_id = item.text() if item is not None else ""
        title_item = self.knowledge_table.item(row, 0)
        title = title_item.text() if title_item is not None else doc_id
        if not doc_id:
            return
        reply = QMessageBox.question(
            self,
            "删除知识",
            f"确定删除「{title}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run(
            lambda: self._client().delete_knowledge(doc_id),
            self._on_delete_done,
            "删除知识…",
        )

    def _on_delete_done(self, data: Any) -> None:
        self.knowledge_status.setText("已删除")
        self._refresh_after_finish = True

    # ---------------- 关闭 ----------------
    def reject(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "请稍候", "请求还没结束，完成后再关闭。")
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "请稍候", "请求还没结束，完成后再关闭。")
            event.ignore()
            return
        super().closeEvent(event)
