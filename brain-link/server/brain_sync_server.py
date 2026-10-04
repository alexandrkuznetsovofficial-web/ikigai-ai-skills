#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
brain_sync_server.py — серверная половина brain-sync (kit 2.1, KIT_CONVENTIONS §8).

Запускается ТОЛЬКО через ограниченный ключ синка в authorized_keys пользователя brain:
    restrict,command="/home/brain/.local/bin/brain_sync_server.py" ssh-ed25519 AAAA… brain-sync
Команду, которую прислал компьютер, sshd кладёт в SSH_ORIGINAL_COMMAND. Разрешены только:
    manifest   stdin: JSON {"private_report": bool} (можно пусто)  → stdout: JSON со списком файлов и server_time
    fetch      stdin: JSON {"paths": [...], "private_paths": [...]} → stdout: tar.gz с этими файлами
    apply      stdin: tar.gz (первый элемент .brain-sync-plan.json + файлы) → stdout: JSON итога
    heartbeat  → stdout: JSON со временем последнего успешного прогона
    version    → stdout: JSON с версией
Всё остальное — отказ. Консоль этим ключом получить нельзя.

Самодостаточный файл: на сервер ставится один (harden.sh). Константы EXCLUDES / зоны — копия из
brain-link/scripts/brainlib.py; tests/test_sync.py сверяет их, править в двух местах сразу.

Корень — /home/brain (переопределяется BRAIN_ROOT, для тестов). Ключи путей протокола:
    "CLAUDE.md" → <root>/CLAUDE.md · "memory/…" → <root>/memory/… · "skills/…" → <root>/.claude/skills/…

