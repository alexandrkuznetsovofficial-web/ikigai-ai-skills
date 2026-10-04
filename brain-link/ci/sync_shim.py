#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sync_shim.py — brain_sync.py для расписания лаборатории (launchd / Планировщик задач) с транспортом local.

Расписание вызывает «<python> sync_shim.py run [--root …]». Шим добавляет --transport из файла
<config_dir>/ci_transport.txt (строка local:<папка «сервера»>) и запускает настоящий brain_sync.main —
код синка тот же, что у ученика, отличается только транспорт (ssh → локальный подпроцесс сервера).
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import brainlib as bl  # noqa: E402
import brain_sync  # noqa: E402


def main():
    argv = sys.argv[1:]
    if "--transport" not in argv and os.environ.get("BRAIN_SYNC_TRANSPORT"):
        argv += ["--transport", os.environ["BRAIN_SYNC_TRANSPORT"]]
    if "--transport" not in argv:
        f = bl.config_dir() / "ci_transport.txt"
        try:
            t = f.read_text(encoding="utf-8-sig").strip()
        except OSError:
            bl.fail(bl.EXIT_CONFIG, "sync_shim: нет %s" % f)
        argv += ["--transport", t]
    sys.argv = [str(SCRIPTS / "brain_sync.py")] + argv
    bl.run_cli(brain_sync.main)


if __name__ == "__main__":
    main()
