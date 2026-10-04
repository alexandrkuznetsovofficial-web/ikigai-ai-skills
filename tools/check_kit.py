#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка репозитория скиллов Академии перед сборкой и публикацией (kit 2.0).

Запуск из корня репозитория:
    python3 tools/check_kit.py            # Mac / Linux
    py -3 tools/check_kit.py              # Windows

Что проверяет:
  1. Шапка скиллов: блок --- name / description --- читается.
  2. kit_version: 2.0 у скиллов из списка KIT2_FILES (одно место для списка).
  3. Пути memory/… в текстах скиллов входят в карту §7 KIT_CONVENTIONS.md
     (неизвестный путь = предупреждение, не ошибка).
  4. Нет кириллицы в именах файлов и папок.
  5. Нет файлов *.bak*.
  6. Нет секретов, личной инфраструктуры и личных данных (гейт санитизации).
     Исключения — только через явный ALLOWLIST ниже, с причиной.
  7. Копии-близнецы совпадают байт-в-байт (TWINS).
  8. Нет двух разных скиллов (или двух разных агентов) с одним name: — ошибка.
  9. Бинарные файлы, кроме pdf / png / jpg / zip, — предупреждение.
 10. Каждый *.ps1 начинается с UTF-8 BOM — иначе Windows PowerShell 5.1 читает его в ANSI
     и портит кириллицу (ошибка).

Какие файлы проверяются: если это git-репозиторий — ровно те, что уйдут в публикацию
(git ls-files: в индексе + новые, не попавшие в .gitignore); иначе — обход папки.
Папки dist/ и tools/ (на любом уровне), .git, __pycache__, node_modules пропускаются —
одинаково здесь и в tools/build_dist.py (он берёт список отсюда: list_kit_files).

