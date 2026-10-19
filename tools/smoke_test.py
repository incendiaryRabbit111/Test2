"""冒烟测试：跑通整条链路，并离屏验证界面。

用法（项目根目录下）：
    .venv\\Scripts\\python.exe tools\\smoke_test.py
用临时数据库，不会污染 data/history.db
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import analyzer as analyzer_mod
from app import exporter as exporter_mod
from app import history as history_mod
from app import metrics as metrics_mod
from app import parser as parser_mod
from app import trend as trend_mod
from app.sample import SAMPLE_TEXT

failures = 0
TMP_DB = Path(tempfile.mkdtemp(prefix="microbe_test_")) / "history.db"
history_mod.DB_PATH = TMP_DB

TARGET_SET = {"内管虫", "匣壳虫", "扭曲管叶虫", "摩门虫", "斜管虫", "楯纤虫",
              "盖纤虫", "累枝虫", "线虫", "表壳虫", "袋鞭虫", "轮虫", "钟虫"}

FORMAT_CASES = {
    "原始样例": (SAMPLE_TEXT, 13),
    "极简（只有浓度+单位）": (
        "内管虫: 0.346, 匣壳虫: 0.115, 扭曲管叶虫: 0.403, 摩门虫: 0.058, 斜管虫: 0.058, "
        "楯纤虫: 0.058, 盖纤虫: 0.173, 累枝虫: 0.173, 线虫: 0.115, 表壳虫: 1.440, "
        "袋鞭虫: 0.288, 轮虫: 0.115, 钟虫: 0.173。浓度单位(10^6个/L)", 13),
    "全角标点": ("内管虫：0.346，匣壳虫：0.115，扭曲管叶虫：0.403，摩门虫：0.058，斜管虫：0.058，"
                 "楯纤虫：0.058，盖纤虫：0.173，累枝虫：0.173，线虫：0.115，表壳虫：1.440，"
                 "袋鞭虫：0.288，轮虫：0.115，钟虫：0.173", 13),
    "无冒号+空格分隔": ("内管虫 0.346\n匣壳虫 0.115\n扭曲管叶虫 0.403\n摩门虫 0.058\n斜管虫 0.058\n"
                        "楯纤虫 0.058\n盖纤虫 0.173\n累枝虫 0.173\n线虫 0.115\n表壳虫 1.440\n"
                        "袋鞭虫 0.288\n轮虫 0.115\n钟虫 0.173", 13),
    "Excel 复制的制表符表格": ("物种\t浓度\n内管虫\t0.346\n匣壳虫\t0.115\n扭曲管叶虫\t0.403\n"
                              "摩门虫\t0.058\n斜管虫\t0.058\n楯纤虫\t0.058\n盖纤虫\t0.173\n"
                              "累枝虫\t0.173\n线虫\t0.115\n表壳虫\t1.440\n袋鞭虫\t0.288\n"
                              "轮虫\t0.115\n钟虫\t0.173", 13),
    "带序号前缀": ("1.内管虫 0.346\n2.匣壳虫 0.115\n3.扭曲管叶虫 0.403\n4.摩门虫 0.058\n"
                   "5.斜管虫 0.058\n6.楯纤虫 0.058\n7.盖纤虫 0.173\n8.累枝虫 0.173\n"
                   "9.线虫 0.115\n10.表壳虫 1.440\n11.袋鞭虫 0.288\n12.轮虫 0.115\n13.钟虫 0.173", 13),
    "等号/分号/竖线混排": ("内管虫=0.346；匣壳虫=0.115|扭曲管叶虫=0.403；摩门虫=0.058；表壳虫=1.440", 5),
}

BATCH_TEXT = """2026-10-09 09:00
内管虫: 0.301, 表壳虫: 1.052, 轮虫: 0.022
---
2026-10-09 10:00
内管虫: 0.312, 表壳虫: 1.088, 轮虫: 0.024

