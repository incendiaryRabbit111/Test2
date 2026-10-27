"""主窗口（C 布局）：左侧会话列表，右侧详情。

一次检测 = 一条会话记录。点左边任意一条，右边立刻还原当时的
指标、物种评价、AI 报告；趋势图始终展示全部记录的走势。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHeaderView,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QTableWidgetItem,
    QVBoxLayout,
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
from app.api_dialog import ApiSettingsDialog
from app.batch_dialog import BatchDialog
from app.confirm_dialog import ConfirmDialog
from app.generated.ui_main_window import Ui_MainWindow
from app.paths import ROOT
from app.sample import SAMPLE_TEXT
from app.trend_view import TrendView

COLOR_ABSOLUTE = QColor("#ffe0e0")
COLOR_DOMINANT = QColor("#eaf6ea")
COLOR_UP = QColor("#c0392b")
COLOR_DOWN = QColor("#1f6feb")
REPORT_FONT_PT = 11
FIRST_RUN_HINT = True          # 首次启动且没配置 AI 时，弹一次引导（测试里关掉）
SHOW_ERROR_DIALOG = True       # 调用失败时弹窗（测试里必须关掉，否则模态阻塞）


class AnalyzeWorker(QObject):
    """把 LLM 调用放到子线程，避免界面卡死。"""

    finished = Signal(object)

    def __init__(self, analyzer, payload: dict) -> None:
        super().__init__()
        self.analyzer = analyzer
        self.payload = payload

    def run(self) -> None:
        self.finished.emit(self.analyzer.analyze(self.payload))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.history = history_mod.History()
        self.api_store = api_config_mod.ApiConfigStore()
        self.api_store.seed_from_env()        # 首次运行把 .env 里的 key 导进配置库
        self.analyzer = analyzer_mod.DeepSeekAnalyzer(self.api_store.default())
        self._pending = None            # 分析中的上下文
        self._change_map: dict = {}
        self._trends: list = []
        self._current = None            # 当前展示的 Record
        self._thread = None
        self._worker = None

        self._setup_tables()
        self._setup_report_view()
        self._setup_trend_view()
        self._connect()
        self.ui.mainLayout.setStretchFactor(self.ui.splitter, 1)
        self.ui.leftLayout.setStretchFactor(self.ui.sessionList, 1)
        self.ui.inputText.setMinimumHeight(300)

        self._reload_providers()
        self.ui.inputText.setPlainText(SAMPLE_TEXT)

        self._refresh_trend()
        self._reload_sessions(select_id=None)
        if self.history.count() == 0:
            self._show_input_page("还没有任何记录，粘贴数据后点「分析」")
        else:
            self.ui.labelSummary.setText(f"已载入 {self.history.count()} 条历史记录")

    # ---------------- 初始化 ----------------
    def _setup_tables(self) -> None:
        t1 = self.ui.tblMetrics
        t1.setColumnCount(5)
        t1.setHorizontalHeaderLabels(["物种", "浓度", "相对丰度(%)", "优势种群", "绝对优势种群"])
        t1.verticalHeader().setVisible(False)
        t1.setEditTriggers(t1.EditTrigger.NoEditTriggers)

        t2 = self.ui.tblEvaluations
        t2.setColumnCount(6)
        t2.setHorizontalHeaderLabels(
            ["物种", "浓度", "相对丰度(%)", "较上次变化", "综合评价", "指导意见"])
        t2.verticalHeader().setVisible(False)
        t2.setWordWrap(True)
        t2.setEditTriggers(t2.EditTrigger.NoEditTriggers)

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

    def _connect(self) -> None:
        self.ui.btnAnalyze.clicked.connect(self.on_analyze)
        self.ui.btnClear.clicked.connect(lambda: self.ui.inputText.clear())
        self.ui.btnNew.clicked.connect(self._on_new)
        self.ui.btnExport.clicked.connect(self.on_export)
        self.ui.btnBatchImport.clicked.connect(self.on_batch_import)
        self.ui.btnApiSettings.clicked.connect(self.on_api_settings)
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
            self.ui.labelSummary.setText(tip)

    def _show_result_page(self) -> None:
        self.ui.rightStack.setCurrentWidget(self.ui.resultPage)

    # ---------------- 会话列表 ----------------
    def _reload_sessions(self, select_id: int | None = None) -> None:
        recs = self.history.all_desc()
        self.ui.sessionList.blockSignals(True)
        self.ui.sessionList.clear()
        row_of = {}
        for i, rec in enumerate(recs):
            item = QListWidgetItem(f"{rec.title}\n{rec.subtitle}")
            item.setData(Qt.ItemDataRole.UserRole, rec.id)
            item.setToolTip(f"{rec.title}\n物种 {rec.species_count} 个　H'={rec.shannon_h}\n"
                            f"{'已分析' if rec.report else '未分析'}")
            self.ui.sessionList.addItem(item)
            row_of[rec.id] = i
        self.ui.sessionList.blockSignals(False)
        self.ui.labelCount.setText(f"共 {len(recs)} 条")

        if select_id is not None and select_id in row_of:
            row = row_of[select_id]
            if self.ui.sessionList.currentRow() != row:
                self.ui.sessionList.setCurrentRow(row)      # 触发 _on_row_changed
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
        self.ui.labelSummary.setText(f"已删除「{rec.title}」｜历史库还剩 {self.history.count()} 条")

    # ---------------- 展示一条记录 ----------------
    def _show_record(self, rec) -> None:
        self._current = rec
        src = f"　｜　分析来源：{rec.analysis_source}" if rec.analysis_source else "　｜　未分析"
        self.ui.labelSession.setText(f"当前记录：{rec.title}{src}")
        self._change_map = {d.get("species"): d for d in (rec.changes or [])}
        self._trends = rec.trends or []

        if rec.species:
            m = metrics_mod.compute(rec.species)
            self._fill_metrics(m)
            self._fill_evaluations(m, rec.evaluations or [])
        else:
            self.ui.tblMetrics.setRowCount(0)
            self.ui.tblEvaluations.setRowCount(0)

        if rec.error_text:
            banner = ("⚠ 本次 AI 调用失败，以下是本地模拟内容。\n"
                      f"{rec.error_text.splitlines()[0]}\n"
                      "（详见 data/last_error.txt）\n\n")
            self._show_report(banner + (rec.report or ""))
        else:
            self._show_report(rec.report or "（这条记录还没有生成 AI 报告。"
                                             "可以右键「载入到输入框」后重新分析。）")
        self._show_result_page()
        self.ui.btnExport.setEnabled(bool(rec.species))

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
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

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
        t.resizeRowsToContents()
        header = t.horizontalHeader()
        for col in range(4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

    def _show_report(self, text: str) -> None:
        """把「情况/变化/建议」各段拆开、段间留白，避免糊成一片。"""
        lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
        self.ui.txtReport.setPlainText("\n\n".join(lines))

    # ---------------- 分析流程 ----------------
    def on_analyze(self) -> None:
        raw = self.ui.inputText.toPlainText()
        parsed = parser_mod.parse(raw)
        if not parsed.species:
            QMessageBox.warning(self, "解析失败", "\n".join(parsed.warnings) or "没有识别到任何物种数据")
            return

        if self.ui.chkConfirm.isChecked():
            dlg = ConfirmDialog(parsed, self)
            if dlg.exec() != ConfirmDialog.DialogCode.Accepted:
                self.ui.labelSummary.setText("已取消（解析结果未确认）")
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
        self.ui.btnExport.setEnabled(False)
        msg = f"分析中…（阶段一：{metrics.species_count} 个物种逐个评价；阶段二：综合成报告）"
        if last:
            msg += f"｜对比基准：{last.imported_at}"
        self.ui.labelSummary.setText(msg)

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
        ))

        self._refresh_trend()
        self._reload_sessions(select_id=rec_id)
        self.ui.btnAnalyze.setEnabled(True)

        src = next((c["source"] for c in changes_list if c["source"] != "无"), "无对比数据")
        covered = len({e.species for e in analysis.evaluations})
        tip = (f"完成（{analysis.source}）｜物种 {metrics.species_count} 种｜H'={metrics.shannon_h}"
               f"｜已评价 {covered}/{metrics.species_count} 种｜变化来源：{src}"
               f"｜趋势命中 {len(trends_list)} 条")
        if analysis.error:
            tip += "　⚠ 调用失败，见详情"
        self.ui.labelSummary.setText(tip)

        if analysis.error and SHOW_ERROR_DIALOG:
            QMessageBox.warning(
                self, "AI 调用失败",
                f"{analysis.error}\n\n"
                f"本次已降级为「本地模拟」，结果仅供参考。\n\n"
                f"原始请求/响应已写入：\n{ROOT / 'data' / 'last_error.txt'}",
            )

    def _refresh_trend(self) -> None:
        self.trend_view.load(self.history.recent(limit=500))

    # ---------------- 批量导入 ----------------
    def on_batch_import(self) -> None:
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
        self.ui.labelSummary.setText(
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
        self.ui.labelSummary.setText(f"已导出：{path}")