Код выхода: 0 — ошибок нет (предупреждения допустимы), 1 — есть ошибки.
Python 3.8+, без внешних зависимостей.
"""
from __future__ import print_function

import argparse
import fnmatch
import hashlib
import os
import re
import sys

# ---------------------------------------------------------------------------
# Настройки (единственное место, где их править)
# ---------------------------------------------------------------------------

# Скиллы kit 2.0: новые и изменённые. У каждого в шапке должно быть kit_version: 2.0.
KIT2_FILES = [
    "meeting-1/team-architect.md",
    "second-brain-audit/SKILL.md",
    "memory-garden/SKILL.md",
    "weekly-distill/SKILL.md",
    "memory-upgrade/SKILL.md",
    "project-splitter/SKILL.md",
    "craft-to-skill/SKILL.md",
    "meeting-1/second-brain-architect.md",
    "meeting-1/second-brain-os.md",
    "meeting-1/founder-context-extractor.md",
    "meeting-1/morning-brief.md",
    "meeting-1/gtd-weekly.md",
    "meeting-2-3/orchestrator.md",
    "meeting-2-3/auto-commit-backup.md",
    "meeting-2-3/upgrade-2026-09.md",
    "agents/checker.md",
    "agents/secops.md",
    "agents/researcher.md",
    "brain-link/SKILL.md",  # kit_version: 2.1
]

# Однофайловые скиллы лежат в этих папках: у каждого .md должна быть шапка.
SINGLE_FILE_SKILL_DIRS = ["meeting-1", "meeting-2-3", "agents"]

# Справочники без шапки внутри папок со скиллами (по ТЗ 25.09, раздел 9).
HEADERLESS_OK = {
    "meeting-2-3/upgrade-2026-09.md",
    "meeting-2-3/telegram-bot-setup.md",
    "agents/README.md",
}

# Копии-близнецы: должны совпадать байт-в-байт.
_AUDIT = "novoselie-server-kit/audit"
TWINS = [
    ("meeting-2-3/auto-commit-backup.md", _AUDIT + "/docs/auto-commit-backup.md"),
    ("meeting-2-3/orchestrator.md", _AUDIT + "/docs/orchestrator.md"),
    ("meeting-2-3/upgrade-2026-09.md", _AUDIT + "/docs/upgrade-2026-09.md"),
    ("SETUP_MORNING_BRIEF.md", _AUDIT + "/docs/SETUP_MORNING_BRIEF.md"),
    ("second-brain-audit/SKILL.md", _AUDIT + "/skills/second-brain-audit/SKILL.md"),
    ("second-brain-audit/reference/standard.md",
     _AUDIT + "/skills/second-brain-audit/reference/standard.md"),
]

for _s in ("anthropic-academy", "code-reviewer", "cto", "devops", "secops"):
    TWINS.append(("team-kit/skills/%s/SKILL.md" % _s, _AUDIT + "/skills/%s/SKILL.md" % _s))

# Что не проверяем и не публикуем: имя папки на ЛЮБОМ уровне пути.
# Тот же список использует tools/build_dist.py — правьте только здесь.
SKIP_DIRS = {".git", "dist", "tools", "__pycache__", "node_modules"}

# Бинарные файлы, которые ожидаемо лежат в ките (остальные бинарные — предупреждение).
BINARY_OK = {".pdf", ".png", ".jpg", ".jpeg", ".zip"}

# Папки, где .md с шапкой name: — не скиллы (образцы и справочники).
NOT_SKILL_PARTS = {"templates", "reference"}
# Сам скрипт содержит паттерны поиска, поэтому гейт его не сканирует.
SKIP_SCAN_FILES = {"tools/check_kit.py"}

TEXT_EXT = {
    ".md", ".txt", ".sh", ".ps1", ".py", ".html", ".htm", ".css", ".js",
    ".json", ".yml", ".yaml", ".toml", ".example", ".plist", ".xml", ".csv",
    ".ini", ".cfg", ".env", "", ".conf", ".local", ".service", ".timer",
}

# --- Гейт санитизации -------------------------------------------------------
# (id, regex, что это). Совпадение = ОШИБКА, если не попало в ALLOWLIST.
SENSITIVE_PATTERNS = [
    # Реальные хосты, пути и имена автора — в tools/sensitive_local.txt (не публикуется).
    # Секреты
    ("secret", r"sk-ant-[A-Za-z0-9_\-]{20,}", "ключ Anthropic"),
    ("secret", r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b", "токен Telegram-бота"),
    ("secret", r"(?i)api_hash\s*[=:]\s*[\"']?[0-9a-f]{32}", "api_hash Telegram"),
    ("secret", r"(?i)server_pw", "пароль сервера"),
    ("secret", r"\bghp_[A-Za-z0-9]{30,}", "токен GitHub"),
    ("secret", r"\bgithub_pat_[A-Za-z0-9_]{30,}", "токен GitHub"),
    ("secret", r"\bAKIA[0-9A-Z]{16}\b", "ключ AWS"),
    ("secret", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "закрытый ключ"),
    ("secret", r"\bya29\.[0-9A-Za-z_\-]{20,}", "токен доступа Google OAuth"),
    ("secret", r"\b1//0[0-9A-Za-z_\-]{20,}", "refresh-токен Google OAuth"),
    ("secret", r"\bGOCSPX-[0-9A-Za-z_\-]{20,}", "client secret Google OAuth"),
    ("secret", r"(?i)\b(password|passwd|пароль)\s*[:=]\s*[\"']?(?![<{$\[(*.])"
               r"(?=[^\s\"'<>`(),]*\d)(?=[^\s\"'<>`(),]*[^\W\d_])[^\s\"'<>`(),]{6,}",
     "пароль, записанный значением"),
    # Сырые диалоги и личный контур памяти
    ("personal", r"memory/personal/secret", "секретный контур"),
    ("personal", r"(?m)^\s*(Human|Assistant|H|A):\s", "сырой диалог"),
]

# Локальные паттерны автора (реальные хосты, пути, имена) — вне публичного репозитория.
def _load_local_patterns():
    import os as _os
    f = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "sensitive_local.txt")
    out = []
    if _os.path.isfile(f):
        for line in open(f, encoding="utf-8"):
            if line.strip() and not line.startswith("#"):
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 3:
                    out.append((parts[0], parts[1], parts[2]))
    return out
SENSITIVE_PATTERNS += _load_local_patterns()

# Явные исключения: (id паттерна, маска пути, подстрока в строке, причина).
ALLOWLIST = [
    ("infra", "novoselie-server-kit/*", "/home/brain",
     "учебная конвенция: ученик сам создаёт на СВОЁМ сервере пользователя brain"),
    ("infra", "brain-link/*", "/home/brain",
     "учебная конвенция kit 2.1: пользователь brain на сервере ученика"),
    ("infra", "KIT_CONVENTIONS.md", "/home/brain",
     "контракт связки §8: путь на сервере ученика"),
    ("personal", "*", "memory/personal/secret",
     "упоминание пути как запрета (не в облако), без содержимого"),
]

# Локальные исключения (строки «allow<TAB>id<TAB>маска<TAB>подстрока<TAB>причина» в sensitive_local.txt).
def _load_local_allow():
    import os as _os
    f = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "sensitive_local.txt")
    out = []
    if _os.path.isfile(f):
        for line in open(f, encoding="utf-8"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 5 and parts[0] == "allow":
                out.append(tuple(parts[1:]))
    return out
ALLOWLIST += _load_local_allow()

# Файлы, которые не публикуются по самому имени (содержимое не важно).
SENSITIVE_FILENAMES = [
    (re.compile(r"(?i)\.session(-journal)?$"), "файл сессии Telegram (*.session) — это вход в аккаунт"),
    (re.compile(r"(?i)2fa"), "файл с кодами двухфакторной защиты (2fa)"),
    (re.compile(r"(?i)recovery"), "файл с кодами восстановления (recovery)"),
    (re.compile(r"(?i)^\.env$|\.env\.(local|prod|production)$"), "файл .env с ключами"),
    (re.compile(r"(?i)(^|_)token\.json$|^credentials\.json$|client_secret.*\.json$"),
     "файл с токеном или ключами OAuth"),
]

GENERIC_IPV4 = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])")
CYRILLIC = re.compile(u"[А-Яа-яЁё]")
MEMORY_MENTION = re.compile(r"(?<![\w\-])memory/[A-Za-z0-9_\-./*<>{}Ѐ-ӿ]*")


# ---------------------------------------------------------------------------
class Report(object):
    def __init__(self):
        self.errors = []
        self.warnings = []

    def err(self, section, msg):
        self.errors.append((section, msg))

    def warn(self, section, msg):
        self.warnings.append((section, msg))


def rel(root, path):
    return os.path.relpath(path, root).replace(os.sep, "/")


def is_skipped(relpath):
    """Путь лежит в служебной папке (dist, tools, .git, …) на любом уровне."""
    return any(p in SKIP_DIRS for p in relpath.split("/"))


def git_listed(root, tracked_only=False):
    """Файлы из git: в индексе (+ новые, не попавшие в .gitignore, если tracked_only=False).
    None — это не git-репозиторий или git недоступен."""
    import subprocess
    if not os.path.exists(os.path.join(root, ".git")):
        return None
    cmd = ["git", "-C", root, "-c", "core.quotepath=off", "ls-files", "-z", "--cached"]
    if not tracked_only:
        cmd += ["--others", "--exclude-standard"]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
    except Exception:
        return None
    names = [n for n in out.decode("utf-8", "replace").split("\0") if n]
    return sorted(set(names))


def list_kit_files(root, tracked_only=False):
    """Единый список файлов кита для проверки и сборки: git ls-files (или обход папки),
    без служебных папок, только реально существующие файлы."""
    names = git_listed(root, tracked_only)
    if names is None:
        names = []
        for cur, dnames, fnames in os.walk(root):
            dnames[:] = sorted(d for d in dnames if d not in SKIP_DIRS)
            for f in sorted(fnames):
                names.append(rel(root, os.path.join(cur, f)))
    return [n for n in names
            if not is_skipped(n) and os.path.isfile(os.path.join(root, *n.split("/")))]


def walk(root):
    """Все файлы и папки кита (относительные пути), кроме служебных и игнорируемых git."""
    files = list_kit_files(root)
    dirs = set()
    for f in files:
        parts = f.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))
    return files, sorted(dirs)


def read_text(root, relpath):
    with open(os.path.join(root, relpath), "rb") as fh:
        data = fh.read()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8", errors="replace")


def is_text(relpath):
    name = os.path.basename(relpath)
    if name.endswith(".min.js"):
        return True
    ext = os.path.splitext(name)[1].lower()
    if name.startswith(".") and ext == "":
        return True
    return ext in TEXT_EXT


# --- 1. Шапка -----------------------------------------------------------------
def parse_frontmatter(text):
    """Возвращает (lines, None) или (None, причина). lines — строки между ---."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, "нет открывающей строки ---"
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], None
    return None, "нет закрывающей строки ---"