2026-10-09 11:00
内管虫: 0.325, 表壳虫: 1.120, 轮虫: 0.026"""


def check(label: str, cond: bool, detail: str = "") -> None:
    global failures
    print(f"{'[PASS]' if cond else '[FAIL]'} {label}" + (f"  -> {detail}" if detail else ""))
    if not cond:
        failures += 1


# ---------------------------------------------------------------- 1
def test_pipeline():
    print("\n=== 1. 解析 / 计算 ===")
    p = parser_mod.parse(SAMPLE_TEXT)
    check("解析出 13 个物种", len(p.species) == 13, str(len(p.species)))
    check("识别浓度单位", p.unit == "10^6 个/L", p.unit)
    check("解析出「较上次变化」13 条", len(p.change) == 13, str(len(p.change)))

    m = metrics_mod.compute(p.species)
    check("物种数 = 13", m.species_count == 13, str(m.species_count))
    check("浓度合计 = 3.515", abs(m.total - 3.515) < 1e-9, f"{m.total}")
    check("H' = 2.031", m.shannon_h == 2.031, str(m.shannon_h))
    check("优势种群 10 个", len(m.dominant) == 10, str(len(m.dominant)))
    check("绝对优势种群与仪器一致", set(m.absolute) == {"扭曲管叶虫", "表壳虫"}, str(m.absolute))
    return p, m


# ---------------------------------------------------------------- 2
def test_format_tolerance():
    print("\n=== 2. 输入格式容忍度 ===")
    for title, (text, expect) in FORMAT_CASES.items():
        r = parser_mod.parse(text)
        ok = len(r.species) == expect
        if expect == 13:
            ok = ok and set(r.species) == TARGET_SET
        check(f"{title}（{len(r.species)} 种）", ok, f"策略={r.strategy}")
    bad = parser_mod.parse("内管虫: 0.346, 表壳虫: 1.44\n物种种类数: 13")
    check("物种数与文本不符时告警", any("物种种类数" in w for w in bad.warnings), str(bad.warnings))


# ---------------------------------------------------------------- 3
def test_batch():
    print("\n=== 3. 批量导入 ===")
    from app import batch as batch_mod
    check("按 --- 和空行切段", len(batch_mod.split_segments(BATCH_TEXT)) == 3,
          str(len(batch_mod.split_segments(BATCH_TEXT))))

    res = batch_mod.parse_batch(BATCH_TEXT)
    check("解析出 3 段", len(res.items) == 3, str(len(res.items)))
    check("时间从段内提取", [it.sample_time for it in res.items] ==
          ["2026-10-09 09:00:00", "2026-10-09 10:00:00", "2026-10-09 11:00:00"],
          str([it.sample_time for it in res.items]))
    check("每段物种正确", all(len(it.parsed.species) == 3 for it in res.items))
    check("浓度读对（表壳虫）", res.items[0].parsed.species["表壳虫"] == 1.052)

    no_time = "内管虫: 0.30, 表壳虫: 1.05\n---\n内管虫: 0.31, 表壳虫: 1.09\n---\n内管虫: 0.32, 表壳虫: 1.12"
    res2 = batch_mod.parse_batch(no_time, start_time="2026-10-09 09:00", interval_min=60)
    check("起始时间+间隔推算", [it.sample_time for it in res2.items] ==
          ["2026-10-09 09:00:00", "2026-10-09 10:00:00", "2026-10-09 11:00:00"],
          str([it.sample_time for it in res2.items]))

    res3 = batch_mod.parse_batch(SAMPLE_TEXT)
    check("单段文本也能导入", len(res3.ok_items) == 1, str(len(res3.ok_items)))


# ---------------------------------------------------------------- 4
def test_trend():
    print("\n=== 4. 变化计算 + 趋势规则 ===")
    cur = {"楯纤虫": 0.058, "轮虫": 0.115, "钟虫": 0.173, "表壳虫": 1.44, "新物种": 0.05}
    prev = {"楯纤虫": 0.500, "轮虫": 0.020, "钟虫": 0.170, "表壳虫": 1.44, "老物种": 0.09}

    ch = trend_mod.compute_changes(cur, prev)
    check("楯纤虫 -88.4%", round(ch["楯纤虫"].pct, 1) == -88.4, f"{ch['楯纤虫'].pct:.1f}%")
    check("轮虫 +475%", round(ch["轮虫"].pct, 1) == 475.0, f"{ch['轮虫'].pct:.1f}%")
    check("钟虫未达阈值", abs(ch["钟虫"].pct - 1.76) < 0.1, f"{ch['钟虫'].pct:.2f}%")
    check("本次消失的物种也有记录", "老物种" in ch and ch["老物种"].pct == -100.0)
    check("新检出物种标注", ch["新物种"].text == "上次未检出", ch["新物种"].text)

    hits = trend_mod.detect_trends(ch)
    names = {h.rule for h in hits}
    check("命中「楯纤虫急速变少」", "楯纤虫急速变少" in names, str(names))
    check("命中「轮虫变多」", "轮虫变多" in names)
    check("未误报「钟虫急速变少」", "钟虫急速变少" not in names)

    ch2 = trend_mod.compute_changes(cur, None, {"楯纤虫": -80.0, "轮虫": 350.0})
    check("方案A 用文本自带变化", ch2["楯纤虫"].pct == -80.0 and ch2["楯纤虫"].source == "文本自带")
    check("方案A 也能命中趋势规则", len(trend_mod.detect_trends(ch2)) == 2)


# ---------------------------------------------------------------- 5
def test_history():
    print("\n=== 5. 会话记录库 ===")
    h = history_mod.History()
    check("初始为空", h.count() == 0, str(h.count()))

    rec = history_mod.Record(species={"内管虫": 0.3, "表壳虫": 1.1}, unit="10^6 个/L",
                             sample_time="2026-10-09 09:00:00", imported_at="2026-10-09 09:00:01",
                             total=1.4, species_count=2, shannon_h=0.6, raw_text="内管虫: 0.3")
    rid = h.save(rec)
    got = h.get(rid)
    check("写读一致", got is not None and got.species == rec.species, str(got.species if got else None))
    check("原始文本已存", got.raw_text == "内管虫: 0.3", got.raw_text)
    check("last() 返回最新一条", h.last().id == rid)

    # 回填分析结果
    got.report = "情况：测试"
    got.evaluations = [{"species": "内管虫", "comment": "占比偏高", "advice": "缩短污泥龄"}]
    got.changes = [{"species": "内管虫", "pct": 12.5, "source": "历史库", "text": "+12.5%"}]
    got.trends = [{"rule": "轮虫变多", "detail": "d", "meaning": "m"}]
    got.analysis_source = "DeepSeek"
    h.update_analysis(rid, got)

    back = h.get(rid)
    check("报告已回填", back.report == "情况：测试", back.report)
    check("评价已回填", back.evaluations and back.evaluations[0]["comment"] == "占比偏高",
          str(back.evaluations))
    check("变化快照已回填", back.changes and back.changes[0]["text"] == "+12.5%")
    check("趋势已回填", back.trends and back.trends[0]["rule"] == "轮虫变多")
    check("分析来源已回填", back.analysis_source == "DeepSeek")

    check("副标题显示已分析", "未分析" not in back.subtitle, back.subtitle)
    check("列表倒序", [r.id for r in h.all_desc()] == [rid])
    check("recent 升序", [r.id for r in h.recent()] == [rid])

    rid2 = h.save(history_mod.Record(species={"钟虫": 0.2}, sample_time="2026-10-09 10:00:00"))
    check("两条记录", h.count() == 2)
    check("删除单条", h.delete(rid2) == 1 and h.count() == 1)
    check("清空", h.clear() == 1 and h.count() == 0)

    # 给界面测试预置一条（带报告和评价，模拟"分析过的历史记录"）
    rec.report = "情况：本次为预置测试记录。"
    rec.evaluations = [{"species": "内管虫", "comment": "占比偏高", "advice": "缩短污泥龄"}]
    rec.changes = [{"species": "内管虫", "pct": 12.5, "source": "历史库", "text": "+12.5%"}]
    rec.trends = [{"rule": "轮虫变多", "detail": "轮虫增加 400%", "meaning": "污泥解体加剧"}]
    rec.analysis_source = "DeepSeek"
    h.save(rec)


# ---------------------------------------------------------------- 6
def test_analyzer(p, m):
    print("\n=== 6. AI 两阶段（逐物种评价 -> 综合报告）===")
    analyzer = analyzer_mod.DeepSeekAnalyzer()
    print(f"     分析模式：{analyzer.mode_text}（temperature={analyzer_mod.TEMPERATURE}）")

    changes = trend_mod.compute_changes(p.species, None, p.change)
    trends = trend_mod.detect_trends(changes)
    payload = analyzer_mod.build_payload(p, m, changes, trends, "")

    t0 = time.time()
    result = analyzer.analyze(payload)
    cost = time.time() - t0
    print(f"     耗时 {cost:.1f}s｜来源 {result.source}")
    if result.error:
        print(f"     ⚠ 已降级：{result.error[:150]}")

    got = {e.species for e in result.evaluations}
    check("每个物种都有评价", got == TARGET_SET, f"缺失 {TARGET_SET - got}")
    lengths = [len(e.comment) for e in result.evaluations]
    check("综合评价简短(20~90字)", all(20 <= n <= 90 for n in lengths),
          f"最长 {max(lengths)} / 平均 {sum(lengths)//len(lengths)} 字")

    lines = [x for x in result.report.splitlines() if x.strip()]
    check("报告为分段式", len(lines) >= 2, f"{len(lines)} 行")
    check("首行是「情况：」", lines[0].startswith("情况：") if lines else False)
    check("末几行是「建议：」", all(x.startswith("建议：") for x in lines[-3:]) if len(lines) >= 3 else False)
    return result


# ---------------------------------------------------------------- 7
def test_export(p, m, result):
    print("\n=== 7. 导出 ===")
    changes = trend_mod.compute_changes(p.species, None, p.change)
    change_text = {c.species: c.text for c in changes.values()}
    out = ROOT / "output" / "smoke_test.xlsx"
    exporter_mod.export(out, sample_time="2026-10-10 09:00", parsed=p, metrics=m,
                        analysis=result, changes=change_text,
                        trends=trend_mod.detect_trends(changes), previous_time="")
    check("导出 xlsx", out.exists() and out.stat().st_size > 5000,
          f"{out.stat().st_size if out.exists() else 0} 字节")
    from openpyxl import load_workbook
    wb = load_workbook(out)
    check("三个 sheet", wb.sheetnames == ["物种评价", "检测概要", "AI分析报告"], str(wb.sheetnames))
    ws = wb["物种评价"]
    want = ["序号", "物种", "浓度", "相对丰度(%)", "等级", "较上次变化", "综合评价", "指导意见"]
    got = [ws.cell(row=1, column=i).value for i in range(1, ws.max_column + 1)]
    check("主表表头 = xlsx纵向格式 + 浓度", got == want, str(got))
    check("一个物种一行", ws.max_row == m.species_count + 1, str(ws.max_row))
    check("首行是表壳虫且带浓度",
          ws.cell(row=2, column=2).value == "表壳虫" and ws.cell(row=2, column=3).value == 1.44,
          f"{ws.cell(row=2, column=2).value} / {ws.cell(row=2, column=3).value}")
    check("检测概要是一行", wb["检测概要"].max_row == 2, str(wb["检测概要"].max_row))


# ---------------------------------------------------------------- 8
def test_gui():
    print("\n=== 8. 界面（C 布局：左会话列表 / 右详情）===")
    from PySide6.QtWidgets import QApplication

    from app.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    check("窗口创建成功", win.ui.tblEvaluations is not None)
    check("有会话列表", hasattr(win.ui, "sessionList"))
    check("有「新建分析」按钮", hasattr(win.ui, "btnNew"))
    check("旧的「设备编号」已移除", not hasattr(win.ui, "deviceInput"))
    check("旧的「清除历史记录」已移除", not hasattr(win.ui, "btnClearHistory"))
    check("预置记录已进列表", win.ui.sessionList.count() == 1, str(win.ui.sessionList.count()))
    check("选中后显示详情", win.ui.rightStack.currentWidget() is win.ui.resultPage)
    check("详情还原了评价", "占比偏高" in [win.ui.tblEvaluations.item(i, 4).text()
                                          for i in range(win.ui.tblEvaluations.rowCount())],
          str([win.ui.tblEvaluations.item(i, 4).text()
               for i in range(win.ui.tblEvaluations.rowCount())]))

    # 新建 -> 输入页
    win.ui.btnNew.click()
    check("「新建分析」切到输入页", win.ui.rightStack.currentWidget() is win.ui.inputPage)

    win.ui.chkConfirm.setChecked(False)
    win.ui.inputText.setPlainText(SAMPLE_TEXT)
    win.on_analyze()
    for _ in range(800):
        app.processEvents()
        if win._pending is None:
            break
        time.sleep(0.05)
    app.processEvents()

    check("分析后新增一条会话", win.ui.sessionList.count() == 2, str(win.ui.sessionList.count()))
    check("自动切回详情页", win.ui.rightStack.currentWidget() is win.ui.resultPage)
    check("指标表 13 行", win.ui.tblMetrics.rowCount() == 13, str(win.ui.tblMetrics.rowCount()))
    check("评价表 13 行 x 6 列",
          win.ui.tblEvaluations.rowCount() == 13 and win.ui.tblEvaluations.columnCount() == 6)
    check("评价表有综合评价", len(win.ui.tblEvaluations.item(0, 4).text()) > 10,
          win.ui.tblEvaluations.item(0, 4).text()[:30])
    check("报告已分段显示", "\n\n" in win.ui.txtReport.toPlainText())
    check("报告字号已放大", win.ui.txtReport.font().pointSize() == 11)
    check("导出按钮已启用", win.ui.btnExport.isEnabled())
    check("趋势图 tab 存在", hasattr(win.ui, "trendHolder"))
    check("趋势图已加载物种按钮", len(win.trend_view._buttons) >= 13,
          f"{len(win.trend_view._buttons)} 个按钮")

    # 记录已落库（含评价）
    latest = win.history.last()
    check("最新记录已入库", latest is not None and latest.species_count == 13,
          str(latest.species_count if latest else None))
    check("评价已持久化", bool(latest.evaluations), f"{len(latest.evaluations or [])} 条")
    check("报告已持久化", len(latest.report or "") > 50)

    # 删除单条
    removed_id = latest.id
    win.history.delete(removed_id)
    win._refresh_trend()
    win._reload_sessions(select_id=None)
    check("删单条后列表变 1 条", win.ui.sessionList.count() == 1, str(win.ui.sessionList.count()))
    check("删单条后历史库变 1 条", win.history.count() == 1, str(win.history.count()))

    win.close()


if __name__ == "__main__":
    p, m = test_pipeline()
    test_format_tolerance()
    test_batch()
    test_trend()
    test_history()
    result = test_analyzer(p, m)
    test_export(p, m, result)
    test_gui()
    print("\n" + "=" * 50)
    print("全部通过 ✅" if failures == 0 else f"失败 {failures} 项 ❌")
    print(f"（临时库：{TMP_DB}）")
    sys.exit(1 if failures else 0)
