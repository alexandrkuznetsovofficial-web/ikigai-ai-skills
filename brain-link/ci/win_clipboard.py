#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""win_clipboard.py — лаборатория (только GitHub Actions, Windows): настоящий буфер обмена для put-token claude.

На Windows brain_link не может поймать строку `claude setup-token` через pty — человек выделяет её мышью и
жмёт Ctrl+C, скрипт берёт её из буфера (default_clipboard_get → Get-Clipboard) и затирает буфер пробелом
(default_clipboard_put → clip). Без терминала шаг кладёт в буфер КОМАНДУ запуска. Здесь — те же функции
продукта на настоящем буфере Windows. Токен — сгенерированный, в вывод не печатается (только длина и sha256).
"""
import hashlib
import os
import secrets
import string
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import brain_link as bk  # noqa: E402

PASS = FAIL = 0


def ok(t):
    global PASS
    PASS += 1
    print("PASS " + t, flush=True)


def bad(t):
    global FAIL
    FAIL += 1
    print("FAIL " + t, flush=True)


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def human_copy(text):
    """Как Ctrl+C человека: Set-Clipboard из PowerShell (не через функцию продукта)."""
    ps = bk.find_powershell()
    env = dict(os.environ, LAB_CLIP=text)
    r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", "Set-Clipboard -Value $env:LAB_CLIP"],
                       env=env, capture_output=True, timeout=30)
    return r.returncode


def main():
    if bk.os_name() != "windows":
        print("SKIP: не Windows")
        return 0
    alpha = string.ascii_letters + string.digits + "-_"
    tok = "sk-ant-oat01-" + "".join(secrets.choice(alpha) for _ in range(95))

    # 1. команда в буфер (шаг без терминала) — функция продукта, обратно читаем функцией продукта
    cmd = bk.human_command("put-token claude")
    put_ok = bk.CLIPBOARD_PUT(cmd)
    got = (bk.CLIPBOARD_GET() or "").rstrip("\r\n")
    (ok if put_ok else bad)("CLIPBOARD_PUT(команда) rc=0 (clip)")
    if got == cmd:
        ok("команда из буфера = положенной (%d знаков, с $env:USERPROFILE)" % len(cmd))
    else:
        bad("команда в буфере искажена: %r → %r" % (cmd, got))

    # 1b. кириллица в команде (путь профиля с кириллицей) — clip получает UTF-16LE
    cyr = 'py -3 "C:\\Users\\Иван Петров\\.claude\\skills\\brain-link\\scripts\\brain_link.py" put-token claude'
    bk.CLIPBOARD_PUT(cyr)
    got = (bk.CLIPBOARD_GET() or "").rstrip("\r\n")
    if got == cyr:
        ok("кириллица в буфере не искажена (clip UTF-16LE → Get-Clipboard)")
    else:
        bad("кириллица в буфере искажена: sha %s → %s, len %d → %d" % (sha(cyr), sha(got), len(cyr), len(got)))

    # 2. человек скопировал строку токена (как в окне setup-token: с пробелами и переводом строки)
    for label, text in (("одной строкой", "  " + tok + "\r\n"),
                        ("с переносом посередине", tok[:40] + "\r\n" + tok[40:] + "\r\n")):
        rc = human_copy(text)
        if rc != 0:
            bad("Set-Clipboard не сработал (rc=%s) — буфер раннера недоступен" % rc)
            continue
        clip = (bk.CLIPBOARD_GET() or "").strip()
        m = bk.TOKEN_ANY_RE.search(clip.replace("\r", "").replace("\n", ""))
        found = m.group(0) if m and bk.CLAUDE_TOKEN_RE.match(m.group(0)) else ""
        if found == tok:
            ok("токен из буфера %s взят целиком (len %d, sha %s)" % (label, len(found), sha(found)))
        else:
            bad("токен из буфера %s: len %d sha %s, ждали len %d sha %s" % (label, len(found), sha(found or "-"),
                                                                         len(tok), sha(tok)))

    # 3. затирание буфера после чтения (CLIPBOARD_PUT(" ")) — токена в буфере не остаётся
    bk.CLIPBOARD_PUT(" ")
    left = bk.CLIPBOARD_GET() or ""
    if tok not in left.replace("\r", "").replace("\n", "") and tok[:40] not in left:
        ok("после чтения токена буфер затёрт")
    else:
        bad("токен остался в буфере")

    print("win-clipboard: %d PASS, %d FAIL" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