Имена. Ключи протокола — всегда NFC. На ext4 имена не нормализуются: файл, приехавший когда-то в NFD (scp/rsync
с Mac), лежит на диске в NFD. Поэтому путь на диске ищется по каждому компоненту: точное имя, иначе имя, чья NFC-форма
совпадает (resolve_component). Запись нового — в NFC; при загрузке поверх NFD-файла и по флагу плана normalize_names
(init/adopt) NFD-имена переименовываются в NFC, если такого NFC-имени рядом ещё нет.
"""
import fnmatch
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import time
import unicodedata

try:
    import fcntl
except ImportError:   # сервер — Linux; на Windows тесты этого файла не гоняются
    fcntl = None

SERVER_VERSION = "2.1"
PROTOCOL = 1

# ---- копия brainlib (сверяется тестом) ----
EXCLUDES_BASE = (
    "personal/", "private/", "secret*/", "sessions/", ".secrets/", ".git/", ".config/",
    "node_modules/", ".venv/", "__pycache__/",
    ".env", "*.env", "*.session", "*.bak*", "*.conflict-*", ".DS_Store",
)
EXCLUDES_SECRETS = (
    ".aws/", ".ssh/", ".gnupg/", ".kube/",
    "*.pem", "*.key", "id_rsa*", "id_ed25519*", "id_ecdsa*", ".netrc", ".npmrc", ".pypirc",
    "credentials*.json", "client_secret*.json", "*token*.json", "*.kdbx", "*.p12", "*.pfx",
)
EXCLUDES = EXCLUDES_BASE + EXCLUDES_SECRETS
MAX_FILE_BYTES = 20 * 1024 * 1024
EXCLUDE_DIRS = tuple(p[:-1] for p in EXCLUDES if p.endswith("/"))
EXCLUDE_FILES = tuple(p for p in EXCLUDES if not p.endswith("/"))
PRIVATE_DIRS = ("personal", "private", "secret*", "sessions")
ROOT_FILES = ("CLAUDE.md",)
ZONE_PREFIXES = ("memory/", "skills/")
INBOX_PREFIX = "memory/inbox/"
DIALOGUES_PREFIX = "memory/dialogues/"
SYNCED_DIRNAME = ".synced"
TMP_SUFFIX = ".brain-tmp"
PLAN_MEMBER = ".brain-sync-plan.json"
# ---- конец копии ----

KEEP_DAYS = 30
ALLOWED = ("manifest", "fetch", "apply", "heartbeat", "version")
MAX_PLAN_BYTES = 8 * 1024 * 1024


class Refuse(Exception):
    pass


def root_dir():
    return os.path.realpath(os.environ.get("BRAIN_ROOT") or "/home/brain")


def state_dir():
    return os.path.join(root_dir(), ".brain-sync")


def server_now():
    # BRAIN_TEST_CLOCK_SHIFT — только для тестов (имитация «часы сервера ушли»)
    try:
        shift = float(os.environ.get("BRAIN_TEST_CLOCK_SHIFT") or 0)
    except ValueError:
        shift = 0.0
    return time.time() + shift


def nfc(s):
    return unicodedata.normalize("NFC", s)


def _match_any(name, patterns):
    low = name.lower()
    return any(fnmatch.fnmatchcase(low, p.lower()) for p in patterns)


def is_excluded_dir(name):
    return _match_any(name, EXCLUDE_DIRS)


def is_excluded_file(name):
    return _match_any(name, EXCLUDE_FILES) or name.endswith(TMP_SUFFIX)


def is_safe_rel(rel):
    if not isinstance(rel, str) or not rel or len(rel) > 1024:
        return False
    if "\\" in rel or "\x00" in rel or rel.startswith("/") or ":" in rel.split("/")[0]:
        return False
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return False
    if rel in ROOT_FILES:
        return True
    return len(parts) >= 2 and (parts[0] + "/") in ZONE_PREFIXES


def excluded(rel):
    parts = rel.split("/")
    if any(is_excluded_dir(d) for d in parts[:-1]):
        return True
    if is_excluded_file(parts[-1]):
        return True
    return rel.startswith(INBOX_PREFIX + SYNCED_DIRNAME + "/")


def zone_of(rel):
    if rel.startswith(INBOX_PREFIX):
        return "inbox"
    if rel.startswith(DIALOGUES_PREFIX):
        return "dialogues"
    if rel in ROOT_FILES or rel.startswith(ZONE_PREFIXES):
        return "computer"
    return None


def zone_roots():
    r = root_dir()
    return (("memory", os.path.join(r, "memory")), ("skills", os.path.join(r, ".claude", "skills")))


def zone_base(rel):
    r = root_dir()
    if rel in ROOT_FILES:
        return r
    return os.path.join(r, "memory") if rel.startswith("memory/") else os.path.join(r, ".claude", "skills")


_DIR_CACHE = {}


def _listdir(path):
    """Точка подмены для тестов (эмуляция ФС, которая не нормализует имена)."""
    return os.listdir(path)


def _entries(d):
    if d not in _DIR_CACHE:
        try:
            _DIR_CACHE[d] = list(_listdir(d))
        except (FileNotFoundError, NotADirectoryError):
            _DIR_CACHE[d] = []
    return _DIR_CACHE[d]


def _forget(d):
    _DIR_CACHE.pop(d, None)


def resolve_component(d, comp):
    """Реальное имя на диске для NFC-компонента comp в папке d: точное совпадение, иначе по NFC-форме, иначе comp."""
    names = _entries(d)
    if comp in names:
        return comp
    for n in names:
        if nfc(n) == comp:
            return n
    return comp


def _rel_components(rel):
    if not is_safe_rel(rel):
        raise Refuse("недопустимый путь: %r" % rel[:200])
    if rel in ROOT_FILES:
        return [rel]
    head, _, tail = rel.partition("/")
    base = ["memory"] if head == "memory" else [".claude", "skills"]
    return base + tail.split("/")


def target_path(rel):
    """Абсолютный путь НА ДИСКЕ для ключа протокола (NFC → реальное имя, см. шапку).
    Ни одна часть пути внутри корня не может быть симлинком."""
    cur = root_dir()
    for comp in _rel_components(rel):
        cur = os.path.join(cur, resolve_component(cur, comp))
        if os.path.islink(cur):
            raise Refuse("симлинк на пути: %r" % rel[:200])
    return cur


def normalize_path(rel):
    """Как target_path, но NFD-компоненты по дороге переименовываются в NFC (если NFC-имени рядом нет).
    Возвращает путь, куда писать (последний компонент — NFC, если файла ещё нет)."""
    cur = root_dir()
    for comp in _rel_components(rel):
        real = resolve_component(cur, comp)
        if real != comp and comp not in _entries(cur):
            try:
                os.rename(os.path.join(cur, real), os.path.join(cur, comp))
                real = comp
            except OSError:
                pass
            _forget(cur)
        cur = os.path.join(cur, real)
        if os.path.islink(cur):
            raise Refuse("симлинк на пути: %r" % rel[:200])
    return cur


def normalize_names():
    """Флаг плана normalize_names (init/adopt): все NFD-имена в зонах → NFC, где нет коллизии. Глубокие — первыми."""
    todo, renamed = [], []
    for prefix, base in zone_roots():
        if not os.path.isdir(base) or os.path.islink(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            dirnames[:] = [d for d in dirnames if not is_excluded_dir(d)
                           and not os.path.islink(os.path.join(dirpath, d))]
            for name in dirnames + filenames:
                if nfc(name) != name:
                    todo.append((dirpath, name))
    todo.sort(key=lambda x: -len(x[0]))
    for dirpath, name in todo:
        new = nfc(name)
        if new in _listdir(dirpath):
            continue                       # коллизия: оба имени существуют — не трогаем
        try:
            os.rename(os.path.join(dirpath, name), os.path.join(dirpath, new))
            renamed.append(os.path.relpath(os.path.join(dirpath, new), root_dir()))
        except OSError:
            pass
        _forget(dirpath)
    return renamed


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def current_sha(path):
    """sha файла на сервере; None — файла нет. Нечитаемый файл — отказ (нечитаемое ≠ отсутствующее)."""
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return None
        return sha256_file(path)
    except FileNotFoundError:
        return None
    except OSError as ex:
        raise Refuse("не могу прочитать на сервере %s: %s" % (path, ex.strerror or type(ex).__name__))


# ---------- обход ----------
def walk_zone(base, prefix, private_mode=False):
    """Обычный режим: синкаемые файлы. private_mode: файлы ВНУТРИ личных папок (для отчёта adopt)."""
    found, skipped = {}, []
    if not os.path.isdir(base) or os.path.islink(base):
        return found, skipped
    def onerror(ex):
        raise Refuse("не могу прочитать на сервере %s: %s" % (getattr(ex, "filename", base),
                                                             ex.strerror or type(ex).__name__))

    for dirpath, dirnames, filenames in os.walk(base, followlinks=False, onerror=onerror):
        reldir = os.path.relpath(dirpath, base)
        reldir = "" if reldir == "." else nfc(reldir.replace(os.sep, "/"))
        in_private = any(_match_any(p, PRIVATE_DIRS) for p in reldir.split("/") if p)
        keep = []
        for d in dirnames:
            full = os.path.join(dirpath, d)
            drel = "%s/%s%s" % (prefix, reldir + "/" if reldir else "", nfc(d))
            if os.path.islink(full) or drel == INBOX_PREFIX + SYNCED_DIRNAME:
                continue
            if is_excluded_dir(d):
                # в private_mode спускаемся только в личные папки (и в то, что внутри них)
                if private_mode and (in_private or _match_any(d, PRIVATE_DIRS)):
                    keep.append(d)
                continue
            keep.append(d)
        dirnames[:] = keep
        if private_mode and not in_private:
            continue
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = "%s/%s%s" % (prefix, reldir + "/" if reldir else "", nfc(fn))
            if os.path.islink(full) or not os.path.isfile(full) or fn.endswith(TMP_SUFFIX):
                continue
            if is_excluded_file(fn) or not is_safe_rel(rel):
                continue
            if private_mode and any(is_excluded_dir(p) and not _match_any(p, PRIVATE_DIRS)
                                    for p in rel.split("/")[:-1]):
                continue   # .git внутри personal и т.п. не везём даже по флагу
            try:
                st = os.stat(full)
            except FileNotFoundError:
                continue
            except OSError as ex:
                raise Refuse("не могу прочитать на сервере %s: %s" % (full, ex.strerror or type(ex).__name__))
            if st.st_size > MAX_FILE_BYTES:
                skipped.append({"rel": rel, "reason": "больше 20 МБ"})
                continue
            if rel in found:
                # ext4: рядом NFC- и NFD-имя одного файла. Ключ один — берём точное NFC, второе докладываем
                if fn == nfc(fn):
                    skipped.append({"rel": rel, "reason": "есть копия с именем в NFD: %s" % found[rel][0]})
                else:
                    skipped.append({"rel": rel, "reason": "есть копия с именем в NFD: %s" % full})
                    continue
            found[rel] = (full, st.st_size, st.st_mtime_ns)
    return found, skipped


def load_cache():
    try:
        with open(os.path.join(state_dir(), "hash_cache.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache):
    try:
        ensure_dir(state_dir())
        tmp = os.path.join(state_dir(), "hash_cache.json.%d%s" % (os.getpid(), TMP_SUFFIX))
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        os.replace(tmp, os.path.join(state_dir(), "hash_cache.json"))
    except OSError:
        pass


def hashed(found, cache, new_cache):
    res = {}
    for rel, (full, size, mt) in found.items():
        c = cache.get(rel)
        if c and c[0] == size and c[1] == mt:
            sha = c[2]
        else:
            try:
                sha = sha256_file(full)
            except FileNotFoundError:
                continue
            except OSError as ex:
                raise Refuse("не могу прочитать на сервере %s: %s" % (full, ex.strerror or type(ex).__name__))
        res[rel] = sha
        new_cache[rel] = [size, mt, sha]
    return res


def sync_files():
    found, skipped = {}, []
    for prefix, base in zone_roots():
        f, s = walk_zone(base, prefix)
        found.update(f)
        skipped += s
    claude_md = os.path.join(root_dir(), resolve_component(root_dir(), "CLAUDE.md"))
    if os.path.isfile(claude_md) and not os.path.islink(claude_md):
        st = os.stat(claude_md)
        if st.st_size <= MAX_FILE_BYTES:
            found["CLAUDE.md"] = (claude_md, st.st_size, st.st_mtime_ns)
    return found, skipped


def private_files():
    found = {}
    for prefix, base in zone_roots():
        f, _ = walk_zone(base, prefix, private_mode=True)
        found.update(f)
    return found


# ---------- файлы и права ----------
# Права на сервере (kit 2.1, RT-11): синк работает под brain с umask 027 — файлы 0640, папки 0750, группа brain.
# Бот — отдельный пользователь brainbot в группе brain: память читает, пишет только в memory/inbox и
# memory/dialogues. Эти две папки — 2770 (setgid: файлы бота остаются в группе brain, он создаёт их 0660),
# поэтому синк (brain) читает заметки бота и переносит inbox → inbox/.synced: rename разрешён правом записи
# группы на папку, владелец файла (brainbot) значения не имеет.
BOT_DIRS = ("inbox", "dialogues")
BOT_DIR_MODE = 0o2770


def ensure_bot_dirs():
    mem = os.path.join(root_dir(), "memory")
    if not os.path.isdir(mem) or os.path.islink(mem):
        return
    for sub in BOT_DIRS:
        p = os.path.join(mem, sub)
        try:
            if os.path.islink(p):
                continue
            if not os.path.isdir(p):
                os.mkdir(p, 0o770)
                _forget(mem)
            st = os.lstat(p)
            me = getattr(os, "geteuid", lambda: None)()   # на Windows (лаборатория, local-транспорт) прав нет
            if me is not None and st.st_uid == me and (st.st_mode & 0o7777) != BOT_DIR_MODE:
                os.chmod(p, BOT_DIR_MODE)
        except OSError:
            pass   # не наша папка или ФС без setgid — бот скажет в selftest


def ensure_dir(path):
    if not os.path.isdir(path):
        _forget(os.path.dirname(path))
        os.makedirs(path, mode=0o750, exist_ok=True)
        try:
            os.chmod(path, 0o750)
        except OSError:
            pass


def ensure_parents(path):
    parent = os.path.dirname(path)
    missing = []
    while parent and not os.path.isdir(parent):
        missing.append(parent)
        parent = os.path.dirname(parent)
    for d in reversed(missing):
        ensure_dir(d)


def prune_empty(path, stop):
    d = os.path.dirname(path)
    while d.startswith(stop + os.sep) and d != stop:
        try:
            os.rmdir(d)
        except OSError:
            break
        d = os.path.dirname(d)


def unique_path(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    i = 2
    while os.path.exists("%s-%d%s" % (stem, i, ext)):
        i += 1
    return "%s-%d%s" % (stem, i, ext)


def move_aside(src, dest):
    dest = unique_path(dest)
    ensure_parents(dest)
    os.replace(src, dest)
    _forget(os.path.dirname(src))
    try:
        os.utime(dest, None)   # срок 30 дней считаем от момента переноса
    except OSError:
        pass
    return dest


def cleanup_old():
    """Корзина ~/.brain-trash/ДАТА/ и inbox/.synced/ — старше 30 дней удаляются."""
    limit = time.time() - KEEP_DAYS * 86400
    trash = os.path.join(root_dir(), ".brain-trash")
    if os.path.isdir(trash) and not os.path.islink(trash):
        for name in os.listdir(trash):
            p = os.path.join(trash, name)
            try:
                day = time.mktime(time.strptime(name[:10], "%Y-%m-%d"))
            except ValueError:
                continue
            if day < limit and os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p, ignore_errors=True)
    synced = os.path.join(root_dir(), "memory", "inbox", SYNCED_DIRNAME)
    if os.path.isdir(synced) and not os.path.islink(synced):
        for dirpath, dirnames, filenames in os.walk(synced, topdown=False):
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                try:
                    if os.lstat(p).st_mtime < limit:
                        os.remove(p)
                except OSError:
                    pass
            if dirpath != synced:
                try:
                    os.rmdir(dirpath)
                except OSError:
                    pass


# ---------- tar ----------
def check_member(m):
    name = m.name
    if name == PLAN_MEMBER:
        if not m.isfile() or m.size > MAX_PLAN_BYTES:
            raise Refuse("служебный элемент архива испорчен")
        return name
    if not m.isfile():
        raise Refuse("в архиве не обычный файл: %r" % name[:120])
    if name.startswith("/") or name.startswith("\\") or (len(name) > 1 and name[1] == ":"):
        raise Refuse("абсолютный путь в архиве: %r" % name[:120])
    if ".." in name.replace("\\", "/").split("/"):
        raise Refuse("путь с .. в архиве: %r" % name[:120])
    if not is_safe_rel(nfc(name)):
        raise Refuse("недопустимый путь в архиве: %r" % name[:120])
    if m.size > MAX_FILE_BYTES:
        raise Refuse("файл больше 20 МБ в архиве: %r" % name[:120])
    return nfc(name)


def write_tar(stream, items):
    with tarfile.open(fileobj=stream, mode="w|gz") as tf:
        for rel, full in items:
            with open(full, "rb") as f:
                data = f.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                continue
            ti = tarfile.TarInfo(rel)
            ti.size = len(data)
            ti.mode = 0o640
            ti.mtime = int(time.time())
            tf.addfile(ti, io.BytesIO(data))


# ---------- команды ----------
def read_stdin_json():
    data = sys.stdin.buffer.read(MAX_PLAN_BYTES + 1)
    if len(data) > MAX_PLAN_BYTES:
        raise Refuse("слишком большой запрос")
    if not data.strip():
        return {}
    try:
        obj = json.loads(data.decode("utf-8"))
    except Exception:
        raise Refuse("запрос не JSON")
    if not isinstance(obj, dict):
        raise Refuse("запрос не объект JSON")
    return obj


def cmd_manifest():
    req = read_stdin_json()
    cache = load_cache()
    new_cache = {}
    found, skipped = sync_files()
    files = hashed(found, cache, new_cache)
    res = {"ok": True, "version": SERVER_VERSION, "protocol": PROTOCOL, "server_time": server_now(),
           "files": files, "skipped": skipped[:200],
           "heartbeat": os.path.isfile(os.path.join(state_dir(), "heartbeat"))}
    if req.get("private_report"):
        priv = private_files()
        res["private"] = {"count": len(priv), "bytes": sum(v[1] for v in priv.values()),
                          "files": {rel: v[1] for rel, v in sorted(priv.items())}}
    save_cache(new_cache)
    emit(res)


def cmd_fetch():
    req = read_stdin_json()
    paths = req.get("paths") or []
    private_paths = req.get("private_paths") or []
    if not isinstance(paths, list) or not isinstance(private_paths, list):
        raise Refuse("paths должен быть списком")
    items = []
    for rel in paths:
        rel = nfc(str(rel))
        if not is_safe_rel(rel) or excluded(rel):
            raise Refuse("этот путь не отдаётся: %r" % rel[:200])
        full = target_path(rel)
        if os.path.isfile(full) and not os.path.islink(full):
            items.append((rel, full))
    if private_paths:
        priv = private_files()
        for rel in private_paths:
            rel = nfc(str(rel))
            if rel not in priv:
                raise Refuse("это не файл личной зоны: %r" % rel[:200])
            target_path(rel)
            items.append((rel, priv[rel][0]))
    out = sys.stdout.buffer
    write_tar(out, items)
    out.flush()


def cmd_apply():
    sd = state_dir()
    ensure_dir(sd)
    stage = os.path.join(sd, "incoming-%d-%d" % (os.getpid(), int(time.time())))
    os.makedirs(stage, mode=0o700)
    try:
        plan, staged = None, {}
        try:
            with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as tf:
                idx = 0
                for m in tf:
                    if m.isdir():
                        continue
                    name = check_member(m)
                    f = tf.extractfile(m)
                    data = f.read(MAX_FILE_BYTES + 1) if f else b""
                    if name == PLAN_MEMBER:
                        if plan is not None or staged:
                            raise Refuse("план должен быть первым и единственным")
                        plan = json.loads(data.decode("utf-8"))
                        if not isinstance(plan, dict):
                            raise Refuse("план не объект")
                        continue
                    if plan is None:
                        raise Refuse("в архиве нет плана первым элементом")
                    if name not in (plan.get("uploads") or {}) or name in staged:
                        raise Refuse("в архиве лишний файл: %r" % name[:120])
                    if len(data) > MAX_FILE_BYTES:
                        raise Refuse("файл больше 20 МБ: %r" % name[:120])
                    idx += 1
                    sp = os.path.join(stage, "%06d" % idx)
                    with open(sp, "wb") as out:
                        out.write(data)
                    staged[name] = (sp, hashlib.sha256(data).hexdigest())
        except tarfile.TarError as ex:
            raise Refuse("архив повреждён: %s" % ex)
        if plan is None:
            raise Refuse("в архиве нет плана")
        uploads = plan.get("uploads") or {}
        deletes = plan.get("deletes") or {}
        acks = plan.get("inbox_ack") or {}
        if not all(isinstance(x, dict) for x in (uploads, deletes, acks)):
            raise Refuse("план испорчен")
        # проверяем ВСЁ до первой записи: отказ — значит ничего не тронуто
        for rel, spec in uploads.items():
            if zone_of(rel) != "computer" or excluded(rel) or not isinstance(spec, dict):
                raise Refuse("загрузка вне зоны компьютера: %r" % rel[:200])
            target_path(rel)
        for rel in deletes:
            if zone_of(rel) != "computer" or excluded(rel):
                raise Refuse("удаление вне зоны компьютера: %r" % rel[:200])
            target_path(rel)
        for rel in acks:
            if zone_of(rel) != "inbox" or excluded(rel):
                raise Refuse("подтверждение не из inbox: %r" % rel[:200])
            target_path(rel)

        if os.environ.get("BRAIN_TEST_FAIL_APPLY"):   # только для тестов: «apply упал после fetch»
            raise Refuse("тестовый отказ apply")
        res = {"ok": True, "written": [], "deleted": [], "acked": [], "skipped": [], "renamed": [],
               "server_time": server_now()}
        if plan.get("normalize_names"):
            res["renamed"] = normalize_names()[:200]
        for rel, spec in sorted(uploads.items()):
            # один испорченный/недоехавший файл не валит весь прогон: он пропускается, остальное пишется
            if rel not in staged:
                res["skipped"].append({"rel": rel, "reason": "нет в архиве"})
                continue
            if staged[rel][1] != spec.get("sha"):
                res["skipped"].append({"rel": rel, "reason": "sha не совпал"})
                continue
            dest = target_path(rel)
            if os.path.isdir(dest):
                res["skipped"].append({"rel": rel, "reason": "на сервере здесь папка"})
                continue
            if current_sha(dest) != spec.get("expected"):
                res["skipped"].append({"rel": rel, "reason": "changed"})   # кто-то правил между вызовами
                continue
            dest = normalize_path(rel)
            ensure_parents(dest)
            os.replace(staged[rel][0], dest)
            os.chmod(dest, 0o640)
            res["written"].append(rel)
        day = time.strftime("%Y-%m-%d")
        trash_day = os.path.join(root_dir(), ".brain-trash", day)
        for rel, expected in sorted(deletes.items()):
            src = target_path(rel)
            cur = current_sha(src)
            if cur is None:
                res["deleted"].append(rel)   # уже нет — цель достигнута
                continue
            if cur != expected:
                res["skipped"].append({"rel": rel, "reason": "changed"})
                continue
            move_aside(src, os.path.join(trash_day, *rel.split("/")))
            res["deleted"].append(rel)
            prune_empty(src, zone_base(rel))
        month = time.strftime("%Y-%m")
        inbox_root = os.path.join(root_dir(), "memory", "inbox")
        for rel, sha in sorted(acks.items()):
            src = target_path(rel)
            if current_sha(src) != sha:
                res["skipped"].append({"rel": rel, "reason": "changed"})
                continue
            inner = rel[len(INBOX_PREFIX):].split("/")
            move_aside(src, os.path.join(inbox_root, SYNCED_DIRNAME, month, *inner))
            res["acked"].append(rel)
            prune_empty(src, inbox_root)
        cleanup_old()
        ensure_bot_dirs()   # первая выгрузка (init) только что создала memory/ — папки бота сразу 2770
        if plan.get("heartbeat"):
            hb = os.path.join(sd, "heartbeat")
            tmp = hb + "." + str(os.getpid()) + TMP_SUFFIX
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"last_success": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "epoch": time.time(),
                           "client": str(plan.get("client") or "")[:80]}, f)
            os.replace(tmp, hb)
            os.chmod(hb, 0o640)
        emit(res)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def cmd_heartbeat():
    hb = os.path.join(state_dir(), "heartbeat")
    try:
        with open(hb, encoding="utf-8") as f:
            data = json.load(f)
        data["age_sec"] = int(time.time() - os.path.getmtime(hb))
    except Exception:
        data = {"last_success": None}
    data.update({"ok": True, "server_time": server_now()})
    emit(data)


def cmd_version():
    emit({"ok": True, "version": SERVER_VERSION, "protocol": PROTOCOL, "server_time": server_now(),
          "python": sys.version.split()[0]})


def _write(stream, text):
    """UTF-8 байтами: локаль sshd-сессии бывает C/POSIX (ascii) — кириллица и ↑↓ не должны ронять сервер."""
    try:
        buf = getattr(stream, "buffer", None)
        if buf is not None:
            buf.write(text.encode("utf-8", "backslashreplace"))
        else:
            stream.write(text)
        stream.flush()
    except (OSError, ValueError, UnicodeError):
        pass


def emit(obj):
    try:
        text = json.dumps(obj, ensure_ascii=False)
        text.encode("utf-8")
    except UnicodeEncodeError:   # суррогаты из «битых» имён файлов
        text = json.dumps(obj, ensure_ascii=True)
    _write(sys.stdout, text + "\n")


def main():
    os.umask(0o027)
    raw = os.environ.get("SSH_ORIGINAL_COMMAND")
    words = raw.split() if raw is not None else sys.argv[1:]
    cmd = words[0] if words else ""
    if cmd not in ALLOWED or len(words) > 1:
        _write(sys.stderr, "brain_sync_server: команда не разрешена\n")
        return 1
    ensure_dir(state_dir())
    ensure_bot_dirs()
    lock_f = open(os.path.join(state_dir(), "server.lock"), "a")
    try:
        if fcntl is not None and cmd in ("manifest", "fetch", "apply"):
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        {"manifest": cmd_manifest, "fetch": cmd_fetch, "apply": cmd_apply,
         "heartbeat": cmd_heartbeat, "version": cmd_version}[cmd]()
        return 0
    except Refuse as ex:
        _write(sys.stderr, "brain_sync_server: отказ: %s\n" % ex)
        return 3
    except Exception as ex:
        _write(sys.stderr, "brain_sync_server: ошибка %s: %s\n" % (type(ex).__name__, str(ex)[:300]))
        return 4
    finally:
        lock_f.close()


if __name__ == "__main__":
    sys.exit(main())
