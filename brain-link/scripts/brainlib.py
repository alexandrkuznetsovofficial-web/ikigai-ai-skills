#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
brainlib.py — общая библиотека связки «компьютер — мастерская, сервер — база» (kit 2.1, KIT_CONVENTIONS §8).

Правила, которые соблюдают все скрипты brain-link:
  * stdout — ровно один JSON-объект, в нём поле "human" — одна строка по-русски для человека;
  * коды выхода: 0 ок · 1 нет конфига / плохие аргументы · 2 не пустили (ssh-ключ, ключ сервера) ·
    3 нужно подтверждение человека (массовое удаление, ветка B, --yes) · 4 ошибка сервера / сети;
  * секреты никогда не печатаются, только маска вида "ab…yz (16 символов)";
  * только стандартная библиотека Python 3.9+, одинаково на Mac, Windows и Linux.

Служебные файлы — ~/.config/brain/ (Windows %USERPROFILE%\\.config\\brain\\), переопределяется BRAIN_CONFIG_DIR.
Список исключений EXCLUDES живёт ТОЛЬКО здесь; brain_sync_server.py держит копию, тест сверяет их побайтно.
"""
import argparse
import fnmatch
import hashlib
import io
import json
import logging
import logging.handlers
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath

KIT_VERSION = "2.1"
PROTOCOL = 1

EXIT_OK, EXIT_CONFIG, EXIT_AUTH, EXIT_CONFIRM, EXIT_PROVIDER = 0, 1, 2, 3, 4

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

# ---------- контракт §8: исключено в ОБЕ стороны ----------
# «/» на конце — папка (любой уровень вложенности), без «/» — имя файла. Сравнение без учёта регистра.
EXCLUDES = (
    "personal/", "private/", "secret*/", "sessions/", ".secrets/", ".git/", ".config/",
    "node_modules/", ".venv/", "__pycache__/",
    ".env", "*.env", "*.session", "*.bak*", "*.conflict-*", ".DS_Store",
)
MAX_FILE_BYTES = 20 * 1024 * 1024
EXCLUDE_DIRS = tuple(p[:-1] for p in EXCLUDES if p.endswith("/"))
EXCLUDE_FILES = tuple(p for p in EXCLUDES if not p.endswith("/"))
# личные зоны: на сервере их быть не должно; adopt только докладывает (и по --pull-private забирает домой)
PRIVATE_DIRS = ("personal", "private", "secret*", "sessions")

# ---------- зоны ----------
# Ключи путей в протоколе: "CLAUDE.md" (корень рабочей папки), "memory/…", "skills/…".
#   компьютер:  <workspace>/CLAUDE.md, <workspace>/memory/…, ~/.claude/skills/…
#   сервер:     /home/brain/CLAUDE.md,  /home/brain/memory/…,  /home/brain/.claude/skills/…
ROOT_FILES = ("CLAUDE.md",)          # из корня рабочей папки синкается только этот файл
ZONE_PREFIXES = ("memory/", "skills/")
INBOX_PREFIX = "memory/inbox/"
DIALOGUES_PREFIX = "memory/dialogues/"
SYNCED_DIRNAME = ".synced"           # memory/inbox/.synced/ГГГГ-ММ/ — забранное, только на сервере
TMP_SUFFIX = ".brain-tmp"
PLAN_MEMBER = ".brain-sync-plan.json"

MASS_DELETE_ABS = 25        # больше 25 удалений за прогон — стоп
MASS_DELETE_PCT = 0.10      # или больше 10 % зоны компьютера…
MASS_DELETE_MIN = 3         # …но правило процентов включается с 3 удалений (иначе в маленькой папке стоп на каждом)
CLOCK_WARN_SEC = 120
LOCK_STALE_SEC = 600


# ---------- вывод (контракт KIT: один JSON, поле human) ----------
_BAD_CHARS = {c: " " for c in list(range(0x00, 0x20)) + [0x7F, 0x2028, 0x2029]}


def clean(value):
    if isinstance(value, str):
        return " ".join(value.translate(_BAD_CHARS).split())
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


class CliExit(Exception):
    """Поднимается вместо sys.exit там, где вызывающему нужно доделать работу (статус, lock)."""

    def __init__(self, code, human, **extra):
        super().__init__(human)
        self.code = code
        self.human = human
        self.extra = extra


def out(obj, code=EXIT_OK):
    obj.setdefault("ok", code == EXIT_OK)
    obj.setdefault("exit_code", code)
    sys.stdout.write(json.dumps(clean(obj), ensure_ascii=False) + "\n")
    sys.stdout.flush()
    sys.exit(code)


def fail(code, human, **extra):
    obj = {"ok": False, "human": human}
    obj.update(extra)
    out(obj, code)


class JsonArgumentParser(argparse.ArgumentParser):
    """Ошибка разбора аргументов — обычный JSON с кодом 1, а не usage в stderr с кодом 2."""

    def error(self, message):
        fail(EXIT_CONFIG, "не понял команду: %s. Команды: run, status, pause, resume, init, adopt." % message)

    def exit(self, status=0, message=None):
        if status != 0:
            fail(EXIT_CONFIG, "не понял команду: %s" % ((message or "").strip() or "проверь имя команды и флаги"))
        sys.exit(0)

    def print_help(self, file=None):
        out({"human": "brain-sync: run · status · pause [--reason] · resume · init [--yes] · adopt [--yes] "
                      "[--pull-private] · флаги --dry-run --allow-mass-delete --root --transport"})


def run_cli(func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except SystemExit:
        raise
    except CliExit as ex:
        fail(ex.code, ex.human, **ex.extra)
    except KeyboardInterrupt:
        fail(EXIT_CONFIG, "прервано с клавиатуры")
    except Exception as ex:  # наружу — JSON, не трассировка
        fail(EXIT_PROVIDER, "неожиданная ошибка (%s): %s" % (type(ex).__name__, str(ex)[:200]))


def mask(value):
    if not value:
        return "(пусто)"
    value = str(value)
    if len(value) <= 4:
        return "•" * len(value)
    return "%s…%s (%d символов)" % (value[:2], value[-2:], len(value))


def mask_ip(ip):
    """Для скриншотов ученика: IP целиком не показываем никогда."""
    if not ip:
        return "(пусто)"
    if ip.count(".") == 3:
        return ip.split(".")[0] + ".x.x.x"
    return mask(ip)


# ---------- пути ----------
def config_dir():
    p = os.environ.get("BRAIN_CONFIG_DIR")
    return Path(p).expanduser() if p else Path.home() / ".config" / "brain"


def ikigai_env_path():
    p = os.environ.get("BRAIN_IKIGAI_ENV")
    return Path(p).expanduser() if p else Path.home() / ".claude" / "ikigai_env.json"


def default_skills_dir():
    return Path.home() / ".claude" / "skills"


def detect_os():
    return "windows" if IS_WINDOWS else ("mac" if IS_MAC else "linux")


def resolve_workspace(root_arg=None):
    """Рабочая папка (где CLAUDE.md и memory/): --root, иначе профиль пробника (§6): workspace_win на Windows,
    иначе workspace. Возвращает Path или поднимает CliExit(1)."""
    if root_arg:
        ws = Path(os.path.abspath(str(Path(root_arg).expanduser())))
        src = "--root"
    else:
        prof = ikigai_env_path()
        if not prof.exists():
            raise CliExit(EXIT_CONFIG, "не знаю рабочую папку: нет профиля %s. Запусти пробник ikigai-preflight "
                                       "или укажи --root <папка с CLAUDE.md>" % prof)
        try:
            data = json.loads(prof.read_text(encoding="utf-8-sig"))
        except Exception:
            raise CliExit(EXIT_CONFIG, "профиль %s не читается как JSON — перезапусти пробник" % prof)
        val = (data.get("workspace_win") if IS_WINDOWS else None) or data.get("workspace") or ""
        if not val:
            raise CliExit(EXIT_CONFIG, "в профиле нет поля workspace — укажи --root <папка с CLAUDE.md>")
        ws = Path(val).expanduser()
        src = "профиль"
    if not (ws / "memory").is_dir():
        raise CliExit(EXIT_CONFIG, "в рабочей папке (%s) нет папки memory/ — это не та папка" % src,
                      workspace=str(ws))
    return ws


# ---------- имена и зоны ----------
def nfc(s):
    return unicodedata.normalize("NFC", s)


def _match_any(name, patterns):
    low = name.lower()
    return any(fnmatch.fnmatchcase(low, p.lower()) for p in patterns)


def is_excluded_dir(name):
    return _match_any(name, EXCLUDE_DIRS)


def is_excluded_file(name):
    return _match_any(name, EXCLUDE_FILES) or name.endswith(TMP_SUFFIX)


def is_private_dir(name):
    return _match_any(name, PRIVATE_DIRS)


def excluded_reason(rel):
    """Почему путь не синкается (None — синкается). Проверяет каждую папку и имя файла."""
    parts = rel.split("/")
    for d in parts[:-1]:
        if is_excluded_dir(d):
            return "папка %s/ исключена" % d
    if is_excluded_file(parts[-1]):
        return "файл %s исключён" % parts[-1]
    if rel.startswith(INBOX_PREFIX + SYNCED_DIRNAME + "/"):
        return "inbox/.synced — служебная"
    return None


def is_safe_rel(rel):
    """Относительный путь протокола: только CLAUDE.md, memory/…, skills/…; без .., абсолютных путей, «\\», NUL."""
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


def zone_of(rel):
    """computer | inbox | dialogues | None."""
    if rel.startswith(INBOX_PREFIX):
        return "inbox"
    if rel.startswith(DIALOGUES_PREFIX):
        return "dialogues"
    if rel in ROOT_FILES or rel.startswith(ZONE_PREFIXES):
        return "computer"
    return None


_WIN_BAD = set('<>:"|?*')
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}


def windows_name_problem(rel):
    """None — путь можно создать на Windows; иначе причина. Проверяет каждую часть пути."""
    for part in PurePosixPath(rel).parts:
        if any(c in _WIN_BAD or ord(c) < 32 for c in part):
            return "в имени «%s» есть символ, запрещённый в Windows" % part
        if part.endswith(" ") or part.endswith("."):
            return "имя «%s» кончается пробелом или точкой — Windows так не умеет" % part
        if part.split(".")[0].rstrip(" ").upper() in _WIN_RESERVED:
            return "«%s» — зарезервированное имя Windows" % part
    return None


def join_rel(root, rel):
    """Склеивает корень (Path / PureWindowsPath / PurePosixPath) и путь протокола по частям — без «/» внутри строк."""
    return root.joinpath(*PurePosixPath(rel).parts)


def conflict_name(rel, kind, now=None):
    """notes.md → notes.conflict-server-20261002-1405.md (kind: server | local)."""
    stamp = time.strftime("%Y%m%d-%H%M", time.localtime(now if now is not None else time.time()))
    head, _, name = rel.rpartition("/")
    if "." in name.lstrip("."):
        dot = name.rfind(".")
        base, ext = name[:dot], name[dot:]
    else:
        base, ext = name, ""
    new = "%s.conflict-%s-%s%s" % (base, kind, stamp, ext)
    return (head + "/" + new) if head else new


# ---------- хэши и обход ----------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def scan_tree(root, prefix, follow_links=True):
    """Обходит папку зоны. Возвращает (entries, skipped):
       entries: {rel: (Path, size, mtime_ns)}; skipped: [{"rel", "reason"}] — исключённое и пропущенное.
       prefix: "memory" / "skills". Имена приводятся к NFC. Симлинки: на компьютере идём по ним (скиллы часто
       ссылки на репозиторий) с защитой от петель; на сервере (follow_links=False) пропускаем."""
    entries, skipped = {}, []
    root = Path(root)
    if not root.is_dir():
        return entries, skipped
    seen_real = set()
    for dirpath, dirnames, filenames in os.walk(str(root), followlinks=follow_links):
        try:
            real = os.path.realpath(dirpath)
        except OSError:
            real = dirpath
        if real in seen_real:
            dirnames[:] = []
            continue
        seen_real.add(real)
        reldir = os.path.relpath(dirpath, str(root))
        reldir = "" if reldir == "." else nfc(reldir.replace(os.sep, "/"))
        keep = []
        for d in sorted(dirnames):
            drel = "%s/%s%s" % (prefix, (reldir + "/") if reldir else "", nfc(d))
            if is_excluded_dir(d):
                skipped.append({"rel": drel + "/", "reason": "исключённая папка"})
            elif drel == INBOX_PREFIX + SYNCED_DIRNAME:
                continue
            elif not follow_links and os.path.islink(os.path.join(dirpath, d)):
                skipped.append({"rel": drel + "/", "reason": "симлинк пропущен"})
            else:
                keep.append(d)
        dirnames[:] = keep
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = "%s/%s%s" % (prefix, (reldir + "/") if reldir else "", nfc(fn))
            if fn.endswith(TMP_SUFFIX):
                continue
            if is_excluded_file(fn):
                skipped.append({"rel": rel, "reason": "исключённый файл"})
                continue
            if os.path.islink(full) and not follow_links:
                skipped.append({"rel": rel, "reason": "симлинк пропущен"})
                continue
            if not is_safe_rel(rel):
                skipped.append({"rel": rel, "reason": "имя не годится для синка"})
                continue
            try:
                st = os.stat(full)
            except OSError:
                continue
            if not os.path.isfile(full):
                continue
            if st.st_size > MAX_FILE_BYTES:
                skipped.append({"rel": rel, "reason": "больше 20 МБ"})
                continue
            if rel in entries:
                skipped.append({"rel": rel, "reason": "два файла с одинаковым именем в разной форме Unicode"})
                continue
            entries[rel] = (Path(full), st.st_size, st.st_mtime_ns)
    return entries, skipped


def scan_root_files(ws):
    entries, skipped = {}, []
    for name in ROOT_FILES:
        p = Path(ws) / name
        try:
            if p.is_file():
                st = p.stat()
                if st.st_size > MAX_FILE_BYTES:
                    skipped.append({"rel": name, "reason": "больше 20 МБ"})
                else:
                    entries[name] = (p, st.st_size, st.st_mtime_ns)
        except OSError:
            pass
    return entries, skipped


def hash_entries(entries, cache):
    """sha по содержимому; кэш {rel: [size, mtime_ns, sha]} экономит чтение неизменённых файлов.
    Время участвует только как ключ кэша, в решениях синка — нет."""
    result, new_cache = {}, {}
    for rel, (path, size, mtime_ns) in entries.items():
        c = cache.get(rel)
        if c and c[0] == size and c[1] == mtime_ns:
            sha = c[2]
        else:
            try:
                sha = sha256_file(path)
            except OSError:
                continue
        result[rel] = sha
        new_cache[rel] = [size, mtime_ns, sha]
    return result, new_cache


# ---------- безопасный tar ----------
class TarSafetyError(Exception):
    pass


def check_member(m, max_size=MAX_FILE_BYTES, extra_names=()):
    name = m.name
    if name in extra_names:
        if not m.isfile():
            raise TarSafetyError("служебный элемент архива — не файл")
        return name
    if not m.isfile():
        raise TarSafetyError("в архиве не обычный файл (симлинк/ссылка/устройство): %s" % name[:120])
    if name.startswith("/") or name.startswith("\\") or (len(name) > 1 and name[1] == ":"):
        raise TarSafetyError("абсолютный путь в архиве: %s" % name[:120])
    if ".." in name.replace("\\", "/").split("/"):
        raise TarSafetyError("путь с «..» в архиве: %s" % name[:120])
    if not is_safe_rel(nfc(name)):
        raise TarSafetyError("недопустимый путь в архиве: %s" % name[:120])
    if m.size > max_size:
        raise TarSafetyError("файл больше 20 МБ в архиве: %s" % name[:120])
    return nfc(name)


def iter_tar(fileobj, max_size=MAX_FILE_BYTES, extra_names=()):
    """Читает tar.gz потоком и отдаёт (имя, байты). Любой опасный элемент — TarSafetyError на весь архив."""
    try:
        with tarfile.open(fileobj=fileobj, mode="r|gz") as tf:
            for m in tf:
                if m.isdir():
                    continue
                name = check_member(m, max_size, extra_names)
                f = tf.extractfile(m)
                data = f.read(max_size + 1) if f else b""
                if len(data) > max_size:
                    raise TarSafetyError("файл больше 20 МБ в архиве: %s" % name[:120])
                yield name, data
    except tarfile.TarError as ex:
        raise TarSafetyError("архив повреждён: %s" % ex)


def write_tar(fileobj, items):
    """items: [(arcname, bytes | Path)]. Права/владельцы в архиве нейтральные — их ставит принимающая сторона."""
    with tarfile.open(fileobj=fileobj, mode="w:gz", compresslevel=6) as tf:
        for name, src in items:
            data = src if isinstance(src, (bytes, bytearray)) else Path(src).read_bytes()
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mode = 0o640
            ti.mtime = int(time.time())
            tf.addfile(ti, io.BytesIO(data))


# ---------- запись файлов ----------
def atomic_write_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + "." + str(os.getpid()) + TMP_SUFFIX)
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(str(tmp), str(path))


def atomic_write_json(path, obj):
    atomic_write_bytes(path, (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


# ---------- файл доступа ----------
ACCESS_KEYS = ("SERVER_IP", "SERVER_USER", "SERVER_PORT", "BOT_TOKEN", "USER_ID", "PASSWORD")
LEGACY_KEYS = {"IP": "SERVER_IP", "LOGIN": "SERVER_USER", "PORT": "SERVER_PORT"}
SECRET_KEYS = ("BOT_TOKEN", "PASSWORD", "CLAUDE_TOKEN")


def access_path():
    return config_dir() / "server_access"


def read_access(path=None):
    """Возвращает (access: dict, warnings: list). Старые ключи IP/LOGIN/PORT читаются с предупреждением,
    CLAUDE_TOKEN — только предупреждение (токен подписки в файл не пишется, §8)."""
    path = Path(path) if path else access_path()
    if not path.exists():
        raise CliExit(EXIT_CONFIG, "нет файла доступа %s — заполни его по образцу server_access.example" % path,
                      access_path=str(path))
    raw = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[len("export "):].strip()
        raw[k] = v.strip().strip('"').strip("'")
    access, warnings = {}, []
    for k in ACCESS_KEYS:
        if raw.get(k):
            access[k] = raw[k]
    for old, new in LEGACY_KEYS.items():
        if raw.get(old) and not access.get(new):
            access[new] = raw[old]
            warnings.append("в файле доступа старый ключ %s — переименуй в %s" % (old, new))
    if raw.get("CLAUDE_TOKEN"):
        warnings.append("в файле доступа лежит CLAUDE_TOKEN — токен подписки там не хранится, удали строку "
                        "(на сервер его передаёт brain-link put-token)")
    access.setdefault("SERVER_USER", "root")
    access.setdefault("SERVER_PORT", "22")
    return access, warnings


def access_public_view(access):
    view = {}
    for k, v in access.items():
        if k in SECRET_KEYS:
            view[k] = mask(v)
        elif k == "SERVER_IP":
            view[k] = mask_ip(v)
        else:
            view[k] = v
    return view


# ---------- ssh ----------
def sync_key_path():
    return Path.home() / ".ssh" / "brain_sync_ed25519"


def find_ssh():
    """Windows: встроенный OpenSSH. 32-битный Python на 64-битной Windows видит System32 подменённым на SysWOW64,
    где ssh.exe нет, — поэтому сначала Sysnative."""
    if IS_WINDOWS:
        sysroot = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
        for sub in ("Sysnative", "System32"):
            cand = Path(sysroot) / sub / "OpenSSH" / "ssh.exe"
            if cand.exists():
                return str(cand)
    return shutil.which("ssh")


def _ssh_opt_path(key, path):
    p = str(path)
    if " " in p:   # ssh сам режет значение -o по пробелам — путь с пробелом берём в кавычки
        p = '"%s"' % p
    return "%s=%s" % (key, p)


def ssh_command(access, remote_args, key_path=None, known_hosts=None, ssh_bin=None):
    """Собирает argv для ssh. Без shell: пробелы и кириллица в путях безопасны."""
    ssh_bin = ssh_bin or find_ssh()
    if not ssh_bin:
        raise CliExit(EXIT_CONFIG, "не найден ssh. Windows: Параметры → Приложения → Дополнительные компоненты → "
                                   "Клиент OpenSSH; Mac: ssh встроен")
    key_path = Path(key_path) if key_path else sync_key_path()
    known_hosts = Path(known_hosts) if known_hosts else config_dir() / "known_hosts"
    ip = access.get("SERVER_IP")
    if not ip:
        raise CliExit(EXIT_CONFIG, "в файле доступа нет SERVER_IP")
    cmd = [ssh_bin,
           "-o", "BatchMode=yes",
           "-o", "IdentitiesOnly=yes",
           "-o", "ConnectTimeout=15",
           "-o", "ServerAliveInterval=15",
           "-o", "ServerAliveCountMax=4",
           "-o", _ssh_opt_path("UserKnownHostsFile", known_hosts),
           "-o", "StrictHostKeyChecking=yes",
           "-o", "LogLevel=ERROR",
           "-T",
           "-i", str(key_path),
           "-p", str(access.get("SERVER_PORT") or "22"),
           "%s@%s" % (access.get("SERVER_USER") or "brain", ip)]
    return cmd + list(remote_args)


def classify_ssh_error(rc, stderr):
    """(код выхода KIT, человеческая причина)."""
    s = (stderr or "").lower()
    if "remote host identification has changed" in s or "host key verification failed" in s \
            or "no matching host key" in s or "host key for" in s:
        return EXIT_AUTH, ("ключ сервера не совпал с закреплённым в ~/.config/brain/known_hosts. Если сервер "
                           "переустанавливали — перезакрепи ключ шагом keys; если нет — не продолжай, это может быть подмена")
    if "permission denied" in s or "too many authentication failures" in s:
        return EXIT_AUTH, "сервер не пустил по ключу brain_sync_ed25519 — проверь шаг keys"
    if "could not resolve" in s or "timed out" in s or "connection refused" in s or "no route" in s \
            or "network is unreachable" in s or "connection closed" in s or "broken pipe" in s:
        return EXIT_PROVIDER, "сервер недоступен по сети — проверь интернет/VPN, синк повторится сам"
    return EXIT_PROVIDER, "ошибка связи с сервером (код %s)" % rc


def no_window_flags():
    return 0x08000000 if IS_WINDOWS else 0   # CREATE_NO_WINDOW: из pythonw не мигаем консолью


# ---------- журнал ----------
def get_logger(name="brain-sync"):
    log = logging.getLogger(name)
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    try:
        d = config_dir() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(str(d / "sync.log"), maxBytes=1024 * 1024, backupCount=2,
                                                 encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
    except OSError:
        log.addHandler(logging.NullHandler())
    return log


# ---------- уведомление на рабочий стол ----------
_PS_TOAST = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$t = [Security.SecurityElement]::Escape($env:BRAIN_NOTIFY_TITLE)
$b = [Security.SecurityElement]::Escape($env:BRAIN_NOTIFY_TEXT)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual></toast>")
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def notify(title, text):
    """Уведомление на рабочий стол. Не вышло — молча возвращает False (синк из-за этого не падает)."""
    if os.environ.get("BRAIN_NO_NOTIFY"):
        return False
    try:
        if IS_MAC:
            esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e", 'display notification "%s" with title "%s"' % (esc(text), esc(title))],
                           capture_output=True, timeout=15)
            return True
        if IS_WINDOWS:
            env = dict(os.environ, BRAIN_NOTIFY_TITLE=title, BRAIN_NOTIFY_TEXT=text)
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-Command", _PS_TOAST], capture_output=True, timeout=30, env=env,
                           creationflags=no_window_flags())
            return True
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", title, text], capture_output=True, timeout=15)
            return True
    except Exception:
        pass
    return False


def now_iso(t=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t if t is not None else time.time()))
