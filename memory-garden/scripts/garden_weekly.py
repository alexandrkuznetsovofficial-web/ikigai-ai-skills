#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Пятничный прогон сада одной командой: разметить новые заметки стадиями и пересобрать граф.

Его ставит расписание (launchd на Mac, Планировщик заданий на Windows). Вручную:
  python3 garden_weekly.py --root <рабочая папка>/memory [--no-personal] [--out ПАПКА]

Пишет журнал в ~/.claude/graph/memory_garden.log (Windows: %USERPROFILE%\\.claude\\graph\\).
Заметкам без шапки шапку НЕ дописывает — это делается один раз руками, после согласия.
"""
import datetime
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _utf8_stdout():
    """Windows / Git Bash: вывод в канал идёт в cp1251/cp1252 и падает на кириллице — переключаем на UTF-8."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    _utf8_stdout()
    extra = [x for x in sys.argv[1:]]
    if any(x in ("-h", "--help") for x in extra):
        print("garden_weekly.py [--root ПАПКА_ПАМЯТИ] — разметить стадии (--apply) и пересобрать граф. "
              "Запускается по расписанию в пятницу; вручную — только если понимаешь, что пишет в заметки.")
        return 0
    root_args = []
    if "--root" in extra:
        i = extra.index("--root")
        root_args = extra[i:i + 2]
    out_args = []
    if "--out" in extra:
        i = extra.index("--out")
        out_args = extra[i:i + 2]
    graph_args = root_args + out_args + (["--no-personal"] if "--no-personal" in extra else [])
    log_dir = Path(out_args[1]).expanduser() if len(out_args) == 2 else Path.home() / ".claude" / "graph"
    log_dir.mkdir(parents=True, exist_ok=True)
    out = ["", "=== %s ===" % datetime.datetime.now().isoformat(timespec="minutes")]
    code = 0
    for script, args in (("garden_stage.py", ["--apply"] + root_args),
                         ("build_memory_graph.py", graph_args)):
        r = subprocess.run([sys.executable, str(HERE / script)] + args,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        out.append(r.stdout.decode("utf-8", errors="replace").rstrip())
        code = code or r.returncode
    text = "\n".join(out)
    print(text)
    with open(str(log_dir / "memory_garden.log"), "a", encoding="utf-8") as f:
        f.write(text + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
