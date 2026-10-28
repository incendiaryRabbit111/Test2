"""统一视觉主题（薄荷纸 Mint Paper）。

Qt 的 QSS 相当于 Web 的 CSS，但不支持 box-shadow / backdrop-filter，
所以"卡片感"靠「白底 + 1px 淡边框 + 圆角」实现，阴影只用极少量。
"""
from __future__ import annotations

# ---------------- 设计令牌 ----------------
BG = "#F3F6F4"          # 页面底色
CARD = "#FFFFFF"        # 卡片
BORDER = "#DEE6E1"      # 边框
LINE = "#EEF2F0"        # 分隔线
PRIMARY = "#2F7D5D"     # 主色
PRIMARY_HOVER = "#276A4F"
PRIMARY_PRESSED = "#1F5940"
PRIMARY_LIGHT = "#E6F2EC"
TEXT = "#1C262D"        # 主文字
TEXT2 = "#5C6C64"       # 次要文字
TEXT3 = "#8C9B93"       # 弱文字
AMBER = "#C87A2E"       # 绝对优势 / 警告
DANGER = "#C0392B"
SOFT_GREEN = "#8BBFA8"

FONT_FAMILY = "Microsoft YaHei UI"
FONT_PT = 10

# 表格行的极淡底色（替代原来看起来很扎眼的整行填充）
ROW_ABSOLUTE = "#FBF3E8"
ROW_DOMINANT = "#F1F8F4"
ROW_ALT = "#FAFCFB"