def check_frontmatter(rep, relpath, text, is_skill):
    fm, why = parse_frontmatter(text)
    if fm is None:
        if is_skill:
            rep.err("шапка", "%s: %s" % (relpath, why))
        return None
    keys = {}
    key_re = re.compile(r"^([A-Za-z_][\w\-]*):(?:\s+(.*)|\s*)$")
    for n, line in enumerate(fm, start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("\t"):
            rep.err("шапка", "%s:%d: табуляция в шапке (YAML её не читает)" % (relpath, n))
            continue
        if line[0] in " -":
            continue  # продолжение значения или элемент списка
        m = key_re.match(line)
        if not m:
            rep.err("шапка", "%s:%d: строка шапки не вида «ключ: значение»" % (relpath, n))
            continue
        key, val = m.group(1), (m.group(2) or "").strip()
        if key in keys:
            rep.err("шапка", "%s:%d: ключ «%s» повторяется" % (relpath, n, key))
        keys[key] = val
        if val and val[0] not in "\"'>|[{" and (": " in val or " #" in val):
            rep.warn("шапка", "%s:%d: в значении «%s» есть «: » или « #» без кавычек — "
                     "строгий YAML может не прочитать" % (relpath, n, key))
    if is_skill:
        for need in ("name", "description"):
            if need not in keys:
                rep.err("шапка", "%s: нет поля %s" % (relpath, need))
        name = keys.get("name", "")
        if name and not re.match(r"^[a-z0-9][a-z0-9\-]*$", name):
            rep.warn("шапка", "%s: name «%s» — лучше латиница в нижнем регистре и дефисы"
                     % (relpath, name))
        if name:
            base = os.path.basename(relpath)
            expected = (os.path.basename(os.path.dirname(relpath)) if base == "SKILL.md"
                        else os.path.splitext(base)[0])
            if name != expected:
                rep.warn("шапка", "%s: name «%s» не совпадает с «%s»" % (relpath, name, expected))
        if "description" in keys and not keys["description"]:
            # описание могло уйти в продолжение строки (>-, | или перенос)
            pass
    return keys


def skill_targets(files):
    out = []
    for f in files:
        if not f.endswith(".md"):
            continue
        if os.path.basename(f) == "SKILL.md":
            out.append(f)
            continue
        top = f.split("/")[0]
        if top in SINGLE_FILE_SKILL_DIRS and f.count("/") == 1 and f not in HEADERLESS_OK:
            out.append(f)
    return out


# --- 2. kit_version -----------------------------------------------------------
KV_FM = re.compile(r"^\s*kit_version:\s*[\"']?2\.[01]\b")
KV_COMMENT = re.compile(r"<!--[^>]*kit_version:\s*2\.[01]\b")


def check_kit_version(rep, root, files_set):
    for f in KIT2_FILES:
        if f not in files_set:
            rep.err("kit_version", "%s: файла нет (скилл из списка kit 2.0)" % f)
            continue
        text = read_text(root, f)
        fm, _ = parse_frontmatter(text)
        ok = False
        if fm is not None:
            ok = any(KV_FM.match(l) for l in fm)
        if not ok:
            head = "\n".join(text.splitlines()[:15])
            ok = bool(KV_COMMENT.search(head))
        if not ok:
            rep.err("kit_version", "%s: нет kit_version: 2.0 в шапке "
                    "(или <!-- kit_version: 2.0 --> у справочника без шапки)" % f)


# --- 3. Карта памяти §7 -------------------------------------------------------
def load_memory_map(root):
    path = os.path.join(root, "KIT_CONVENTIONS.md")
    if not os.path.exists(path):
        return None
    text = read_text(root, "KIT_CONVENTIONS.md")
    m = re.search(r"^## 7\..*?(?=^## \d|\Z)", text, re.S | re.M)
    if not m:
        return None
    sec = m.group(0)
    entries = set()
    for tok in re.findall(r"`([^`]+)`", sec):
        for part in re.split(r"[,\s]+", tok):
            if part.startswith("memory/") and part != "memory/":
                entries.add(part.strip())
    return sorted(entries)


def _sample(path):
    s = re.sub(r"<[^>]*>", "X", path)
    s = re.sub(r"\{[^}]*\}", "X", s)
    s = s.replace("YYYY-MM-DD", "2026-01-01").replace("*", "X")
    return s


def memory_matchers(entries):
    prefixes, regexes = [], []
    for e in entries:
        if e.endswith("/"):
            prefixes.append(e)
            continue
        if any(c in e for c in "*<") or "YYYY" in e:
            pat = re.escape(e)
            pat = pat.replace(r"\*", ".*").replace("YYYY\\-MM\\-DD", r"\d{4}-\d{2}-\d{2}")
            pat = pat.replace("YYYY-MM-DD", r"\d{4}-\d{2}-\d{2}")
            pat = re.sub(r"\\<[^>]*\\>|<[^>]*>", ".+", pat)
            if pat.endswith(r"\.md"):
                pat = pat[:-4] + r"(\.md)?"
            regexes.append(re.compile("^" + pat + "$"))
            parent = e.rsplit("/", 1)[0] + "/"
            if parent != "memory/":
                prefixes.append(parent)
        else:
            regexes.append(re.compile("^" + re.escape(e) + "$"))
    return prefixes, regexes


def check_memory_paths(rep, root, targets, entries):
    if entries is None:
        rep.warn("память", "KIT_CONVENTIONS.md: не нашёл раздел «## 7.» — карту не сверял")
        return
    prefixes, regexes = memory_matchers(entries)
    for f in targets:
        text = read_text(root, f)
        unknown = set()
        for m in MEMORY_MENTION.finditer(text):
            p = m.group(0).rstrip(".,;:)`'\"»*")
            if p in ("memory/", "memory"):
                continue
            s = _sample(p)
            if any(s.startswith(px) for px in prefixes):
                continue
            if any(r.match(s) for r in regexes):
                continue
            if any((s.rstrip("/") + "/") == px for px in prefixes):
                continue
            unknown.add(p)
        for p in sorted(unknown):
            rep.warn("память", "%s: путь %s нет в карте §7 KIT_CONVENTIONS" % (f, p))


# --- 4–5. Имена ---------------------------------------------------------------
def check_names(rep, files, dirs):
    for p in dirs + files:
        name = p.rsplit("/", 1)[-1]
        if CYRILLIC.search(name):
            rep.err("имена", "%s: кириллица в имени" % p)
        if ".bak" in name.lower():
            rep.err("имена", "%s: резервная копия *.bak* в репозитории" % p)
        if name == ".DS_Store":
            rep.warn("имена", "%s: служебный файл macOS" % p)


# --- 6. Гейт санитизации ------------------------------------------------------
def allowed(pid, relpath, line):
    for aid, mask, sub, _why in ALLOWLIST:
        if aid == pid and fnmatch.fnmatch(relpath, mask) and sub in line:
            return True
    return False


def ip_is_harmless(parts):
    a, b, c, d = parts
    if any(x > 255 for x in parts):
        return True
    if a in (0, 10, 127) or a >= 224:
        return True
    if a == 169 and b == 254:  # link-local, адрес метаданных облака
        return True
    if a == 192 and b == 168:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 100 and 64 <= b <= 127:  # Tailscale / CGNAT
        return True
    if (a, b, c) in ((192, 0, 2), (198, 51, 100), (203, 0, 113)):
        return True
    if (a, b, c, d) in ((1, 1, 1, 1), (8, 8, 8, 8), (8, 8, 4, 4), (1, 2, 3, 4)):
        return True
    return False


def check_sensitive(rep, root, files):
    compiled = [(pid, re.compile(rx), what) for pid, rx, what in SENSITIVE_PATTERNS]
    for f in files:
        base = f.rsplit("/", 1)[-1]
        for rx, what in SENSITIVE_FILENAMES:
            if rx.search(base):
                rep.err("санитизация", "%s: %s — такой файл не публикуется" % (f, what))
        if f in SKIP_SCAN_FILES:
            continue
        if not is_text(f):
            ext = os.path.splitext(f)[1].lower()
            if ext == ".pdf":
                rep.warn("санитизация", "%s: PDF не проверяется машинно — посмотри глазами" % f)
            elif ext not in BINARY_OK:
                rep.warn("бинарные", "%s: бинарный файл (не pdf/png/jpg/zip) — нужен ли он в ките? "
                         "Содержимое машинно не проверено" % f)
            continue
        text = read_text(root, f)
        vendor = "/vendor/" in "/" + f
        for n, line in enumerate(text.splitlines(), start=1):
            for pid, rx, what in compiled:
                if rx.search(line) and not allowed(pid, f, line):
                    rep.err("санитизация", "%s:%d: %s [%s]" % (f, n, what, pid))
            if vendor:
                continue
            for m in GENERIC_IPV4.finditer(line):
                parts = [int(x) for x in m.groups()]
                if not ip_is_harmless(parts):
                    rep.warn("санитизация", "%s:%d: похоже на публичный IP %s — если это "
                             "реальный сервер, замени на <IP>" % (f, n, m.group(0)))


# --- 7. Близнецы --------------------------------------------------------------
def check_ps1_bom(rep, root, files):
    """*.ps1 без UTF-8 BOM: PowerShell 5.1 читает файл в кодировке ANSI — кириллица превращается в мусор."""
    for f in files:
        if not f.lower().endswith(".ps1"):
            continue
        with open(os.path.join(root, *f.split("/")), "rb") as fh:
            head = fh.read(3)
        if head != b"\xef\xbb\xbf":
            rep.err("кодировка", "%s без UTF-8 BOM — Windows PowerShell 5.1 испортит кириллицу; "
                                 "сохраните как «UTF-8 with BOM»" % f)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def check_twins(rep, root):
    for a, b in TWINS:
        pa, pb = os.path.join(root, a), os.path.join(root, b)
        missing = [x for x, p in ((a, pa), (b, pb)) if not os.path.exists(p)]
        if missing:
            rep.err("близнецы", "нет файла: %s" % ", ".join(missing))
            continue
        if sha256(pa) != sha256(pb):
            rep.err("близнецы", "%s ≠ %s (должны совпадать байт-в-байт)" % (a, b))


# --- 8. Дубли name: -----------------------------------------------------------
def check_duplicate_names(rep, root, files):
    """Два разных файла с одним name: в одном пространстве (скиллы или агенты) — ошибка.
    Байт-в-байт одинаковые копии (зеркала и близнецы) дублями не считаются.
    Агент (agents/*.md) и скилл с тем же именем — разные вещи: агент secops и скилл secops."""
    groups = {}
    for f in files:
        if not f.endswith(".md"):
            continue
        parts = f.split("/")
        if any(p in NOT_SKILL_PARTS for p in parts[:-1]):
            continue
        text = read_text(root, f)
        fm, _ = parse_frontmatter(text)
        if fm is None:
            continue
        name = desc = None
        for line in fm:
            m = re.match(r"^name:\s*[\"']?([^\"'#]+?)[\"']?\s*$", line)
            if m:
                name = m.group(1).strip()
            if line.startswith("description:"):
                desc = True
        if not name or not desc:
            continue
        space = "агент" if parts[0] == "agents" else "скилл"
        groups.setdefault((space, name), []).append(f)
    for (space, name), paths in sorted(groups.items()):
        if len(paths) < 2:
            continue
        digests = set(sha256(os.path.join(root, *p.split("/"))) for p in paths)
        if len(digests) > 1:
            rep.err("дубли", "%s name «%s» у разных файлов: %s — какой сработает, не гарантировано"
                    % (space, name, ", ".join(paths)))


# ---------------------------------------------------------------------------
def run(root, quiet=False):
    rep = Report()
    files, dirs = walk(root)
    files_set = set(files)

    check_names(rep, files, dirs)

    targets = skill_targets(files)
    for f in targets:
        check_frontmatter(rep, f, read_text(root, f), is_skill=True)
    for f in files:
        if f.endswith(".md") and f not in targets:
            text = read_text(root, f)
            if text.startswith("---"):
                check_frontmatter(rep, f, text, is_skill=False)

    check_kit_version(rep, root, files_set)
    extra = [f for f in KIT2_FILES if f in files_set and f not in targets]
    check_memory_paths(rep, root, targets + extra, load_memory_map(root))
    check_sensitive(rep, root, files)
    check_twins(rep, root)
    check_duplicate_names(rep, root, files)
    check_ps1_bom(rep, root, files)

    print("check_kit · kit 2.0 · %s" % root)
    print("Файлов: %d · скиллов с шапкой: %d" % (len(files), len(targets)))
    if not quiet and rep.warnings:
        print("\nПРЕДУПРЕЖДЕНИЯ (%d):" % len(rep.warnings))
        for sec, msg in rep.warnings:
            print("  [%s] %s" % (sec, msg))
    if rep.errors:
        print("\nОШИБКИ (%d):" % len(rep.errors))
        for sec, msg in rep.errors:
            print("  [%s] %s" % (sec, msg))
        print("\nИтог: ✗ ошибок %d, предупреждений %d" % (len(rep.errors), len(rep.warnings)))
        return 1
    print("\nИтог: ✓ ошибок нет, предупреждений %d" % len(rep.warnings))
    return 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Проверка репозитория скиллов kit 2.0")
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help="корень репозитория (по умолчанию — папка над tools/)")
    ap.add_argument("--quiet", action="store_true", help="не печатать предупреждения")
    args = ap.parse_args()
    sys.exit(run(os.path.abspath(args.root), quiet=args.quiet))


if __name__ == "__main__":
    main()
