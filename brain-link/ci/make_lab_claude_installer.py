#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_lab_claude_installer.py — лабораторный «официальный установщик» Claude Code (только GitHub Actions).

`brain-admin update-claude` (RT-11b) принимает в копию бота только ELF-бинарник из
$HOME/.local/share/claude/versions/<версия> — так раскладывает настоящий установщик claude.ai/install.sh.
fake_claude.py — Python-скрипт, поэтому здесь он заворачивается в крошечный ELF (C-обёртка: исходник заглушки
внутри бинарника, запуск `/usr/bin/python3 -c <исходник> аргументы…`), а установщик кладёт этот ELF ровно
туда же, куда настоящий: versions/<версия> + симлинк ~/.local/bin/claude.

Использование: make_lab_claude_installer.py <выход.sh>   (нужен cc/gcc; печатает sha256 ELF)
Результат root кладёт в /etc/brain-bot/lab-claude-installer.sh — brain-admin берёт его вместо скачивания.
Только стандартная библиотека.
"""
import base64
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "2.1.999"

C_TEMPLATE = r"""#include <stdlib.h>
#include <unistd.h>
static const char SRC[] = "%s";
int main(int argc, char **argv) {
    char **a = calloc((size_t)argc + 3, sizeof(char *));
    int i;
    if (!a) return 127;
    a[0] = "python3"; a[1] = "-c"; a[2] = (char *)SRC;
    for (i = 1; i < argc; i++) a[i + 2] = argv[i];
    a[argc + 2] = NULL;
    execv("/usr/bin/python3", a);
    return 127;
}
"""


def c_string(data):
    # каждый байт — восьмеричный escape (ровно 3 цифры): не «съедает» соседние символы, как \x
    return "".join("\\%03o" % b for b in data)


def build_elf(out_path):
    src = open(os.path.join(HERE, "fake_claude.py"), "rb").read()
    cc = shutil.which("cc") or shutil.which("gcc")
    if not cc:
        raise SystemExit("нет cc/gcc — лабораторный ELF не собрать")
    with tempfile.TemporaryDirectory() as tmp:
        c_path = os.path.join(tmp, "fake_claude_elf.c")
        with open(c_path, "w", encoding="ascii") as f:
            f.write(C_TEMPLATE % c_string(src))
        subprocess.run([cc, "-O1", "-o", out_path, c_path], check=True)
    with open(out_path, "rb") as f:
        if f.read(4) != b"\x7fELF":
            raise SystemExit("собранный файл — не ELF")


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        elf = os.path.join(tmp, "claude")
        build_elf(elf)
        data = open(elf, "rb").read()
    b64 = base64.encodebytes(data).decode("ascii")
    script = """#!/bin/bash
# ЛАБОРАТОРИЯ brain-link (GitHub Actions): раскладка как у claude.ai/install.sh, внутри — ELF-обёртка fake_claude.py
set -eu
V=%s
mkdir -p "$HOME/.local/share/claude/versions" "$HOME/.local/bin"
base64 -d > "$HOME/.local/share/claude/versions/$V" <<'B64'
%sB64
chmod 755 "$HOME/.local/share/claude/versions/$V"
ln -sfn "$HOME/.local/share/claude/versions/$V" "$HOME/.local/bin/claude"
echo "lab: claude $V установлен в $HOME/.local/share/claude/versions"
""" % (VERSION, b64)
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        f.write(script)
    print(hashlib.sha256(data).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
