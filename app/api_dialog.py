"""AI API 配置管理对话框。

流程按「先连上、再选模型」设计：
  ① 填 Base URL
  ② 填 API Key  →  自动/手动「获取可用模型」
  ③ 在模型列表里勾选要用的（可多选，也可手动补）
  ④ 填名称、temperature、超时、设为默认
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.analyzer import DeepSeekAnalyzer
from app.api_config import PRESETS, ApiConfig, ApiConfigStore, fetch_models


class ApiSettingsDialog(QDialog):
    def __init__(self, store: ApiConfigStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self._current: ApiConfig | None = None
        self._loading = False
        self.setWindowTitle("AI API 设置")
        self.resize(800, 600)

        root = QVBoxLayout(self)

        tip = QLabel("只支持「OpenAI 兼容」协议——DeepSeek / 通义 / Kimi / 智谱 / Ollama 都是这套。"
                     "API Key 用 Windows DPAPI 加密后存在本机，换台电脑解不开。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#555; background:#f6f8fa; padding:8px; border-radius:4px;")
        root.addWidget(tip)

        body = QHBoxLayout()
        root.addLayout(body, 1)

        # ---------------- 左侧：已有配置 ----------------
        left = QVBoxLayout()
        left.addWidget(QLabel("已保存的配置"))
        self.list = QListWidget()
        self.list.setMinimumWidth(230)
        self.list.currentRowChanged.connect(self._on_select)
        left.addWidget(self.list, 1)

        btns = QHBoxLayout()
        self.btn_add = QPushButton("新增")
        self.btn_del = QPushButton("删除")
        self.btn_add.clicked.connect(self._on_add)
        self.btn_del.clicked.connect(self._on_delete)
        btns.addWidget(self.btn_add)
        btns.addWidget(self.btn_del)
        left.addLayout(btns)
        body.addLayout(left)

        # ---------------- 右侧：表单 ----------------
        form_box = QGroupBox("配置详情")
        form = QFormLayout(form_box)

        # ① 先连上
        self.cbo_preset = QComboBox()
        self.cbo_preset.addItem("（从预设填充…）", None)
        for p in PRESETS:
            self.cbo_preset.addItem(p["name"], p)
        self.cbo_preset.currentIndexChanged.connect(self._on_preset)
        form.addRow("预设", self.cbo_preset)

        self.ed_base = QLineEdit()
        self.ed_base.setPlaceholderText("https://api.deepseek.com")
        self.ed_base.editingFinished.connect(self._maybe_auto_fetch)
        form.addRow("① Base URL", self.ed_base)

        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_key.setPlaceholderText("sk-...")
        self.ed_key.editingFinished.connect(self._maybe_auto_fetch)
        self.chk_show = QCheckBox("显示")
        self.chk_show.toggled.connect(
            lambda on: self.ed_key.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        key_row.addWidget(self.ed_key, 1)
        key_row.addWidget(self.chk_show)
        key_wrap = QWidget()
        key_wrap.setLayout(key_row)
        form.addRow("② API Key", key_wrap)

        # ③ 拉取 + 勾选模型
        model_wrap = QWidget()
        mv = QVBoxLayout(model_wrap)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(6)

        fetch_row = QHBoxLayout()
        fetch_row.setContentsMargins(0, 0, 0, 0)
        self.btn_fetch = QPushButton("获取可用模型")
        self.btn_fetch.setToolTip("调用 GET {Base URL}/models，列出这个 Key 能用的全部模型")
        self.btn_fetch.clicked.connect(self._on_fetch)
        self.lbl_fetch = QLabel("")
        self.lbl_fetch.setWordWrap(True)
        fetch_row.addWidget(self.btn_fetch)
        fetch_row.addWidget(self.lbl_fetch, 1)
        mv.addLayout(fetch_row)

        self.model_list = QListWidget()
        self.model_list.setMinimumHeight(120)
        self.model_list.setToolTip("勾选要在这个网关上启用的模型（可多选）")
        mv.addWidget(self.model_list)

        manual_row = QHBoxLayout()
        manual_row.setContentsMargins(0, 0, 0, 0)
        self.ed_manual = QLineEdit()
        self.ed_manual.setPlaceholderText("接口不支持自动获取时，在这里手动加：如 deepseek-chat")
        self.btn_manual = QPushButton("添加")
        self.btn_manual.clicked.connect(self._on_manual_add)
        manual_row.addWidget(self.ed_manual, 1)
        manual_row.addWidget(self.btn_manual)
        mv.addLayout(manual_row)

        form.addRow("③ 可用模型", model_wrap)

        # ④ 其它
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("给这条配置起个名字，如「公司 DeepSeek」")
        form.addRow("名称", self.ed_name)

        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(0.0, 2.0)
        self.spin_temp.setSingleStep(0.1)
        self.spin_temp.setDecimals(1)
        self.spin_temp.setValue(0.2)
        self.spin_temp.setToolTip("越低结论越稳定；0 = 同一输入几乎一字不差")
        form.addRow("temperature", self.spin_temp)

        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(10, 600)
        self.spin_timeout.setValue(180)
        self.spin_timeout.setSuffix(" 秒")
        form.addRow("超时", self.spin_timeout)

        self.chk_default = QCheckBox("设为默认（程序启动时用这条）")
        form.addRow("", self.chk_default)

        test_row = QHBoxLayout()
        test_row.setContentsMargins(0, 0, 0, 0)
        self.btn_test = QPushButton("测试连接")
        self.btn_test.clicked.connect(self._on_test)
        self.lbl_test = QLabel("")
        self.lbl_test.setWordWrap(True)
        test_row.addWidget(self.btn_test)
        test_row.addWidget(self.lbl_test, 1)
        form.addRow("", test_row)

        body.addWidget(form_box, 1)

        # ---------------- 底部 ----------------
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                               | QDialogButtonBox.StandardButton.Close)
        box.button(QDialogButtonBox.StandardButton.Save).setText("保存当前配置")
        box.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        box.accepted.connect(self._on_save)
        box.rejected.connect(self.accept)
        root.addWidget(box)

        self._reload()
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._clear_form()

    # ---------------- 左侧列表 ----------------
    def _reload(self, select_id: int | None = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        row_to_select = -1
        for i, cfg in enumerate(self.store.all()):
            mark = "★ " if cfg.is_default else "   "
            extra = f"　[{len(cfg.models)} 个模型]" if len(cfg.models) > 1 else ""
            item = QListWidgetItem(f"{mark}{cfg.name or cfg.model}{extra}")
            item.setToolTip(f"{cfg.base_url}\n模型：{'、'.join(cfg.models) or cfg.model}")
            item.setData(Qt.ItemDataRole.UserRole, cfg.id)
            self.list.addItem(item)
            if select_id is not None and cfg.id == select_id:
                row_to_select = i
        self.list.blockSignals(False)
        if row_to_select >= 0:
            self.list.setCurrentRow(row_to_select)

    def _on_select(self, row: int) -> None:
        if row < 0:
            return
        cid = self.list.item(row).data(Qt.ItemDataRole.UserRole)
        cfg = self.store.get(cid) if cid is not None else None
        if cfg:
            self._load_form(cfg)

    def _load_form(self, cfg: ApiConfig) -> None:
        self._loading = True
        self._current = cfg
        self.ed_base.setText(cfg.base_url)
        self.ed_key.setText(cfg.api_key)
        self.ed_name.setText(cfg.name)
        self.spin_temp.setValue(cfg.temperature)
        self.spin_timeout.setValue(cfg.timeout)
        self.chk_default.setChecked(cfg.is_default)
        self.model_list.clear()
        for m in (cfg.models or ([cfg.model] if cfg.model else [])):
            self._add_model_item(m, checked=True)
        self.lbl_fetch.setText("")
        self.lbl_test.setText("")
        self._loading = False

    def _clear_form(self) -> None:
        self._loading = True
        self._current = None
        self.ed_base.clear()
        self.ed_key.clear()
        self.ed_name.clear()
        self.ed_manual.clear()
        self.model_list.clear()
        self.spin_temp.setValue(0.2)
        self.spin_timeout.setValue(180)
        self.chk_default.setChecked(self.store.count() == 0)
        self.lbl_fetch.setText("")
        self.lbl_test.setText("")
        self._loading = False

    # ---------------- 模型列表 ----------------
    def _add_model_item(self, name: str, checked: bool = True) -> bool:
        name = name.strip()
        if not name:
            return False
        for i in range(self.model_list.count()):
            if self.model_list.item(i).text() == name:
                if checked:
                    self.model_list.item(i).setCheckState(Qt.CheckState.Checked)
                return False
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.model_list.addItem(item)
        return True

    def _checked_models(self) -> list[str]:
        return [self.model_list.item(i).text()
                for i in range(self.model_list.count())
                if self.model_list.item(i).checkState() == Qt.CheckState.Checked]

    def _on_manual_add(self) -> None:
        if self._add_model_item(self.ed_manual.text()):
            self.ed_manual.clear()
            self.lbl_fetch.setText("已手动添加")
            self.lbl_fetch.setStyleSheet("color:#1a7f37;")

    def _on_fetch(self) -> None:
        base = self.ed_base.text().strip()
        key = self.ed_key.text().strip()
        if not base:
            self.lbl_fetch.setText("⚠ 先填 Base URL")
            self.lbl_fetch.setStyleSheet("color:#b26a00;")
            return
        keep = set(self._checked_models())
        self.btn_fetch.setEnabled(False)
        self.lbl_fetch.setText("正在获取…")
        self.lbl_fetch.setStyleSheet("color:#666;")
        self.repaint()

        models, err = fetch_models(base, key)
        self.btn_fetch.setEnabled(True)

        if err:
            self.lbl_fetch.setText(f"❌ {err}　（可在下面手动添加模型名）")
            self.lbl_fetch.setStyleSheet("color:#c0392b;")
            return

        self.model_list.clear()
        for m in models:
            self._add_model_item(m, checked=(m in keep) if keep else True)
        self.lbl_fetch.setText(f"✅ 拿到 {len(models)} 个模型，勾选要用的")
        self.lbl_fetch.setStyleSheet("color:#1a7f37;")

    def _maybe_auto_fetch(self) -> None:
        """URL 和 Key 都填了、且还没拉过模型时，自动拉一次。"""
        if self._loading or not self.btn_fetch.isEnabled():
            return
        if self.ed_base.text().strip() and self.ed_key.text().strip() \
                and self.model_list.count() == 0:
            self._on_fetch()

    # ---------------- 操作 ----------------
    def _on_preset(self, idx: int) -> None:
        preset = self.cbo_preset.itemData(idx)
        if not preset:
            return
        self.ed_name.setText(preset["name"])
        self.ed_base.setText(preset["base_url"])
        if preset.get("model"):
            self.ed_manual.setText(preset["model"])
        self.cbo_preset.setCurrentIndex(0)

    def _on_add(self) -> None:
        self.list.clearSelection()
        self._clear_form()
        self.ed_base.setFocus()

    def _on_delete(self) -> None:
        if not self._current or self._current.id is None:
            QMessageBox.information(self, "提示", "先在左边选一条配置")
            return
        reply = QMessageBox.question(
            self, "删除配置",
            f"确定删除「{self._current.name or self._current.model}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(self._current.id)
        self._current = None
        self._reload()
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._clear_form()

    def _form_config(self) -> ApiConfig:
        cfg = self._current or ApiConfig()
        cfg.base_url = self.ed_base.text().strip()
        cfg.api_key = self.ed_key.text().strip()
        cfg.models = self._checked_models()
        cfg.model = cfg.models[0] if cfg.models else ""
        cfg.name = self.ed_name.text().strip()
        cfg.temperature = round(self.spin_temp.value(), 2)
        cfg.timeout = int(self.spin_timeout.value())
        cfg.is_default = self.chk_default.isChecked()
        return cfg

    def _on_test(self) -> None:
        cfg = self._form_config()
        if not cfg.configured:
            self.lbl_test.setText("⚠ Base URL / Key / 至少勾一个模型")
            self.lbl_test.setStyleSheet("color:#b26a00;")
            return
        self.btn_test.setEnabled(False)
        self.lbl_test.setText("测试中…")
        self.lbl_test.setStyleSheet("color:#666;")
        self.repaint()
        ok, msg = DeepSeekAnalyzer(cfg).test_connection()
        self.btn_test.setEnabled(True)
        self.lbl_test.setText(("✅ " if ok else "❌ ") + msg)
        self.lbl_test.setStyleSheet("color:#1a7f37;" if ok else "color:#c0392b;")

    def _on_save(self) -> None:
        cfg = self._form_config()
        if not cfg.base_url:
            QMessageBox.warning(self, "信息不完整", "Base URL 必须填写。")
            return
        if not cfg.api_key:
            QMessageBox.warning(self, "缺少 Key",
                                "API Key 为空。\n本地 Ollama 之类的服务可以随便填一个（如 ollama）。")
            return
        if not cfg.models:
            QMessageBox.warning(self, "没有模型",
                                "至少勾选一个模型。\n点「获取可用模型」，或在下面手动添加。")
            return
        if not cfg.name:
            cfg.name = cfg.model

        new_id = self.store.save(cfg)
        self._reload(select_id=new_id)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        QMessageBox.information(
            self, "已保存",
            f"「{cfg.name}」已保存，启用了 {len(cfg.models)} 个模型：\n"
            + "、".join(cfg.models))
