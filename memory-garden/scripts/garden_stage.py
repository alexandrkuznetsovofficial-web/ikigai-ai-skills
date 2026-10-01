#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Стадии цифрового сада для заметок памяти (Колфилд / Форте): росток → побег → вечнозелёная.

Ставит в шапку (frontmatter) заметки два поля: `stage:` и `stage_source: rule`.

  seed       росток — сырая мысль, пара строк, без структуры и связей
  sprout     побег — к мысли возвращались: есть структура, связи, примеры
  evergreen  вечнозелёная — лучшее текущее понимание, на него опираются (правила, справочники)

Правила детерминированные, без модели, по контракту памяти kit 2.0 (KIT_CONVENTIONS.md §7):
  feedback_* / reference_* / playbook_* / MEMORY.md / PROJECTS.md / commitments.md → evergreen
  папки drafts/ и inbox/                                                         → seed
  короткая заметка без ссылок                                                     → seed
  остальное                                                                       → sprout

Что скрипт НЕ трогает:
  - заметку, где `stage:` уже стоит (в том числе внутри блока `metadata:`) — ручная стадия главнее;
  - чужое значение `stage:` (не seed / sprout / evergreen) — например, стадия сделки;
  - папки sessions/, secret* (на любом уровне), .secrets, .git, .obsidian и файлы secret*;
  - время изменения файла (сохраняется как было, чтобы брифинг не путал «последние задачи»).

Запуск (Python 3.8+, без зависимостей, Mac / Windows / Linux):
  python3 garden_stage.py                     сухой прогон: только отчёт, ничего не пишет
  python3 garden_stage.py --apply             записать стадии
  python3 garden_stage.py --apply --add-frontmatter
                                              ещё и дописать шапку заметкам, у которых её нет
  python3 garden_stage.py --root ПУТЬ         папка памяти явно (по умолчанию <workspace>/memory)
  -v                                          разбивка по папкам

