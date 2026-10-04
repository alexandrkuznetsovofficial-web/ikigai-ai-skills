#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""drive_link.py — запуск brain_link.py в лаборатории с подменой внедряемых зависимостей (не для участников).

  drive_link.py [--getpass-file F] [--sync-shim] [--lockdown-bad-key KEY] -- <шаг brain_link> [флаги]

  --getpass-file F       GETPASS читает «скрытый ввод» из файла F (put-token без терминала)
  --sync-shim            расписание (schedule) запускает ci/sync_shim.py вместо scripts/brain_sync.py:
                         та же brain_sync, но с транспортом local:<папка> из ~/.config/brain/ci_transport.txt
                         (в brain_link.py нет флага транспорта для расписания — см. отчёт лаборатории)
  --lockdown-bad-key K   после включения lockdown (открыта root-сессия) проверка «brain по ключу» идёт
                         с чужим ключом K → проверка обязана провалиться → откат
Вывод и коды — как у brain_link.py (один JSON в stdout).
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import brain_link  # noqa: E402


def main():
    argv = sys.argv[1:]
    if "--" in argv:
        i = argv.index("--")
        opts, rest = argv[:i], argv[i + 1:]
    else:
        opts, rest = [], argv
    getpass_file = bad_key = None
    shim = False
    j = 0
    while j < len(opts):
        o = opts[j]
        if o == "--getpass-file":
            getpass_file = opts[j + 1]
            j += 2
        elif o == "--lockdown-bad-key":
            bad_key = opts[j + 1]
            j += 2
        elif o == "--sync-shim":
            shim = True
            j += 1
        else:
            sys.stderr.write("drive_link: неизвестный флаг %s\n" % o)
            sys.exit(4)

    if getpass_file:
        def fake_getpass(prompt=""):
            with open(getpass_file, encoding="utf-8") as f:
                return f.read().strip()
        brain_link.GETPASS = fake_getpass

    if shim:
        brain_link.SYNC_PY = HERE / "sync_shim.py"

    if bad_key:
        state = {"session": False}
        real_popen, real_runner = brain_link.POPEN, brain_link.RUNNER

        def popen(*a, **kw):
            state["session"] = True
            return real_popen(*a, **kw)

        def runner(cmd, **kw):
            cmd = [str(x) for x in cmd]
            if state["session"] and cmd and cmd[-1] == "true" and any(x.startswith("brain@") for x in cmd) \
                    and "-i" in cmd:
                cmd[cmd.index("-i") + 1] = bad_key
                sys.stderr.write("drive_link: проверка brain идёт с испорченным ключом (ожидается откат)\n")
            return real_runner(cmd, **kw)

        brain_link.POPEN = popen
        brain_link.RUNNER = runner

    brain_link.main(rest)


if __name__ == "__main__":
    main()