QSS = f"""
/* ---------------- 基础 ---------------- */
QWidget {{
    color: {TEXT};
    font-family: "{FONT_FAMILY}";
}}
QMainWindow, QWidget#centralwidget {{
    background: {BG};
}}
QToolTip {{
    background: #2B3A33;
    color: #FFFFFF;
    border: none;
    padding: 6px 8px;
    border-radius: 6px;
}}

/* ---------------- 卡片 ---------------- */
QWidget#topBar,
QWidget#leftPane,
QWidget#inputPage,
QWidget#resultPage {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QStackedWidget#rightStack {{
    background: transparent;
    border: none;
}}

/* ---------------- 按钮 ---------------- */
QPushButton {{
    background: {CARD};
    color: {TEXT2};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 6px 14px;
}}
QPushButton:hover {{
    background: {PRIMARY_LIGHT};
    color: {PRIMARY};
    border-color: {SOFT_GREEN};
}}
QPushButton:pressed {{
    background: #D8EBE2;
}}
QPushButton:disabled {{
    color: {TEXT3};
    background: #F6F8F7;
    border-color: {LINE};
}}

/* 主按钮 */
QPushButton#btnNew, QPushButton#btnAnalyze {{
    background: {PRIMARY};
    color: #FFFFFF;
    border: 1px solid {PRIMARY};
    font-weight: 600;
    padding: 8px 16px;
}}
QPushButton#btnNew:hover, QPushButton#btnAnalyze:hover {{
    background: {PRIMARY_HOVER};
    border-color: {PRIMARY_HOVER};
}}
QPushButton#btnNew:pressed, QPushButton#btnAnalyze:pressed {{
    background: {PRIMARY_PRESSED};
}}

/* 标题旁的小圆按钮（? 教程） */
QPushButton#btnGuide {{
    background: {CARD};
    color: {TEXT3};
    border: 1px solid {BORDER};
    border-radius: 11px;
    font-size: 12px;
    font-weight: 600;
    padding: 0px;
}}
QPushButton#btnGuide:hover {{
    background: {PRIMARY_LIGHT};
    color: {PRIMARY};
    border-color: {SOFT_GREEN};
}}

/* 次要主操作（导出）：绿色描边 */
QPushButton#btnExport {{
    background: {CARD};
    color: {PRIMARY};
    border: 1px solid {SOFT_GREEN};
    border-radius: 7px;
    padding: 7px 16px;
    font-weight: 600;
}}
QPushButton#btnExport:hover {{
    background: {PRIMARY_LIGHT};
    border-color: {PRIMARY};
}}
QPushButton#btnExport:disabled {{
    color: #A9B7B0;
    border-color: {BORDER};
    background: #F7F9F8;
}}

/* 顶栏「≡」更多设置 */
QPushButton#btnMore {{
    background: transparent;
    color: {TEXT3};
    border: 1px solid transparent;
    border-radius: 7px;
    font-size: 14px;
    padding: 0px;
}}
QPushButton#btnMore:hover {{
    background: #F4F8F6;
    border-color: {BORDER};
    color: {PRIMARY};
}}

/* 状态栏胶囊 */
QLabel#pill {{
    background: #EAF4EE;
    color: #4A7A66;
    border-radius: 9px;
    padding: 2px 9px;
    font-size: 10px;
}}

/* 次级强调（API 设置） */
QPushButton#btnApiSettings {{
    background: {PRIMARY_LIGHT};
    color: {PRIMARY};
    border: 1px solid {PRIMARY_LIGHT};
    font-weight: 600;
}}

/* ---------------- 输入类 ---------------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 8px;
    selection-background-color: {PRIMARY_LIGHT};
    selection-color: {TEXT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {PRIMARY};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT3};
    width: 0;
    height: 0;
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {PRIMARY_LIGHT};
    selection-color: {PRIMARY};
    outline: none;
}}

/* ---------------- 勾选框 ---------------- */
QCheckBox {{
    spacing: 6px;
    color: {TEXT2};
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid #C7D3CC;
    border-radius: 4px;
    background: {CARD};
}}
QCheckBox::indicator:checked {{
    background: {PRIMARY};
    border-color: {PRIMARY};
}}
QCheckBox::indicator:hover {{
    border-color: {PRIMARY};
}}

/* ---------------- 左栏列表 ---------------- */
QListWidget {{
    background: transparent;
    border: none;
    outline: none;
    padding: 2px;
}}
QListWidget::item {{
    background: transparent;
    border-radius: 8px;
    padding: 8px 10px;
    margin: 1px 2px;
    color: {TEXT2};
}}
QListWidget::item:hover {{
    background: #F4F8F6;
}}
QListWidget::item:selected {{
    background: {PRIMARY_LIGHT};
    color: {PRIMARY};
    font-weight: 600;
}}

/* ---------------- 页签 ---------------- */
QTabWidget::pane {{
    border: none;
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT3};
    padding: 7px 16px;
    margin-right: 4px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{
    color: {TEXT2};
}}
QTabBar::tab:selected {{
    color: {PRIMARY};
    font-weight: 600;
    border-bottom: 2px solid {PRIMARY};
}}

/* ---------------- 表格 ---------------- */
QTableWidget, QTableView {{
    background: {CARD};
    border: none;
    gridline-color: transparent;
    outline: none;
    selection-background-color: {PRIMARY_LIGHT};
    selection-color: {TEXT};
    alternate-background-color: {ROW_ALT};
}}
QHeaderView {{
    background: transparent;
}}
QHeaderView::section {{
    background: #F0F4F2;
    color: {TEXT2};
    border: none;
    border-bottom: 1px solid {LINE};
    padding: 8px 10px;
    font-weight: 600;
}}
QTableCornerButton::section {{
    background: #F0F4F2;
    border: none;
}}

/* ---------------- 滚动条 ---------------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #CBD8D1;
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: #AFC2B8;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #CBD8D1;
    border-radius: 4px;
    min-width: 28px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}

/* ---------------- 分栏 ---------------- */
QSplitter::handle {{
    background: transparent;
    width: 10px;
}}

/* ---------------- 菜单 / 对话框 ---------------- */
QMenu {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 22px 7px 14px;
    border-radius: 6px;
    color: {TEXT2};
}}
QMenu::item:selected {{
    background: {PRIMARY_LIGHT};
    color: {PRIMARY};
}}
QMenu::separator {{
    height: 1px;
    background: {LINE};
    margin: 4px 8px;
}}
QDialog {{
    background: {BG};
}}
QGroupBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 10px;
    font-weight: 600;
    color: {TEXT2};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    color: {TEXT2};
}}
"""


def apply(app) -> None:
    """给 QApplication 应用主题。"""
    from PySide6.QtGui import QFont

    app.setFont(QFont(FONT_FAMILY, FONT_PT))
    app.setStyleSheet(QSS)
