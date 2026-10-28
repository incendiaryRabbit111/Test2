"""程序入口。"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import main_window as mw_mod
from app.theme import apply as apply_theme


def _app_icon() -> QIcon:
    """优先取打包内资源，其次取 exe/项目目录下的 assets。"""
    from app.paths import app_root, bundle_dir
    for base in (bundle_dir(), app_root()):
        p = base / "assets" / "app.ico"
        if p.exists():
            return QIcon(str(p))
    return QIcon()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("特征微生物分析工具")
    app.setWindowIcon(_app_icon())
    apply_theme(app)
    if "--guide" in sys.argv:
        mw_mod.FORCE_GUIDE = True
    win = mw_mod.MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