Повторный --apply ничего не меняет: «реально изменено файлов: 0».
"""
import argparse
import collections
import json
import os
import re
import stat
import sys
from pathlib import Path

STAGES = ("seed", "sprout", "evergreen")
SKIP_DIRS = {".git", ".obsidian", ".secrets", "node_modules", ".trash"}
SKIP_TOP = {"sessions"}
EVERGREEN_PREFIX = ("feedback_", "reference_", "playbook_")
EVERGREEN_FILES = {"MEMORY.md", "PROJECTS.md", "commitments.md"}
SEED_DIRS = {"drafts", "inbox"}
LINK_RE = re.compile(r"\[\[[^\]]+\]\]|\]\([^)]+\.md[)#]")
HEAD_RE = re.compile(r"^#{1,4} ", re.M)
STAGE_RE = re.compile(r"^\s*stage:\s*[\"']?([^\s\"'#]+)", re.M)
SEED_MAX_CHARS = 700


def find_root(arg_root):
    """--root → <workspace>/memory из профиля → ./memory → . (если папка сама называется memory)."""
    if arg_root:
        return Path(arg_root).expanduser().resolve()
    env = Path.home() / ".claude" / "ikigai_env.json"
    try:
        ws = json.loads(env.read_text(encoding="utf-8")).get("workspace")
        if ws:
            p = Path(ws).expanduser() / "memory"
            if p.is_dir():
                return p.resolve()
    except Exception:
        pass
    cwd = Path.cwd()
    if (cwd / "memory").is_dir():
        return (cwd / "memory").resolve()
    if cwd.name == "memory":
        return cwd.resolve()
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
    tmp = path.with_name("." + path.name + ".garden_tmp")
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


def classify(rel_parts, body):
    parts = list(rel_parts)
    base = parts[-1]
    if parts[0] == "archive" and len(parts) > 1:   # архив хранит стадию происхождения
        parts = parts[1:]
    top = parts[0] if len(parts) > 1 else ""
    if base in EVERGREEN_FILES or base.startswith(EVERGREEN_PREFIX) or top == "feedback":
        return "evergreen"
    if top in SEED_DIRS:
        return "seed"
    text = body.strip()
    links = len(LINK_RE.findall(text))
    heads = len(HEAD_RE.findall(text))
    if len(text) < SEED_MAX_CHARS and links == 0:
        return "seed"
    if links == 0 and heads < 2 and len(text) < 1500:
        return "seed"
    return "sprout"


def iter_notes(root):
    for dp, dn, fn in os.walk(str(root)):
        rel_dir = Path(dp).relative_to(root)
        if rel_dir.parts and rel_dir.parts[0] in SKIP_TOP:
            dn[:] = []
            continue
        dn[:] = sorted(d for d in dn if not skip_dir(d))
        for f in sorted(fn):
            if f.endswith(".md") and not f.lower().startswith("secret"):
                yield Path(dp) / f


def _utf8_stdout():
    """Windows / Git Bash: вывод в канал идёт в cp1251/cp1252 и падает на кириллице — переключаем на UTF-8."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="Стадии цифрового сада: seed / sprout / evergreen")
    ap.add_argument("--root", help="папка памяти (по умолчанию <workspace>/memory)")
    ap.add_argument("--apply", action="store_true", help="записать (без флага — сухой прогон)")
    ap.add_argument("--add-frontmatter", action="store_true",
                    help="заметкам без шапки дописать шапку со стадией (только вместе с --apply)")
    ap.add_argument("-v", action="store_true", help="разбивка по папкам")
    a = ap.parse_args()

    root = find_root(a.root)
    if root is None or not root.is_dir():
        print("Не нашёл папку памяти. Укажи её: --root <рабочая папка>/memory")
        return 2

    stats = collections.Counter()
    by_top = collections.defaultdict(collections.Counter)
    no_fm, changed, kept, errors = [], 0, 0, []

    for full in iter_notes(root):
        rel = full.relative_to(root)
        try:
            raw = full.read_bytes()
            bom = raw.startswith(b"\xef\xbb\xbf")
            text = raw[3:].decode("utf-8") if bom else raw.decode("utf-8")
        except Exception as e:
            errors.append("%s: %s" % (rel.as_posix(), e))
            continue
        nl = "\r\n" if "\r\n" in text[:2000] else "\n"
        head, rest = split_frontmatter(text)
        if head is not None:
            m = STAGE_RE.search(head)      # поле может быть вложено в metadata: — ищем с отступом
            if m and m.group(1) in STAGES:
                stats[m.group(1)] += 1
                kept += 1
                continue
            if m:                           # чужая стадия — не трогаем
                stats["foreign_stage"] += 1
                continue
            body = rest.split("\n", 1)[1] if "\n" in rest else ""
        else:
            body = text
        st = classify(rel.parts, body)
        stats[st] += 1
        by_top[rel.parts[0] if len(rel.parts) > 1 else "(корень)"][st] += 1
        if head is None:
            no_fm.append(rel.as_posix())
            if not (a.apply and a.add_frontmatter):
                continue
            new_text = "---" + nl + "stage: " + st + nl + "stage_source: rule" + nl + "---" + nl + text
        else:
            h = head.rstrip("\r\n")
            new_text = h + nl + "stage: " + st + nl + "stage_source: rule" + nl + rest
        if not a.apply:
            continue
        try:
            stt = full.stat()
            data = new_text.encode("utf-8")
            # BOM и окончания строк (nl) — как были; время изменения не трогаем
            write_atomic(full, (b"\xef\xbb\xbf" if bom else b"") + data, stt)
            changed += 1
        except Exception as e:
            errors.append("%s: %s" % (rel.as_posix(), e))

    total = sum(v for k, v in stats.items())
    print("%s — папка: %s" % ("ЗАПИСАНО" if a.apply else "СУХОЙ ПРОГОН (ничего не записано)", root))
    print("заметок сада (без sessions/ и секретного): %d" % total)
    names = {"seed": "росток", "sprout": "побег", "evergreen": "вечнозелёная",
             "foreign_stage": "чужое поле stage (не трогаю)"}
    for k in ("seed", "sprout", "evergreen", "foreign_stage"):
        print("  %5d  %s · %s" % (stats[k], k, names[k]))
    print("  уже со стадией (не тронуты): %d" % kept)
    if no_fm:
        if a.apply and a.add_frontmatter:
            print("  без шапки: %d — шапка дописана" % len(no_fm))
        else:
            print("  без шапки (пропущены): %d — дописать шапку: --apply --add-frontmatter" % len(no_fm))
    if a.v:
        for top, c in sorted(by_top.items(), key=lambda x: -sum(x[1].values()))[:20]:
            print("    %-22s %s" % (top, dict(c)))
    if errors:
        print("  не прочитано / не записано: %d" % len(errors))
        for e in errors[:10]:
            print("    " + e)
    if a.apply:
        print("  реально изменено файлов: %d" % changed)
    else:
        would = total - kept - stats["foreign_stage"] - len(no_fm)
        print("  будет изменено при --apply: %d" % would)
    return 0


if __name__ == "__main__":
    sys.exit(main())
