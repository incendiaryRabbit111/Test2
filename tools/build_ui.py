"""把 ui/*.ui 批量编译成 app/generated/ui_*.py

用法:  python tools/build_ui.py
也可以用 VS Code 任务 "1) 编译所有 .ui -> .py"
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI_DIR = ROOT / "ui"
OUT_DIR = ROOT / "app" / "generated"
UIC = ROOT / ".venv" / "Scripts" / "pyside6-uic.exe"


def main() -> int:
    if not UI_DIR.exists():
        print(f"[skip] 没有 ui 目录: {UI_DIR}")
        return 0
    UI_DIR.mkdir(exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    uic = str(UIC) if UIC.exists() else "pyside6-uic"
    ui_files = sorted(UI_DIR.glob("*.ui"))
    if not ui_files:
        print("[skip] ui 目录下没有 .ui 文件")
        return 0

    failed = []
    for ui in ui_files:
        out = OUT_DIR / f"ui_{ui.stem}.py"
        cmd = [uic, str(ui), "-o", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            failed.append(ui.name)
            print(f"[FAIL] {ui.name}\n{r.stderr.strip()}")
        else:
            print(f"[ OK ] {ui.name} -> {out.relative_to(ROOT)}")
    if failed:
        print(f"\n{len(failed)} 个文件失败: {failed}")
        return 1
    print(f"\n完成，共 {len(ui_files)} 个 .ui")
    return 0


if __name__ == "__main__":
    sys.exit(main())
