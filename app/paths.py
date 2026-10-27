"""统一的路径解析：同时兼容「源码运行」和「PyInstaller 打包」。

打包成 exe 后：
  · sys.executable 所在目录 = 用户目录（数据库、导出文件、.env 都放这里）
  · __file__ 指向的却是 PyInstaller 的临时解包目录（程序退出就删）
所以不能再用 __file__ 推项目根，否则数据会写进临时目录，一关就没了。
"""
from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    """可写目录：源码运行时是项目根，打包后是 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_dir() -> Path:
    """只读资源目录：打包后是 _MEIPASS，否则同 app_root。"""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else app_root()


ROOT = app_root()
