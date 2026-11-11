"""主窗口（C 布局）：左侧会话列表，右侧详情。

一次检测 = 一条会话记录。点左边任意一条，右边立刻还原当时的
指标、物种评价、AI 报告；趋势图始终展示全部记录的走势。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# 导入用：源码运行时把项目根加进 sys.path（打包后模块已内嵌，不需要）
_PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

from app import analyzer as analyzer_mod
from app import api_config as api_config_mod
from app import exporter as exporter_mod
from app import history as history_mod
from app import metrics as metrics_mod
from app import parser as parser_mod
from app import trend as trend_mod
from app.api_client import ApiClient, ApiError
from app.api_debug_dialog import ApiDebugDialog
from app.api_dialog import ApiSettingsDialog
from app.api_history import ApiHistory
from app.batch_dialog import BatchDialog
from app.confirm_dialog import ConfirmDialog
from app.generated.ui_main_window import Ui_MainWindow
from app.paths import ROOT
from app.sample import SAMPLE_TEXT
from app.onboarding import OnboardingOverlay, Step
from app.trend_view import TrendView

from app.theme import ROW_ABSOLUTE, ROW_DOMINANT

COLOR_ABSOLUTE = QColor(ROW_ABSOLUTE)
COLOR_DOMINANT = QColor(ROW_DOMINANT)
COLOR_UP = QColor("#c0392b")
COLOR_DOWN = QColor("#1f6feb")
REPORT_FONT_PT = 13
FIRST_RUN_HINT = True          # 首次启动且没配置 AI 时，弹一次引导（测试里关掉）
SHOW_ERROR_DIALOG = True       # 调用失败时弹窗（测试里必须关掉，否则模态阻塞）
FORCE_GUIDE = False           # --guide 时强制显示新手引导
SUPPRESS_GUIDE = False        # 截图/测试时关掉引导


class AnalyzeWorker(QObject):
    """把 LLM 调用放到子线程，避免界面卡死。"""

    finished = Signal(object)

    def __init__(self, analyzer, payload: dict) -> None:
        super().__init__()
        self.analyzer = analyzer
        self.payload = payload

    def run(self) -> None:
        self.finished.emit(self.analyzer.analyze(self.payload))


class ApiCallWorker(QThread):
    """API 模式的网络请求放到子线程。"""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None) -> None:
        super().__init__(parent)
        self.fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self.fn())
        except Exception as exc:  # noqa: BLE001 - 错误交给界面显示
            self.failed.emit(str(exc))


class BusyOverlay(QWidget):
    """分析期间盖在结果区上的半透明遮罩，防止重复点击。"""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: rgba(255,255,255,218);")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lab = QLabel("正在分析，请稍候…")
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setStyleSheet("color:#2F7D5D;font-size:13px;font-weight:600;background:transparent;")
        lay.addWidget(lab)
        self.hide()

    def cover(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            self.show()
            self.raise_()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.history = history_mod.History()
        self.api_store = api_config_mod.ApiConfigStore()
        self.api_store.seed_from_env()        # 首次运行把 .env 里的 key 导进配置库
        self.analyzer = analyzer_mod.DeepSeekAnalyzer(self.api_store.default())
        self.mode = "local"
        self.api_client: ApiClient | None = None
        self.api_history: ApiHistory | None = None
        self._pending = None            # 分析中的上下文
        self._api_pending = None
        self._api_worker: ApiCallWorker | None = None
        self._change_map: dict = {}
        self._trends: list = []
        self._current = None            # 当前展示的 Record
        self._thread = None
        self._worker = None
        self._settings = QSettings("MicrobeAnalyzer", "App")
        self._guide = None
        self._guide_checked = False
        self._dot_cache: dict[bool, QIcon] = {}

        self._setup_more_menu()
        self._busy = BusyOverlay(self.ui.tabResults)
        self._setup_tables()
        self._setup_report_view()
        self._setup_trend_view()
        self._setup_feedback_bar()
        self._setup_mode_switch()
        self._connect()
        self.ui.mainLayout.setStretchFactor(self.ui.splitter, 1)
        self.ui.leftLayout.setStretchFactor(self.ui.listStack, 1)
        self.ui.inputText.setMinimumHeight(300)

        self._reload_providers()

        self._refresh_trend()
        self._reload_sessions(select_id=None)
        if self.history.count() == 0:
            self._show_input_page("还没有任何记录，粘贴数据后点「分析」")
        else:
            self._set_status(f"已载入 {self.history.count()} 条历史记录")

        if str(self._settings.value("backend_mode", "local")) == "api":
            self._apply_mode("api", initial=True)

    # ---------------- 初始化 ----------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._guide_checked:
            return
        self._guide_checked = True
        if SUPPRESS_GUIDE:
            return
        done = self._settings.value("onboarded", False, type=bool)
        if FORCE_GUIDE or not done:
            QTimer.singleShot(600, self.start_onboarding)

    def start_onboarding(self) -> None:
        if self._guide is not None:
            return
        # 教程讲的是输入流程，先把右侧切回输入页，免得箭头指向隐藏控件
        self.ui.rightStack.setCurrentWidget(self.ui.inputPage)
        steps = [
            Step("欢迎使用",
                 "这个工具把仪器输出的文字，变成有依据的分析报告。"
                 "花一分钟，带你走一遍最基本的流程。"),
            Step("第一步：配置模型",
                 "点这里填入 Base URL 和 API Key，程序会自动拉取可用模型，"
                 "勾选后保存。以后可以在同一处随时切换模型。",
                 target="btnApiSettings"),
            Step("第二步：新建一次分析",
                 "每次检测都从「新建分析」开始。左侧列表会按导入顺序自动编号，"
                 "点任意一条可以回看当时的报告。",
                 target="btnNew"),
            Step("第三步：粘贴数据",
                 "把仪器输出的文本粘进来。只写「物种: 浓度」也能识别，"
                 "全角标点、Excel 复制的表格都兼容。",
                 target="inputText"),
            Step("第四步：填采样时间",
                 "建议填上采样时间，趋势图按它排序；留空就用导入时间。",
                 target="timeInput"),
            Step("第五步：开始分析",
                 "点「分析」，程序会解析、计算指标、查本地文献库，再调用 AI，"
                 "十几秒出结果。",
                 target="btnAnalyze"),
            Step("分析完成之后",
                 "右侧有四个页签：计算指标、物种评价、AI 分析报告、趋势对比。"
                 "需要表格时点右下角「导出当前记录」。"),
        ]
        self._guide = OnboardingOverlay(self, steps)
        self._guide.finished.connect(self._on_guide_finished)
        self._guide.start()

    def _on_guide_finished(self) -> None:
        self._settings.setValue("onboarded", True)
        if self._guide is not None:
            self._guide.deleteLater()
            self._guide = None

    def _setup_more_menu(self) -> None:
        self._confirm_action = QAction("分析前核对解析结果", self)
        self._confirm_action.setCheckable(True)
        self._confirm_action.setChecked(True)
        menu = QMenu(self)
        menu.addAction(self._confirm_action)
        menu.addSeparator()
        self._api_debug_action = QAction("API 调试台 / 知识库", self)
        self._api_debug_action.triggered.connect(self.on_api_debug)
        menu.addAction(self._api_debug_action)
        self.ui.btnMore.setMenu(menu)
        self.ui.btnMore.setCursor(Qt.CursorShape.PointingHandCursor)

    def _setup_tables(self) -> None:
        t1 = self.ui.tblMetrics
        t1.setColumnCount(5)
        t1.setHorizontalHeaderLabels(["物种", "浓度", "相对丰度(%)", "优势种群", "绝对优势种群"])
        t1.verticalHeader().setVisible(False)
        t1.setEditTriggers(t1.EditTrigger.NoEditTriggers)
        t1.setShowGrid(False)
        t1.setAlternatingRowColors(True)

        t2 = self.ui.tblEvaluations
        t2.setColumnCount(6)
        t2.setHorizontalHeaderLabels(
            ["物种", "浓度", "相对丰度(%)", "较上次变化", "综合评价", "指导意见"])
        t2.verticalHeader().setVisible(False)
        t2.setWordWrap(True)
        t2.setEditTriggers(t2.EditTrigger.NoEditTriggers)
        t2.setShowGrid(False)
        t2.setAlternatingRowColors(True)

    def _setup_report_view(self) -> None:
        view = self.ui.txtReport
        font = view.font()
        font.setPointSize(REPORT_FONT_PT)
        view.setFont(font)
        view.document().setDocumentMargin(18)
        view.setStyleSheet("QPlainTextEdit { padding: 8px; }")

    def _setup_trend_view(self) -> None:
        self.trend_view = TrendView()
        lay = QVBoxLayout(self.ui.trendHolder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.trend_view)

    def _setup_feedback_bar(self) -> None:
        self.feedback_bar = QWidget(self.ui.resultPage)
        row = QHBoxLayout(self.feedback_bar)
        row.setContentsMargins(0, 0, 0, 0)
        self.feedback_label = QLabel("这份报告准确吗？")
        self.feedback_label.setStyleSheet("color:#666;")
        row.addWidget(self.feedback_label)
        self.btn_feedback_up = QPushButton("👍 准确")
        self.btn_feedback_down = QPushButton("👎 不准确")
        self.btn_feedback_clear = QPushButton("撤回反馈")
        self.btn_feedback_up.clicked.connect(lambda: self._on_feedback("up"))
        self.btn_feedback_down.clicked.connect(lambda: self._on_feedback("down"))
        self.btn_feedback_clear.clicked.connect(self._on_feedback_clear)
        row.addWidget(self.btn_feedback_up)
        row.addWidget(self.btn_feedback_down)
        row.addWidget(self.btn_feedback_clear)
        row.addStretch(1)
        self.ui.resultLayout.insertWidget(1, self.feedback_bar)
        self.feedback_bar.setVisible(False)

    def _setup_mode_switch(self) -> None:
        self.mode_combo = QComboBox(self.ui.topBar)
        self.mode_combo.addItem("本地模式", "local")
        self.mode_combo.addItem("API 模式", "api")
        self.mode_combo.setToolTip("本地模式使用本机数据库；API 模式使用后端统一历史库")
        idx = self.ui.topLayout.indexOf(self.ui.labelMode)
        self.ui.topLayout.insertWidget(max(idx, 0), self.mode_combo)
        self.mode_combo.blockSignals(True)
        saved = str(self._settings.value("backend_mode", "local"))
        self.mode_combo.setCurrentIndex(1 if saved == "api" else 0)
        self.mode_combo.blockSignals(False)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)

    def _on_mode_changed(self, *_) -> None:
        mode = str(self.mode_combo.currentData() or "local")
        self._apply_mode(mode)

    def _apply_mode(self, mode: str, initial: bool = False) -> None:
        if mode == "api":
            settings = QSettings("MicrobeAnalyzer", "ApiDebug")
            base = str(settings.value("base_url", "http://127.0.0.1:8000")).strip()
            key = str(settings.value("api_key", "")).strip()
            client = ApiClient(base, key)
            provider = ApiHistory(client)
            try:
                provider.count()
            except Exception as exc:  # noqa: BLE001 - 把连接失败交给界面
                if not initial:
                    QMessageBox.warning(
                        self, "API 模式连接失败",
                        f"无法连接后端：\n{exc}\n\n"
                        "请确认 start_api.bat 已启动，并在「API 调试台 / 知识库」里保存正确的地址和 Key。",
                    )
                self.mode_combo.blockSignals(True)
                self.mode_combo.setCurrentIndex(0)
                self.mode_combo.blockSignals(False)
                self._settings.setValue("backend_mode", "local")
                if not initial:
                    self._apply_mode("local")
                return
            self.mode = "api"
            self.api_client = client
            self.api_history = provider
            self.history = provider
            self.ui.comboProvider.setEnabled(False)
            self.ui.btnApiSettings.setEnabled(False)
            self.feedback_bar.setVisible(True)
            self.ui.labelModeValue.setText("● API 模式")
            self.ui.labelModeValue.setStyleSheet("color:#1a7f37;font-weight:bold;")
            self._settings.setValue("backend_mode", "api")
        else:
            self.mode = "local"
            self.api_client = None
            self.api_history = None
            self.history = history_mod.History()
            self.ui.comboProvider.setEnabled(True)
            self.ui.btnApiSettings.setEnabled(True)
            self.feedback_bar.setVisible(False)
            self._settings.setValue("backend_mode", "local")
            self._apply_provider()
        self._refresh_trend()
        self._reload_sessions(select_id=None)
        self._set_status(
            "API 模式：使用统一历史库" if self.mode == "api"
            else "本地模式：使用本机历史库"
        )

    def _connect(self) -> None:
        self.ui.btnAnalyze.clicked.connect(self.on_analyze)
        self.ui.btnClear.clicked.connect(lambda: self.ui.inputText.clear())
        self.ui.btnNew.clicked.connect(self._on_new)
        self.ui.btnExport.clicked.connect(self.on_export)
        self.ui.btnBatchImport.clicked.connect(self.on_batch_import)
        self.ui.btnApiSettings.clicked.connect(self.on_api_settings)
        self.ui.btnGuide.clicked.connect(self.start_onboarding)
        self.ui.btnGuide.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ui.comboProvider.currentIndexChanged.connect(self._apply_provider)
        self.ui.sessionList.currentRowChanged.connect(self._on_row_changed)
        self.ui.sessionList.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ui.sessionList.customContextMenuRequested.connect(self._on_session_menu)

    def _maybe_first_run_hint(self) -> None:
        """第一次用、且没有可用 AI 配置时，告诉用户去哪儿填 Key。"""
        if not FIRST_RUN_HINT or self.analyzer.is_live:
            return
        if self.api_store.count() > 0:
            return
        QMessageBox.information(
            self, "还没有配置 AI",
            "程序现在处于「本地模拟」模式——能跑完流程，但评价和报告是模板文字，"
            "不是真正的 AI 分析。\n\n"
            "请点右上角「API 设置」，填入 Base URL、API Key，"
            "点「获取可用模型」后勾选模型并保存。\n\n"
            "（如果甲方已提供 Key，填进去即可。）",
        )

    # ---------------- 模型切换 ----------------
    def _reload_providers(self) -> None:
        combo = self.ui.comboProvider
        combo.blockSignals(True)
        combo.clear()
        configs = self.api_store.all()
        if configs:
            default = self.api_store.default()
            target = -1
            for cfg in configs:
                models = cfg.models or ([cfg.model] if cfg.model else [])
                for m in models:
                    star = bool(default and cfg.id == default.id and m == cfg.model)
                    combo.addItem(("★ " if star else "    ") + f"{cfg.name} / {m}",
                                  (cfg.id, m))
                    if star and target < 0:
                        target = combo.count() - 1
            combo.setCurrentIndex(max(target, 0))
        else:
            env = api_config_mod.ApiConfig.from_env()
            if env:
                combo.addItem(f"（来自 .env）{env.model}", None)
            else:
                combo.addItem("（未配置，使用本地模拟）", None)
        combo.blockSignals(False)
        self._apply_provider()

    def _apply_provider(self, *_) -> None:
        data = self.ui.comboProvider.currentData()
        cfg, model = None, None
        if isinstance(data, tuple) and len(data) == 2:
            cid, model = data
            cfg = self.api_store.get(cid)
        if cfg is None:
            cfg = self.api_store.default()
            model = None
        self.analyzer = analyzer_mod.DeepSeekAnalyzer(cfg, model=model)
        live = self.analyzer.is_live
        self.ui.labelModeValue.setText("● 在线" if live else "○ 未配置（本地模拟）")
        self.ui.labelModeValue.setStyleSheet(
            f"color:{'#1a7f37' if live else '#b26a00'};font-weight:bold;")

    def on_api_settings(self) -> None:
        dlg = ApiSettingsDialog(self.api_store, self)
        dlg.exec()
        self._reload_providers()

    def on_api_debug(self) -> None:
        """打开 HTTP API 调试台（不替代本地分析流程）。"""
        ApiDebugDialog(self).exec()

    def _on_new(self) -> None:
        """新建分析：清空输入框和时间，回到输入页。"""
        self.ui.inputText.clear()
        self.ui.timeInput.clear()
        self._show_input_page("粘贴数据后点「分析」")

    # ---------------- 页面切换 ----------------
    def _show_input_page(self, tip: str = "") -> None:
        self.ui.rightStack.setCurrentWidget(self.ui.inputPage)
        self.ui.btnExport.setEnabled(False)
        if tip:
            self._set_status(tip)

    def _show_result_page(self) -> None:
        self.ui.rightStack.setCurrentWidget(self.ui.resultPage)

    # ---------------- 会话列表 ----------------
    def _set_status(self, text: str, pills: list[tuple[str, str]] | None = None) -> None:
        """底部状态：左边一句说明，右边若干胶囊。"""
        self.ui.labelSummary.setText(text)
        lay = self.ui.pillLayout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for label, value in (pills or []):
            chip = QLabel(f"{label} {value}")
            chip.setObjectName("pill")
            lay.addWidget(chip)

    def _dot_icon(self, filled: bool) -> QIcon:
        """列表前的状态点：实心=已分析，空心=未分析。"""
        if filled in self._dot_cache:
            return self._dot_cache[filled]
        pm = QPixmap(12, 12)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if filled:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#2F7D5D"))
            p.drawEllipse(2, 2, 8, 8)
        else:
            p.setPen(QPen(QColor("#C3D0CA"), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(3, 3, 6, 6)
        p.end()
        icon = QIcon(pm)
        self._dot_cache[filled] = icon
        return icon

    def _reload_sessions(self, select_id: int | None = None) -> None:
        # 按导入顺序升序：最早导入的是第 1 条
        try:
            recs = list(reversed(self.history.all_desc()))
        except Exception as exc:  # noqa: BLE001 - API 断线时保留界面
            self._set_status(f"历史加载失败：{exc}")
            recs = []
        self.ui.listStack.setCurrentWidget(self.ui.listPage if recs else self.ui.emptyPage)
        self.ui.sessionList.blockSignals(True)
        self.ui.sessionList.clear()
        row_of = {}
        for idx, rec in enumerate(recs, start=1):
            item = QListWidgetItem(f"{idx:02d}     {rec.title}")
            item.setIcon(self._dot_icon(bool(rec.report)))
            item.setData(Qt.ItemDataRole.UserRole, rec.id)
            item.setToolTip(f"第 {idx} 条｜物种 {rec.species_count} 个｜H'={rec.shannon_h}｜"
                            f"{'已分析' if rec.report else '未分析'}")
            self.ui.sessionList.addItem(item)
            row_of[rec.id] = idx - 1
        self.ui.sessionList.blockSignals(False)
        self.ui.labelCount.setText(f"共 {len(recs)} 条")

        if select_id is not None and select_id in row_of:
            row = row_of[select_id]
            if self.ui.sessionList.currentRow() != row:
                self.ui.sessionList.setCurrentRow(row)      # 触发 _on_row_changed
                self.ui.sessionList.scrollToItem(self.ui.sessionList.item(row))
            else:
                self._show_record(recs[row])
        elif recs:
            self.ui.sessionList.setCurrentRow(0)
        else:
            self._current = None
            self._show_input_page("还没有任何记录")

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self.ui.sessionList.item(row)
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        rec = self.history.get(rec_id) if rec_id is not None else None
        if rec:
            self._show_record(rec)

    def _on_session_menu(self, pos) -> None:
        item = self.ui.sessionList.itemAt(pos)
        if item is None:
            return
        rec_id = item.data(Qt.ItemDataRole.UserRole)
        rec = self.history.get(rec_id) if rec_id is not None else None
        if rec is None:
            return

        menu = QMenu(self)
        act_load = QAction("载入到输入框", self)
        act_delete = QAction("删除该记录", self)
        menu.addAction(act_load)
        menu.addSeparator()
        menu.addAction(act_delete)
        chosen = menu.exec(self.ui.sessionList.mapToGlobal(pos))

        if chosen is act_load:
            self._load_record_to_input(rec)
        elif chosen is act_delete:
            self._delete_record(rec)

    def _load_record_to_input(self, rec) -> None:
        text = rec.raw_text
        if not text:
            text = "，".join(f"{k}: {v:g}" for k, v in rec.species.items())
            if rec.unit:
                text += f"。浓度单位({rec.unit})"
        self.ui.inputText.setPlainText(text)
        self.ui.timeInput.setText(rec.sample_time or "")
        self._show_input_page(f"已载入 {rec.title} 的数据，可以修改后重新分析")

    def _delete_record(self, rec) -> None:
        reply = QMessageBox.question(
            self, "删除记录",
            f"确定删除「{rec.title}」这条记录吗？删除后无法恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.history.delete(rec.id)
        # 删除后不清算已有的"较上次变化"快照（那是当时算的），只刷新展示
        self._refresh_trend()
        self._reload_sessions(select_id=None)
        self._set_status(f"已删除「{rec.title}」｜历史库还剩 {self.history.count()} 条")

    # ---------------- 展示一条记录 ----------------
    def _on_feedback(self, verdict: str) -> None:
        if self.mode != "api":
            return
        rec = self._current
        if rec is None or not rec.id or self.api_client is None:
            return
        if not rec.report:
            QMessageBox.information(self, "提示", "这条记录还没有报告，不能反馈。")
            return
        try:
            self.api_client.feedback(rec.id, verdict)
        except Exception as exc:  # noqa: BLE001 - 反馈失败不阻塞主流程
            QMessageBox.warning(self, "反馈失败", str(exc))
            return
        rec.feedback = verdict
        self._update_feedback_buttons()
        self._set_status("已点赞，已加入内部历史案例库" if verdict == "up"
                         else "已点踩，不会进入历史案例库")

    def _on_feedback_clear(self) -> None:
        if self.mode != "api" or self._current is None or not self._current.id:
            return
        if self.api_client is None:
            return
        try:
            self.api_client.delete_feedback(self._current.id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "撤回失败", str(exc))
            return
        self._current.feedback = ""
        self._update_feedback_buttons()
        self._set_status("已撤回反馈，历史记录仍然保留")

    def _update_feedback_buttons(self) -> None:
        rec = self._current
        visible = self.mode == "api"
        self.feedback_bar.setVisible(visible)
        if not visible:
            return
        has_report = bool(rec and rec.report and rec.id)
        self.btn_feedback_up.setEnabled(has_report)
        self.btn_feedback_down.setEnabled(has_report)
        verdict = getattr(rec, "feedback", "") if rec else ""
        self.btn_feedback_clear.setEnabled(bool(verdict))
        if verdict == "up":
            self.feedback_label.setText("已点赞：这份报告会作为内部历史案例")
        elif verdict == "down":
            self.feedback_label.setText("已点踩：这份报告不会进入历史案例")
        elif has_report:
            self.feedback_label.setText("这份报告准确吗？")
        else:
            self.feedback_label.setText("这条记录还没有报告")

    def _show_record(self, rec) -> None:
        self._current = rec
        self._change_map = {d.get("species"): d for d in (rec.changes or [])}
        self._trends = rec.trends or []

        if rec.species:
            m = metrics_mod.compute(rec.species)
            self._fill_metrics(m)
            self._fill_evaluations(m, rec.evaluations or [])
        else:
            self.ui.tblMetrics.setRowCount(0)
            self.ui.tblEvaluations.setRowCount(0)

        text = rec.report or ("（这条记录还没有生成 AI 报告。"
                               "可以右键「载入到输入框」后重新分析。）")
        if rec.error_text:
            banner = ("⚠ 本次 AI 调用失败，以下是本地模拟内容。\n"
                      f"{rec.error_text.splitlines()[0]}\n"
                      "（详见 data/last_error.txt）\n\n")
            text = banner + text
        self._show_report(text, rec.references or [])
        self._show_result_page()
        self.ui.btnExport.setEnabled(bool(rec.species))
        self._update_feedback_buttons()

    def _fill_metrics(self, metrics: metrics_mod.MetricsResult) -> None:
        t = self.ui.tblMetrics
        t.setRowCount(len(metrics.rows))
        for i, r in enumerate(metrics.rows):
            values = [r.name, f"{r.concentration:.3f}", f"{r.percent:.1f}",
                      "✓" if r.is_dominant else "", "✓" if r.is_absolute else ""]
            for j, v in enumerate(values):
                item = QTableWidgetItem(v)
                if j >= 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if r.is_absolute:
                    item.setBackground(QBrush(COLOR_ABSOLUTE))
                elif r.is_dominant:
                    item.setBackground(QBrush(COLOR_DOMINANT))
                t.setItem(i, j, item)
        t.resizeColumnsToContents()
        header = t.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        t.setColumnWidth(0, 220)
        for c in (1, 2):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        for c in (3, 4):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)

    def _change_cell(self, name: str) -> QTableWidgetItem:
        d = self._change_map.get(name) or {}
        item = QTableWidgetItem(d.get("text") or "—")
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        pct = d.get("pct")
        if isinstance(pct, (int, float)):
            if pct >= 30:
                item.setForeground(QBrush(COLOR_UP))
            elif pct <= -30:
                item.setForeground(QBrush(COLOR_DOWN))
        return item

    def _fill_evaluations(self, metrics: metrics_mod.MetricsResult, evaluations: list) -> None:
        emap = {e.get("species"): e for e in evaluations}
        t = self.ui.tblEvaluations
        t.setRowCount(len(metrics.rows))
        for i, r in enumerate(metrics.rows):
            ev = emap.get(r.name) or {}
            cells = [
                QTableWidgetItem(r.name),
                QTableWidgetItem(f"{r.concentration:.3f}"),
                QTableWidgetItem(f"{r.percent:.1f}"),
                self._change_cell(r.name),
                QTableWidgetItem(ev.get("comment") or "（无评价）"),
                QTableWidgetItem(ev.get("advice") or ""),
            ]
            for j, item in enumerate(cells):
                if 1 <= j <= 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if r.is_absolute and j < 4:
                    item.setBackground(QBrush(COLOR_ABSOLUTE))
                elif r.is_dominant and j < 4:
                    item.setBackground(QBrush(COLOR_DOMINANT))
                t.setItem(i, j, item)
        header = t.horizontalHeader()
        for col in range(4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        # 必须在列宽确定之后再做行高，否则换行宽度变了文字会被截断
        t.resizeRowsToContents()

    def _show_report(self, text: str, references: list | None = None) -> None:
        """把「情况/变化/建议」各段拆开，并在末尾附上参考来源。"""
        lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
        body = "\n\n".join(lines)
        if references:
            ref_lines = ["────────  参考来源  ────────"]
            for ref in references:
                start, end = ref.get("page_start"), ref.get("page_end")
                pages = f"第{start}页" if start == end else f"第{start}-{end}页"
                flag = " ✔已引用" if ref.get("cited") else ""
                ref_lines.append(
                    f"[{ref.get('label', '')}] 《{ref.get('book', '')}》{pages}{flag}"
                )

            body = body + "\n\n\n" + "\n".join(ref_lines)
        self.ui.txtReport.setPlainText(body)

    # ---------------- 分析流程 ----------------
    def on_analyze(self) -> None:
        if self.mode == "api":
            self._on_api_analyze()
            return
        raw = self.ui.inputText.toPlainText()
        parsed = parser_mod.parse(raw)
        if not parsed.species:
            QMessageBox.warning(self, "解析失败", "\n".join(parsed.warnings) or "没有识别到任何物种数据")
            return

        if self._confirm_action.isChecked():
            dlg = ConfirmDialog(parsed, self)
            if dlg.exec() != ConfirmDialog.DialogCode.Accepted:
                self._set_status("已取消（解析结果未确认）")
                return
            parsed.species = dlg.species
            parsed.strategy = (parsed.strategy or "") + " + 人工核对"

        metrics = metrics_mod.compute(parsed.species)
        last = self.history.last()
        changes = trend_mod.compute_changes(
            parsed.species, last.species if last else None, parsed.change or None)
        trends = trend_mod.detect_trends(changes)
        changes_list = [{"species": c.species, "pct": c.pct, "source": c.source, "text": c.text}
                        for c in changes.values()]
        trends_list = [{"rule": t.rule, "detail": t.detail, "meaning": t.meaning} for t in trends]
        prev_time = last.imported_at if last else ""
        sample_time = self.ui.timeInput.text().strip()

        # 先存档，会话列表立刻出现这一条
        rec_id = self.history.save(history_mod.Record(
            species=parsed.species, unit=parsed.unit, sample_time=sample_time,
            total=metrics.total, species_count=metrics.species_count,
            shannon_h=metrics.shannon_h, raw_text=raw,
            changes=changes_list, trends=trends_list,
        ))
        self._pending = (parsed, metrics, changes_list, trends_list, prev_time, rec_id, raw, sample_time)

        self._reload_sessions(select_id=rec_id)
        self.ui.tabResults.setCurrentIndex(2)
        self._show_report("正在调用 " + self.analyzer.mode_text + " 分析…")
        self.ui.btnAnalyze.setEnabled(False)
        self.ui.btnAnalyze.setText("分析中…")
        self._busy.cover()
        self.ui.btnExport.setEnabled(False)
        msg = f"分析中…（阶段一：{metrics.species_count} 个物种逐个评价；阶段二：综合成报告）"
        if last:
            msg += f"｜对比基准：{last.imported_at}"
        self._set_status(msg)

        payload = analyzer_mod.build_payload(parsed, metrics, changes, trends, prev_time)
        self._thread = QThread(self)
        self._worker = AnalyzeWorker(self.analyzer, payload)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        # 必须连到绑定方法（self 是 QObject），Qt 才会自动排队回主线程
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_api_analyze(self) -> None:
        raw = self.ui.inputText.toPlainText()
        if not raw.strip():
            QMessageBox.information(self, "提示", "请先输入固定文本。")
            return
        parsed = parser_mod.parse(raw)
        if not parsed.species:
            QMessageBox.warning(self, "解析失败", "\n".join(parsed.warnings) or "没有识别到任何物种数据")
            return
        if self.api_client is None:
            QMessageBox.warning(self, "API 模式", "API 客户端未初始化，请重新切换模式。")
            return
        sample_time = self.ui.timeInput.text().strip()
        self._api_pending = (raw, sample_time)
        self.ui.btnAnalyze.setEnabled(False)
        self.ui.btnAnalyze.setText("分析中…")
        self._busy.cover()
        self.ui.btnExport.setEnabled(False)
        self._show_report("正在调用 API 分析…")
        self._set_status("API 分析中…（服务端会使用统一历史库和内部案例）")
        worker = ApiCallWorker(
            lambda: self.api_client.evaluate(raw, sample_time=sample_time),
            self,
        )
        self._api_worker = worker
        worker.done.connect(self._on_api_analysis_done)
        worker.failed.connect(self._on_api_analysis_failed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _reset_api_buttons(self) -> None:
        self.ui.btnAnalyze.setEnabled(True)
        self.ui.btnAnalyze.setText("分析")
        self._busy.hide()

    def _on_api_analysis_failed(self, message: str) -> None:
        self._api_pending = None
        self._reset_api_buttons()
        self._set_status(f"API 分析失败：{message}")
        QMessageBox.warning(self, "API 分析失败", message)

    def _on_api_analysis_done(self, data) -> None:
        if self._api_pending is None:
            return
        raw, sample_time = self._api_pending
        self._api_pending = None
        self._reset_api_buttons()
        if not isinstance(data, dict):
            self._set_status("API 返回格式不正确")
            return
        parsed = parser_mod.parse(raw)
        metrics = data.get("metrics") or {}
        meta = data.get("meta") or {}
        rec_id = int(meta.get("history_id") or 0)
        warnings = data.get("warnings") or []
        rec = history_mod.Record(
            id=rec_id,
            sample_time=str(data.get("sample_time") or sample_time),
            unit=parsed.unit,
            total=float(metrics.get("total") or 0.0),
            species_count=int(metrics.get("species_count") or 0),
            shannon_h=float(metrics.get("shannon_h") or 0.0),
            species=dict(parsed.species),
            report=str(data.get("report_text") or ""),
            raw_text=raw,
            evaluations=list(data.get("evaluations") or []),
            changes=list(data.get("changes") or []),
            trends=list(data.get("trends") or []),
            analysis_source=str(meta.get("analysis_source") or ""),
            error_text="；".join(str(x) for x in warnings) if data.get("degraded") else "",
            references=list(data.get("references") or []),
            metrics=dict(metrics),
        )
        self._refresh_trend()
        self._reload_sessions(select_id=rec_id)
        self._show_record(rec)
        self._set_status(
            f"API 完成 · {rec.analysis_source or '未知来源'}",
            [
                ("物种", str(rec.species_count)),
                ("H'", f"{rec.shannon_h}"),
                ("评价", f"{len(rec.evaluations)}/{rec.species_count}"),
                ("趋势", f"{len(rec.trends)}"),
            ],
        )

    def _on_analysis_done(self, analysis) -> None:
        if self._pending is None:
            return
        parsed, metrics, changes_list, trends_list, prev_time, rec_id, raw, sample_time = self._pending
        self._pending = None

        self.history.update_analysis(rec_id, history_mod.Record(
            species=parsed.species, unit=parsed.unit, sample_time=sample_time,
            total=metrics.total, species_count=metrics.species_count,
            shannon_h=metrics.shannon_h, raw_text=raw, report=analysis.report,
            evaluations=[{"species": e.species, "comment": e.comment, "advice": e.advice}
                         for e in analysis.evaluations],
            changes=changes_list, trends=trends_list,
            analysis_source=analysis.source, error_text=analysis.error,
            references=analysis.references,        ))

        self._refresh_trend()
        self._reload_sessions(select_id=rec_id)
        self.ui.btnAnalyze.setEnabled(True)
        self.ui.btnAnalyze.setText("分析")
        self._busy.hide()

        src = next((c["source"] for c in changes_list if c["source"] != "无"), "—")
        covered = len({e.species for e in analysis.evaluations})
        head = f"完成 · {analysis.source}" + ("　⚠ 调用失败" if analysis.error else "")
        self._set_status(head, [
            ("物种", f"{metrics.species_count}"),
            ("H'", f"{metrics.shannon_h}"),
            ("评价", f"{covered}/{metrics.species_count}"),
            ("趋势", f"{len(trends_list)}"),
            ("对比", src),
        ])

        if analysis.error and SHOW_ERROR_DIALOG:
            QMessageBox.warning(
                self, "AI 调用失败",
                f"{analysis.error}\n\n"
                f"本次已降级为「本地模拟」，结果仅供参考。\n\n"
                f"原始请求/响应已写入：\n{ROOT / 'data' / 'last_error.txt'}",
            )

    def _refresh_trend(self) -> None:
        try:
            self.trend_view.load(self.history.recent(limit=500))
        except Exception as exc:  # noqa: BLE001 - 趋势加载失败不应影响主界面
            self._set_status(f"趋势加载失败：{exc}")

    # ---------------- 批量导入 ----------------
    def on_batch_import(self) -> None:
        if self.mode == "api":
            QMessageBox.information(
                self, "API 模式",
                "API 模式下的批量导入还没有接到桌面界面。\n\n"
                "请先切回本地模式使用批量导入，或使用 /docs 调用 /api/v1/batch/import。",
            )
            return
        dlg = BatchDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        saved = skipped = 0
        for it in dlg.items:
            if not it.parsed or not it.parsed.species:
                skipped += 1
                continue
            m = metrics_mod.compute(it.parsed.species)
            self.history.save(history_mod.Record(
                species=it.parsed.species, unit=it.parsed.unit,
                sample_time=it.sample_time, total=m.total,
                species_count=m.species_count, shannon_h=m.shannon_h,
                raw_text=it.text,
            ))
            saved += 1
        self._refresh_trend()
        last = self.history.last()
        self._reload_sessions(select_id=last.id if last else None)
        self._set_status(
            f"批量导入完成：新增 {saved} 条，跳过 {skipped} 条｜历史库共 {self.history.count()} 条")
        QMessageBox.information(
            self, "导入完成",
            f"已导入 {saved} 条记录" + (f"，跳过 {skipped} 条无效数据" if skipped else "")
            + "。\n\n这批记录只有数据没有 AI 报告，需要时右键选「载入到输入框」再分析。",
        )

    # ---------------- 导出 ----------------
    def on_export(self) -> None:
        rec = self._current
        if rec is None or not rec.species:
            QMessageBox.information(self, "提示", "请先在左侧选择一条记录")
            return
        metrics = metrics_mod.compute(rec.species)
        parsed = parser_mod.ParsedSample(species=dict(rec.species), unit=rec.unit)
        analysis = analyzer_mod.AnalysisResult(
            report=rec.report,
            evaluations=[analyzer_mod.SpeciesEval(species=e.get("species", ""),
                                                  comment=e.get("comment", ""),
                                                  advice=e.get("advice", ""))
                         for e in (rec.evaluations or [])],
            source=rec.analysis_source or "（未分析）",
            references=rec.references or [],
        )
        change_text = {d.get("species"): (d.get("text") or "—") for d in (rec.changes or [])}
        trends = [trend_mod.TrendHit(rule=t.get("rule", ""), detail=t.get("detail", ""),
                                     meaning=t.get("meaning", ""))
                  for t in (rec.trends or [])]

        default = f"微生物检测_{rec.title.replace(':', '').replace(' ', '_')}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "导出表格",
                                              str(ROOT / default), "Excel 文件 (*.xlsx)")
        if not path:
            return
        try:
            exporter_mod.export(
                path, sample_time=rec.sample_time, parsed=parsed, metrics=metrics,
                analysis=analysis, changes=change_text, trends=trends,
                previous_time="",
            )
        except PermissionError:
            QMessageBox.critical(self, "导出失败", "文件被占用（可能正开着 Excel），请关闭后重试。")
            return
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", f"{type(exc).__name__}: {exc}")
            return
        QMessageBox.information(self, "导出成功", f"已保存到：\n{path}")
        self._set_status(f"已导出：{path}")
