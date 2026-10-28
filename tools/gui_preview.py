"""把界面离屏渲染成 PNG，方便快速预览样子。

用法（项目根目录下）：
    .venv\\Scripts\\python.exe tools\\gui_preview.py
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app import history as history_mod
from app import main_window as mw_mod
from app.theme import apply as apply_theme

OUT = ROOT / "output" / "preview.png"

PREVIEW_DB = ROOT / "output" / "preview_history.db"
history_mod.DB_PATH = PREVIEW_DB

# API 配置也用独立库，顺便塞一条「一个网关挂两个模型」的配置
from app import api_config as api_config_mod

api_config_mod.DB_PATH = ROOT / "output" / "preview_api.db"

HOURS = 24
BASE_TIME = datetime(2026, 10, 9, 9, 0, 0)

SAMPLE_SPECIES = {
    "内管虫": 0.346, "匣壳虫": 0.115, "扭曲管叶虫": 0.403, "摩门虫": 0.058, "斜管虫": 0.058,
    "楯纤虫": 0.058, "盖纤虫": 0.173, "累枝虫": 0.173, "线虫": 0.115, "表壳虫": 1.440,
    "袋鞭虫": 0.288, "轮虫": 0.115, "钟虫": 0.173,
}
START_SPECIES = {
    "内管虫": 0.301, "匣壳虫": 0.121, "扭曲管叶虫": 0.332, "摩门虫": 0.064, "斜管虫": 0.051,
    "楯纤虫": 0.552, "盖纤虫": 0.205, "累枝虫": 0.198, "线虫": 0.101, "表壳虫": 1.052,
    "袋鞭虫": 0.325, "轮虫": 0.022, "钟虫": 0.181,
}
WAYPOINTS = {
    "楯纤虫": [(0, 0.552), (18, 0.520), (20, 0.470), (22, 0.320), (23, 0.058)],
    "轮虫": [(0, 0.022), (19, 0.024), (21, 0.028), (22, 0.028), (23, 0.115)],
}


def _interp(points, hour):
    if hour <= points[0][0]:
        return points[0][1]
    if hour >= points[-1][0]:
        return points[-1][1]
    for (h0, v0), (h1, v1) in zip(points, points[1:]):
        if h0 <= hour <= h1:
            f = 0 if h1 == h0 else (hour - h0) / (h1 - h0)
            return v0 + (v1 - v0) * f
    return points[-1][1]


def species_at(hour: int) -> dict:
    out = {}
    for name, end in SAMPLE_SPECIES.items():
        if name in WAYPOINTS:
            value = _interp(WAYPOINTS[name], hour)
        else:
            value = START_SPECIES[name] + (end - START_SPECIES[name]) * (hour / (HOURS - 1))
        out[name] = round(value, 3)
    return out


def seed_api() -> None:
    store = api_config_mod.ApiConfigStore()
    store.clear_all() if hasattr(store, "clear_all") else None
    with store._conn() as conn:
        conn.execute("DELETE FROM api_configs")
    env = api_config_mod.ApiConfig.from_env()
    if env is None:
        return
    cfg = api_config_mod.ApiConfig(
        name="DeepSeek", base_url=env.base_url,
        models=["deepseek-flash", "deepseek-v4-pro"],
        api_key=env.api_key, is_default=True,
    )
    store.save(cfg)
    print(f"seeded api config: {cfg.name} / {cfg.models}")


def seed_history() -> None:
    h = history_mod.History()
    h.clear()
    # 只预置到第 23 条，第 24 条留给「分析」写进去
    for hour in range(HOURS - 1):
        t = BASE_TIME + timedelta(hours=hour)
        sp = species_at(hour)
        stamp = t.strftime("%Y-%m-%d %H:%M:00")
        h.save(history_mod.Record(
            species=sp, unit="10^6 个/L", sample_time=stamp, imported_at=stamp,
            total=sum(sp.values()), species_count=len(sp),
        ))
    print(f"seeded {HOURS - 1} hourly records -> {PREVIEW_DB}")
    prev, cur = species_at(HOURS - 2), species_at(HOURS - 1)
    for name in ("楯纤虫", "轮虫"):
        print(f"  {name}: {prev[name]} -> {cur[name]}  ({(cur[name] / prev[name] - 1) * 100:+.1f}%)")


def pump(app, n=15, delay=0.03):
    for _ in range(n):
        app.processEvents()
        time.sleep(delay)


def shot(win, name: str) -> None:
    path = OUT.with_name(f"preview_{name}.png")
    win.grab().save(str(path))
    print("saved", path)


def main() -> int:
    seed_api()
    seed_history()
    mw_mod.SUPPRESS_GUIDE = True      # 自动引导关掉，后面单独渲染
    app = QApplication(sys.argv)
    apply_theme(app)
    win = mw_mod.MainWindow()
    win.resize(1280, 800)
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.show()
    win.ui.chkConfirm.setChecked(False)
    pump(app)

    # 走一遍完整流程：新建 -> 粘贴 -> 分析
    win.ui.btnNew.click()
    pump(app, 8)
    # 先截一张"空输入框 + 占位提示"的图
    shot(win, "00_输入页")

    from app.sample import SAMPLE_TEXT
    win.ui.inputText.setPlainText(SAMPLE_TEXT)
    # 填上采样时间，让新记录接在 23 条小时数据后面（否则会落到"现在"，图上出现假平线）
    win.ui.timeInput.setText("2026-10-10 08:00")

    win.on_analyze()
    for _ in range(1500):
        app.processEvents()
        if win._pending is None:
            break
        time.sleep(0.05)
    pump(app, 30)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    for idx, name in enumerate(["01_指标", "02_物种评价", "03_报告", "05_趋势"]):
        win.ui.tabResults.setCurrentIndex(idx)
        pump(app, 15)
        shot(win, name)

    # 批量导入弹窗
    from app.batch_dialog import BatchDialog
    bd = BatchDialog()
    bd.resize(900, 660)
    bd.text.setPlainText(
        "2026-10-09 09:00\n内管虫: 0.301, 表壳虫: 1.052, 轮虫: 0.022\n"
        "---\n2026-10-09 10:00\n内管虫: 0.312, 表壳虫: 1.088, 轮虫: 0.024\n"
        "---\n2026-10-09 11:00\n内管虫: 0.325, 表壳虫: 1.120, 轮虫: 0.026\n"
        "---\n2026-10-09 12:00\n内管虫: 0.318, 表壳虫: 1.166, 轮虫: 0.028\n"
        "---\n这一段的格式是坏的没有物种数据\n"
        "---\n2026-10-09 14:00\n内管虫: 0.340, 表壳虫: 1.244, 轮虫: 0.035"
    )
    bd._on_preview()
    bd.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    bd.show()
    pump(app, 15)
    bd.grab().save(str(OUT.with_name("preview_06_批量导入.png")))
    print("saved", OUT.with_name("preview_06_批量导入.png"))
    bd.hide()
    bd.deleteLater()
    pump(app, 8)

    # 核对弹窗
    from app import parser as parser_mod
    from app.confirm_dialog import ConfirmDialog
    from app.sample import SAMPLE_TEXT
    dlg = ConfirmDialog(parser_mod.parse(SAMPLE_TEXT))
    dlg.resize(560, 620)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dlg.show()
    pump(app, 15)
    dlg.grab().save(str(OUT.with_name("preview_07_核对弹窗.png")))
    print("saved", OUT.with_name("preview_07_核对弹窗.png"))
    dlg.hide()
    dlg.deleteLater()
    pump(app, 8)
    # API 设置对话框
    from app.api_config import ApiConfigStore
    from app.api_dialog import ApiSettingsDialog
    ad = ApiSettingsDialog(ApiConfigStore())
    ad.resize(820, 560)
    ad.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    ad.show()
    pump(app, 20)
    ad.grab().save(str(OUT.with_name("preview_08_API设置.png")))
    print("saved", OUT.with_name("preview_08_API设置.png"))
    ad.hide()
    ad.deleteLater()
    pump(app, 8)

    # 新手引导：第 2 步（指向 API 设置）
    win.start_onboarding()
    pump(app, 20)
    if win._guide is not None:
        win._guide._goto(1)
        pump(app, 12)
        win.grab().save(str(OUT.with_name("preview_09_新手引导.png")))
        print("saved", OUT.with_name("preview_09_新手引导.png"))
        win._guide._finish()
        pump(app, 8)

    return 0


if __name__ == "__main__":
    sys.exit(main())
