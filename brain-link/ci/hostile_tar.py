#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hostile_tar.py — враждебные архивы для RT-10 (apply в brain_sync_server.py должен отказать, ничего не записав).

  hostile_tar.py OUTDIR   → OUTDIR/<имя>.tgz и OUTDIR/index.json [{"name", "file", "expect": "refuse"|"accept"}]

Каждый враждебный архив: план первым, потом обычный файл memory/rt10_good.md (проверка «отказ — значит не
записано ничего, даже хорошее»), потом враждебный элемент. control.tgz — честный архив (ожидается приём).
"""
import gzip
import hashlib
import io
import json
import os
import sys
import tarfile
import time

PLAN = ".brain-sync-plan.json"
GOOD = b"# rt10 good file\n"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def plan_bytes(uploads):
    return json.dumps({"uploads": uploads, "deletes": {}, "inbox_ack": {}, "heartbeat": False,
                       "client": "lab-rt10"}).encode("utf-8")


def add_bytes(tf, name, data, mode=0o640):
    ti = tarfile.TarInfo(name)
    ti.size = len(data)
    ti.mode = mode
    ti.mtime = int(time.time())
    tf.addfile(ti, io.BytesIO(data))


class Zeros(io.RawIOBase):
    """Поток нулей заданной длины без выделения памяти."""

    def __init__(self, n):
        self.left = n

    def readable(self):
        return True

    def readinto(self, b):
        n = min(len(b), self.left)
        b[:n] = b"\0" * n
        self.left -= n
        return n


def build(path, uploads, extra):
    with tarfile.open(path, "w:gz") as tf:
        add_bytes(tf, PLAN, plan_bytes(uploads))
        add_bytes(tf, "memory/rt10_good.md", GOOD)
        extra(tf)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    good = {"memory/rt10_good.md": {"sha": sha(GOOD), "expected": None}}
    idx = []

    def case(name, hostile_name, extra, expect="refuse", uploads=None):
        u = dict(good)
        if hostile_name:
            u[hostile_name] = {"sha": "0" * 64, "expected": None}
        if uploads is not None:
            u = uploads
        p = os.path.join(out, name + ".tgz")
        build(p, u, extra)
        idx.append({"name": name, "file": p, "expect": expect})

    def symlink(tf):
        ti = tarfile.TarInfo("memory/rt10_link.md")
        ti.type, ti.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tf.addfile(ti)
    case("symlink", "memory/rt10_link.md", symlink)

    def hardlink(tf):
        ti = tarfile.TarInfo("memory/rt10_hard.md")
        ti.type, ti.linkname = tarfile.LNKTYPE, "/etc/passwd"
        tf.addfile(ti)
    case("hardlink", "memory/rt10_hard.md", hardlink)

    case("dotdot", "memory/../../rt10_escape.md", lambda tf: add_bytes(tf, "memory/../../rt10_escape.md", b"x\n"))
    case("absolute", "/tmp/rt10_abs.md", lambda tf: add_bytes(tf, "/tmp/rt10_abs.md", b"x\n"))
    case("outside_zone", ".ssh/authorized_keys",
         lambda tf: add_bytes(tf, ".ssh/authorized_keys", b"ssh-ed25519 AAAA lab\n"))
    case("excluded_personal", "memory/personal/rt10.md",
         lambda tf: add_bytes(tf, "memory/personal/rt10.md", b"x\n"))

    def big(tf, name="memory/rt10_big.md", n=25 * 1024 * 1024):
        ti = tarfile.TarInfo(name)
        ti.size, ti.mode = n, 0o640
        tf.addfile(ti, Zeros(n))
    case("big25mb", "memory/rt10_big.md", big)
    case("gzbomb_member", "memory/rt10_bomb.md", lambda tf: big(tf, "memory/rt10_bomb.md", 300 * 1024 * 1024))

    # «голая» gzip-бомба: 512 МБ нулей без структуры tar
    p = os.path.join(out, "gzbomb_raw.tgz")
    with gzip.open(p, "wb", compresslevel=9) as g:
        chunk = b"\0" * (1 << 20)
        for _ in range(512):
            g.write(chunk)
    idx.append({"name": "gzbomb_raw", "file": p, "expect": "refuse"})

    # план-бомба: служебный элемент больше лимита плана
    p = os.path.join(out, "plan_bomb.tgz")
    with tarfile.open(p, "w:gz") as tf:
        ti = tarfile.TarInfo(PLAN)
        ti.size = 64 * 1024 * 1024
        tf.addfile(ti, Zeros(ti.size))
    idx.append({"name": "plan_bomb", "file": p, "expect": "refuse"})

    # контроль: честный архив принимается (иначе отказы выше ничего не доказывают)
    ctl = b"# rt10 control\n"
    p = os.path.join(out, "control.tgz")
    with tarfile.open(p, "w:gz") as tf:
        add_bytes(tf, PLAN, plan_bytes({"memory/rt10_control.md": {"sha": sha(ctl), "expected": None}}))
        add_bytes(tf, "memory/rt10_control.md", ctl)
    idx.append({"name": "control", "file": p, "expect": "accept"})

    with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, indent=1)
    print("\n".join("%s %s" % (c["name"], c["expect"]) for c in idx))


if __name__ == "__main__":
    main()
