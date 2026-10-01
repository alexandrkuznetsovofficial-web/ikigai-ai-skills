#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Метки PARA в шапке заметок памяти: `para:` + `para_source: rule`. Файлы не двигаются.

PARA (Тиаго Форте) отвечает на вопрос «когда это понадобится»:
  project   проект — есть цель и срок
  area      зона ответственности — без срока, держится постоянно
  resource  справочник — пригодится когда-нибудь
  archive   завершённое и неактивное

Правила (детерминированные, первая подошедшая побеждает):
  archive/ или папка archive где угодно в пути                   → archive
  projects/, папка проекта, task_*, project_*,
  PROJECTS.md, commitments.md                                     → project
  areas/, personal/, insights/profiles/, MEMORY.md, ACTIVE.md,
  goals.md                                                        → area
  остальное (resources/, wiki/, feedback_*, reference_*, …)       → resource

Не трогает: заметки, где `para:` уже стоит (в том числе внутри `metadata:`), папки sessions/,
personal/secret*, .secrets, .git, .obsidian; время изменения файла; BOM и окончания строк.
Заметки без шапки пропускает (шапку дописывает memory-garden с флагом --add-frontmatter).

Запуск (Python 3.8+, без зависимостей):
  python3 para_tag.py --root <рабочая папка>/memory            сухой прогон
  python3 para_tag.py --root <рабочая папка>/memory --apply    запись
Повторный --apply → «реально изменено файлов: 0».
"""
import argparse
import collections
import json
import os
import re
import stat
import sys
from pathlib import Path

PARA = ("project", "area", "resource", "archive")
SKIP_DIRS = {".git", ".obsidian", ".secrets", "node_modules", ".trash"}
SKIP_TOP = {"sessions"}
PROJECT_FILES = {"PROJECTS.md", "commitments.md"}
AREA_FILES = {"MEMORY.md", "ACTIVE.md", "goals.md"}
PARA_RE = re.compile(r"^\s*para:\s*[\"']?([^\s\"'#]+)", re.M)


def _utf8_stdout():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def find_root(arg_root):
    if arg_root:
        return Path(arg_root).expanduser().resolve()
    env = Path.home() / ".claude" / "ikigai_env.json"
    try:
        ws = json.loads(env.read_text(encoding="utf-8")).get("workspace")
        if ws and (Path(ws).expanduser() / "memory").is_dir():
            return (Path(ws).expanduser() / "memory").resolve()
    except Exception:
        pass
    if (Path.cwd() / "memory").is_dir():
        return (Path.cwd() / "memory").resolve()
    return None


def skip_dir(name):
    low = name.lower()
    return name in SKIP_DIRS or low.startswith("secret") or low.startswith(".secret")


KEY_LINE = re.compile(r"^\s*[A-Za-z_][\w\-]*:(\s|$)")


def split_frontmatter(text):
    """Вернуть (head, rest) где head — от первой '---' до закрывающей (без неё), rest — с закрывающей.
    Нет шапки → (None, text).
    «---» в первой строке бывает просто горизонтальной линией. Шапка считается шапкой, только если
    между двумя '---' есть хотя бы одна строка вида «ключ:». Иначе это тело заметки, и в него
    ничего не вставляется."""
    if not text.startswith("---"):
        return None, text
    first_nl = text.find("\n")
    if first_nl == -1 or text[:first_nl].strip() != "---":
        return None, text
    pos = first_nl + 1
    has_key = False
    while pos < len(text):
        nl = text.find("\n", pos)
        line = text[pos:] if nl == -1 else text[pos:nl]
        if line.strip() == "---":
            return (text[:pos], text[pos:]) if has_key else (None, text)
        if KEY_LINE.match(line):
            has_key = True
        if nl == -1:
            break
        pos = nl + 1
    return None, text


def write_atomic(path, data, stt):
    """Запись через временный файл рядом + os.replace: оборванная запись не оставит полфайла.
    Права и время изменения переносятся со старого файла (брифинг ищет «последние задачи» по mtime)."""
    tmp = path.with_name("." + path.name + ".para_tmp")
    try:
        with open(str(tmp), "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(str(tmp), stat.S_IMODE(stt.st_mode))
        except Exception:
            pass
        os.utime(str(tmp), (stt.st_atime, stt.st_mtime))
        os.replace(str(tmp), str(path))
        os.utime(str(path), (stt.st_atime, stt.st_mtime))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


def classify(parts):
    dirs = [p.lower() for p in parts[:-1]]
    base = parts[-1]
    if "archive" in dirs:
        return "archive"
    if (dirs and dirs[0] in ("projects", "project")) or base.startswith(("task_", "project_")) \
            or base in PROJECT_FILES:
        return "project"
    if (dirs and dirs[0] in ("areas", "area", "personal")) or base in AREA_FILES \
            or (len(dirs) >= 2 and dirs[0] == "insights" and dirs[1] == "profiles"):
        return "area"
    return "resource"


def main():
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="Метки PARA в шапке заметок")
    ap.add_argument("--root")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    root = find_root(a.root)
    if root is None or not root.is_dir():
        print("Не нашёл папку памяти. Укажи её: --root <рабочая папка>/memory")
        return 2
    stats = collections.Counter()
    changed, kept, no_fm, errors = 0, 0, 0, []
    for dp, dn, fn in os.walk(str(root)):
        rel_dir = Path(dp).relative_to(root)
        if rel_dir.parts and rel_dir.parts[0] in SKIP_TOP:
            dn[:] = []
            continue
        dn[:] = sorted(d for d in dn if not skip_dir(d))
        for f in sorted(fn):
            if not f.endswith(".md") or f.lower().startswith("secret"):
                continue
            full = Path(dp) / f
            rel = full.relative_to(root)
            try:
                raw = full.read_bytes()
                bom = raw.startswith(b"\xef\xbb\xbf")
                text = (raw[3:] if bom else raw).decode("utf-8")
            except Exception as e:
                errors.append("%s: %s" % (rel.as_posix(), e))
                continue
            head, rest = split_frontmatter(text)
            if head is None:
                no_fm += 1
                continue
            m = PARA_RE.search(head)
            if m:
                stats["kept" if m.group(1) in PARA else "foreign"] += 1
                kept += 1
                continue
            p = classify(rel.parts)
            stats[p] += 1
            if not a.apply:
                continue
            nl = "\r\n" if "\r\n" in text[:2000] else "\n"
            new_text = head.rstrip("\r\n") + nl + "para: " + p + nl + "para_source: rule" + nl + rest
            try:
                st = full.stat()
                write_atomic(full, (b"\xef\xbb\xbf" if bom else b"") + new_text.encode("utf-8"), st)
                changed += 1
            except Exception as e:
                errors.append("%s: %s" % (rel.as_posix(), e))
    print("%s — папка: %s" % ("ЗАПИСАНО" if a.apply else "СУХОЙ ПРОГОН (ничего не записано)", root))
    for k in PARA:
        print("  %5d  %s" % (stats[k], k))
    print("  уже с меткой (не тронуты): %d · без шапки (пропущены): %d" % (kept, no_fm))
    if errors:
        print("  ошибки: %d" % len(errors))
        for e in errors[:10]:
            print("    " + e)
    if a.apply:
        print("  реально изменено файлов: %d" % changed)
    else:
        print("  будет изменено при --apply: %d" % sum(stats[k] for k in PARA))
    return 0


if __name__ == "__main__":
    sys.exit(main())
