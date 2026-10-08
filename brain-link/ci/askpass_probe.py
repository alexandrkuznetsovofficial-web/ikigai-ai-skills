#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""askpass_probe.py — лаборатория: доходит ли пароль через SSH_ASKPASS (brain_link.run_askpass_ssh) до сервера.

  askpass_probe.py --user U --port P [--host 127.0.0.1] [--expect ok|rejected] [--shortpath] [--helper-only]

Пароль идёт ТЕМ ЖЕ путём, что у keys: файл доступа (строка PASSWORD) → помощник (askpass.cmd на Windows,
askpass.sh на Mac/Linux) с нонсом → ssh. Скрипт пароль не печатает и проверяет, что его нет в выводе.
  --helper-only  без ssh: запускает помощник сам (как его запустил бы ssh) и сравнивает его вывод с паролем
                 по длине и sha256 (сами значения не печатаются) — отделяет «помощник отдал не то» от «сервер отказал»
  --shortpath    (Windows) SSH_ASKPASS — короткое имя 8.3 пути помощника (проверка обхода кириллицы в %TEMP%)
Удалённая команда — `echo askpass-ok` (работает и в cmd, и в bash). Код выхода: 0 — совпало с --expect.
Не для участников (папка ci/ в кит не входит).
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import brain_link  # noqa: E402
import brainlib as bl  # noqa: E402

MARK = "askpass-ok"


def short_path(p):
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, 1024)
    return buf.value if n else str(p)


def h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def helper_only(pw):
    """Помощник без ssh: та же папка/нонс, что делает run_askpass_ssh."""
    import secrets
    tmp = tempfile.mkdtemp(prefix=brain_link.ASKPASS_PREFIX, dir=tempfile.gettempdir())
    try:
        nonce = secrets.token_urlsafe(32)
        Path(tmp, ".nonce").write_text(brain_link._sha256_hex(nonce), encoding="ascii")
        helper, extra = brain_link.make_askpass(tmp)
        env = dict(os.environ)
        env.update(extra)
        env[brain_link.ASKPASS_NONCE_ENV] = nonce
        p = subprocess.run([str(helper), "root@127.0.0.1's password: "], env=env, capture_output=True, timeout=60,
                           shell=False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = p.stdout.decode("utf-8", "replace")
    stripped = out.rstrip("\r\n")
    tail = repr(out[len(stripped):])
    print("helper rc=%s out_len=%d stripped_len=%d pw_len=%d tail=%s sha_out=%s sha_pw=%s stderr=%s"
          % (p.returncode, len(out), len(stripped), len(pw), tail, h(stripped), h(pw),
             p.stderr.decode("utf-8", "replace").replace(pw, "<PW>")[-300:].strip()))
    return 0 if stripped == pw else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", default="22")
    ap.add_argument("--user", required=True)
    ap.add_argument("--expect", choices=("ok", "rejected"), default="ok")
    ap.add_argument("--shortpath", action="store_true")
    ap.add_argument("--helper-only", action="store_true")
    a = ap.parse_args()
    access, _ = bl.read_access(bl.access_path())
    pw = access.get("PASSWORD") or ""
    print("TEMP=%s (ascii=%s)" % ("<…>" + tempfile.gettempdir()[-28:], tempfile.gettempdir().isascii()))
    if a.helper_only:
        return helper_only(pw)
    if a.shortpath:
        real = brain_link.make_askpass

        def make_short(tmpdir):
            helper, extra = real(tmpdir)
            sp = short_path(helper)
            print("shortpath: %s (ascii=%s)" % (sp[-40:], sp.isascii()))
            return sp, extra
        brain_link.make_askpass = make_short
    ssh = brain_link.find_tool("ssh") or "ssh"
    ver = subprocess.run([ssh, "-V"], capture_output=True, text=True)
    print("ssh: %s | %s" % (ssh, (ver.stderr or ver.stdout).strip()))
    kh = Path(tempfile.mkdtemp(prefix="probe-kh-")) / "known_hosts"
    try:
        argv = [ssh, "-F", "none", "-v", "-T", "-o", "UserKnownHostsFile=" + str(kh).replace("\\", "/"),
                "-o", "StrictHostKeyChecking=no", "-o", "PubkeyAuthentication=no",
                "-o", "PreferredAuthentications=password", "-o", "NumberOfPasswordPrompts=1",
                "-o", "ConnectTimeout=15", "-p", str(a.port), "%s@%s" % (a.user, a.host), "echo " + MARK]
        r = brain_link.run_askpass_ssh(argv, b"", timeout=90)
    finally:
        shutil.rmtree(str(kh.parent), ignore_errors=True)
    out, err = r["stdout"], r["stderr"]
    leak = bool(pw) and (pw in out or pw in err)
    interesting = [l for l in err.splitlines()
                   if any(k in l.lower() for k in ("askpass", "password", "authenticat", "spawn", "exec", "denied",
                                                     "remote software", "error", "createprocess", "-f none"))]
    print("rc=%s askpass_called=%s marker_in_stdout=%s leak=%s" % (r["rc"], r["askpass_called"], MARK in out, leak))
    for l in interesting[-25:]:
        print("  ssh: " + l[:300])
    if r["rc"] != 0 and not interesting:
        for l in err.splitlines()[-15:]:
            print("  ssh: " + l[:300])
    if leak:
        print("FAIL: пароль в выводе ssh")
        return 1
    if a.expect == "ok":
        good = r["rc"] == 0 and MARK in out and r["askpass_called"]
    else:
        good = r["rc"] != 0 and r["askpass_called"] and "Permission denied (" in err
    print("RESULT %s (expect=%s)" % ("OK" if good else "MISMATCH", a.expect))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
