#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cmdline_watch.py — сторож RT-12 лаборатории: токен не должен появляться в /proc/*/cmdline (Linux, от root).

  cmdline_watch.py --secret-file F [--secret-file F2 ...] --stop STOPFILE --out SUMMARY.json [--interval 0.02]

Каждые interval секунд читает cmdline всех процессов и ищет точные значения токенов. Пишет итог в SUMMARY.json:
{"scans": N, "hits": [{"pid", "comm", "label"}]} — сами значения и строки команд не пишет никогда.
Работает, пока нет STOPFILE.
"""
import argparse
import json
import os
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secret-file", action="append", required=True)
    ap.add_argument("--stop", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--interval", type=float, default=0.02)
    a = ap.parse_args()
    secrets = []
    for p in a.secret_file:
        with open(p, "rb") as f:
            v = f.read().strip()
        if v:
            secrets.append((os.path.basename(p), v))
    me = os.getpid()
    scans, hits, seen = 0, [], set()
    while not os.path.exists(a.stop):
        scans += 1
        for pid in os.listdir("/proc"):
            if not pid.isdigit() or int(pid) == me:
                continue
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as f:
                    cmd = f.read()
            except OSError:
                continue
            for label, v in secrets:
                if v in cmd and (pid, label) not in seen:
                    seen.add((pid, label))
                    try:
                        with open("/proc/%s/comm" % pid) as f:
                            comm = f.read().strip()
                    except OSError:
                        comm = "?"
                    hits.append({"pid": int(pid), "comm": comm, "label": label, "t": time.time()})
        if scans % 50 == 1:
            dump(a.out, scans, hits, False)
        time.sleep(a.interval)
    dump(a.out, scans, hits, True)
    return 0


def dump(out, scans, hits, finished):
    with open(out + ".tmp", "w") as f:
        json.dump({"scans": scans, "hits": hits, "finished": finished}, f)
    os.replace(out + ".tmp", out)


if __name__ == "__main__":
    main()
