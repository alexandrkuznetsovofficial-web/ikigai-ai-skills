#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""smoke_json.py — смоук «один JSON в stdout и ожидаемый код» для скриптов brain-link (лаборатория).

  smoke_json.py [--fake-home] [--with-access] [--env K=V ...] --expect-rc 0,4 [--expect-key human] -- cmd ...

  --fake-home    HOME и USERPROFILE → новая временная папка с пробелом и кириллицей в имени
  --with-access  положить в фейковый дом файл доступа (127.0.0.1, без ключей) — detect дойдёт до развилки
Печатает PASS/FAIL; код 0 — прошло.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile


def main():
    argv = sys.argv[1:]
    if "--" not in argv:
        print("FAIL usage: нужен -- перед командой")
        return 2
    i = argv.index("--")
    opts, cmd = argv[:i], argv[i + 1:]
    env = dict(os.environ)
    expect_rc, expect_keys, fake, access = {0}, ["human"], False, False
    j = 0
    while j < len(opts):
        o = opts[j]
        if o == "--env":
            k, v = opts[j + 1].split("=", 1)
            env[k] = v
            j += 2
        elif o == "--expect-rc":
            expect_rc = {int(x) for x in opts[j + 1].split(",")}
            j += 2
        elif o == "--expect-key":
            expect_keys.append(opts[j + 1])
            j += 2
        elif o == "--fake-home":
            fake = True
            j += 1
        elif o == "--with-access":
            access = True
            j += 1
        else:
            print("FAIL неизвестный флаг %s" % o)
            return 2
    tmp = None
    if fake:
        tmp = tempfile.mkdtemp(prefix="lab-")
        home = os.path.join(tmp, "Тест Дом")
        os.makedirs(home)
        env["HOME"] = env["USERPROFILE"] = home
        env.pop("BRAIN_CONFIG_DIR", None)
        if access:
            cfg = os.path.join(home, ".config", "brain")
            os.makedirs(cfg)
            with open(os.path.join(cfg, "server_access"), "w", encoding="utf-8") as f:
                f.write("SERVER_IP=127.0.0.1\nSERVER_USER=root\nSERVER_PORT=2222\nUSER_ID=111111111\n")
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, timeout=120)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    raw = r.stdout or b""
    obj, enc = None, None
    for enc_try in ("utf-8", "cp1251"):
        try:
            text = raw.decode(enc_try)
        except UnicodeDecodeError:
            continue
        for line in reversed(text.strip().splitlines()):
            try:
                obj = json.loads(line)
                enc = enc_try
                break
            except ValueError:
                continue
        if obj is not None:
            break
    name = " ".join(os.path.basename(c) for c in cmd[1:3])
    problems = []
    if obj is None:
        problems.append("stdout не JSON (%d байт): %r" % (len(raw), raw[:200]))
    else:
        if enc != "utf-8":
            problems.append("stdout не в UTF-8 (прочитался как %s)" % enc)
        for k in expect_keys:
            if k not in obj:
                problems.append("нет поля %s" % k)
    if r.returncode not in expect_rc:
        problems.append("код %d, ждали %s" % (r.returncode, sorted(expect_rc)))
    if b"Traceback" in (r.stderr or b""):
        problems.append("трассировка в stderr: %r" % (r.stderr or b"")[-300:])
    if problems:
        print("FAIL %s: %s" % (name, "; ".join(problems)))
        return 1
    print("PASS %s: код %d, JSON (%s), human=%r" % (name, r.returncode, enc, (obj.get("human") or "")[:100]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
