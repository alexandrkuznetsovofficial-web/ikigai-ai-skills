#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
brain_link.py — установщик связки «компьютер — мастерская, сервер — база» (kit 2.1, KIT_CONVENTIONS §8).

Шаги (каждый идемпотентен, только добавляет, перед правкой файла компьютера делает .bak,
без --replace ничего чужого не перезаписывает):
  detect                        ОС, ssh, python, файл доступа, состояние сервера → ветка A / B / C и следующий шаг
  keys [--fingerprint SHA256:…] [--replace]
                                ключи ed25519; ключ сервера закрепляется при первом входе (как ssh accept-new),
                                --fingerprint — необязательная сверка; свой ключ кладёт на сервер сам по PASSWORD
                                из файла доступа (SSH_ASKPASS, одна попытка); нет PASSWORD — команда для человека
  harden                        сервер: пользователь brain, swap, ufw, fail2ban, автообновления, часы, brain-admin
  claude                        Claude Code под brain официальным установщиком, проверка «API-ключа нет»
  put-token claude|bot          токен уходит на сервер со скрытого ввода, нигде не печатается
  init [--yes] / adopt [--yes]  первая выгрузка (A) / переход со старой модели (B); без --yes — только отчёт
  schedule [--replace]          launchd (Mac) / Планировщик задач (Windows) каждые 5 минут + пробный запуск
  bot [--voice] [--yes]         бот и таймеры на сервере; старый бот выключается (не удаляется) по --yes
  verify [--wait С]             9 проверок связки (+ самопроверка безопасности на живом claude), итог таблицей
  lockdown --confirm --confirm-again [--drop-password] [--accept-unverified]
                                вход только по ключам, с автооткатом; нужен PASS самопроверки
  report                        диагностика для куратора в ~/brain-link-report-ДАТА.txt (секреты замаскированы)
  status | pause [--reason] | resume                       прокси к brain_sync.py

Запуск: Mac  python3 ~/.claude/skills/brain-link/scripts/brain_link.py <шаг>
        Win  py -3 "$env:USERPROFILE\\.claude\\skills\\brain-link\\scripts\\brain_link.py" <шаг>

Вывод — ровно один JSON в stdout с полем human. Подсказки во время ожидания — в stderr.
Коды выхода: 0 ок · 1 ошибка · 2 нужно действие человека · 3 стоп-точка, ждёт подтверждения · 4 конфигурация.
Секреты (пароль, токены) не печатаются никогда. Только стандартная библиотека Python 3.9+.
"""
import argparse
import getpass
import io
import json
import os
import platform
import plistlib
import queue
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import brainlib as bl  # noqa: E402

KIT = HERE.parent
SERVER_DIR = KIT / "server"
TEMPLATES = KIT / "templates"
SYNC_PY = HERE / "brain_sync.py"

EXIT_OK, EXIT_ERR, EXIT_HUMAN, EXIT_CONFIRM, EXIT_CONFIG = 0, 1, 2, 3, 4
# коды brainlib / brain_sync → коды установщика (у brainlib 1 = конфиг, 4 = сеть)
BL_TO_LINK = {0: EXIT_OK, 1: EXIT_CONFIG, 2: EXIT_HUMAN, 3: EXIT_CONFIRM, 4: EXIT_ERR}

LABEL = "com.ikigai.brain-sync"
TASK_NAME = "Ikigai brain-sync"
BH = "/home/brain"
UPLOAD_DIR = "/root/.brain-link-upload"
KIT_COPY = BH + "/.local/share/brain-link/server"
# kit 2.1 (RT-11): бот — системный пользователь brainbot (группа brain), его состояние — /var/lib/brain-bot (0700)
BOT_USER = "brainbot"
BOT_STATE = "/var/lib/brain-bot"
# конфиг Claude Code бота (CLAUDE_CONFIG_DIR, там .claude.json и .credentials.json); в ~/.claude — только скиллы
BOT_CLAUDE_CONFIG = BOT_STATE + "/claude-config"
VERIFY_FILE = "brain_link_verify.md"
WAIT_DEFAULT = 360

CLAUDE_TOKEN_RE = re.compile(r"^sk-ant-oat[0-9A-Za-z_-]{20,}$")
BOT_TOKEN_RE = re.compile(r"^[0-9]{6,12}:[A-Za-z0-9_-]{30,}$")
PUBKEY_RE = re.compile(r"^ssh-ed25519 [A-Za-z0-9+/=]{40,} ?[A-Za-z0-9@._-]*$")
UNIT_RE = re.compile(r"^[A-Za-z0-9@._-]{1,80}\.service$")
SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")

# «старый бот» на сервере: слово bot / telegram / tg целиком в имени юнита (postgresql — не бот)
# или следы Telegram в ExecStart / WorkingDirectory / Environment. Системные сервисы не трогаем никогда.
BOT_NAME_RE = re.compile(r"(^|[-_.@])(bot|telegram|tg)([-_.@]|$)", re.I)
PROTECTED_UNIT_RE = re.compile(
    r"^(brain-.*|postgresql.*|mysql.*|mariadb.*|nginx.*|apache2.*|httpd.*|docker.*|containerd.*|ssh.*|"
    r"sshd.*|systemd-.*|cron.*|crond.*|ufw.*|fail2ban.*|dbus.*|snapd.*|unattended-upgrades.*|rsyslog.*|"
    r"getty.*|serial-getty.*|polkit.*|networkd-dispatcher.*|qemu-guest-agent.*|cloud-.*)\.service$", re.I)
SHELL_PROTECTED = ("brain-*|postgresql*|mysql*|mariadb*|nginx*|apache2*|httpd*|docker*|containerd*|ssh*|"
                   "systemd-*|cron*|crond*|ufw*|fail2ban*|dbus*|snapd*|unattended-upgrades*|rsyslog*|getty*|"
                   "serial-getty*|polkit*|networkd-dispatcher*|qemu-guest-agent*|cloud-*")


def is_protected_unit(unit):
    return bool(PROTECTED_UNIT_RE.match(unit or ""))


def looks_like_bot_unit(unit):
    """Только по имени: tg-bridge.service, my_bot.service, telegram@x.service — да; postgresql.service — нет."""
    stem = (unit or "")[:-len(".service")] if (unit or "").endswith(".service") else (unit or "")
    return bool(BOT_NAME_RE.search(stem)) and not is_protected_unit(unit)


def old_bot_units(text):
    """Строки OLD=<юнит> из OLD_SCAN → список юнитов, которые можно предложить выключить."""
    res = []
    for line in (text or "").splitlines():
        if not line.startswith("OLD="):
            continue
        for u in line[4:].split():
            if UNIT_RE.match(u) and not is_protected_unit(u) and u not in res:
                res.append(u)
    return res


# ---------- внедряемые зависимости (тесты подменяют) ----------
def default_runner(argv, input=None, timeout=120, env=None, cwd=None):
    """Запуск команды без shell. Возвращает (код, stdout bytes, stderr bytes)."""
    try:
        r = subprocess.run([str(a) for a in argv], input=input, capture_output=True, timeout=timeout,
                           env=env, cwd=cwd, creationflags=bl.no_window_flags())
    except subprocess.TimeoutExpired:
        return 124, b"", b"timeout"
    except OSError as ex:
        return 127, b"", str(ex).encode("utf-8", "replace")
    return r.returncode, r.stdout or b"", r.stderr or b""


def default_interactive(argv):
    """Команда, которую человек проходит сам (браузер, вход): stdout уводим в stderr — stdout держит JSON."""
    try:
        err = sys.stderr if sys.stderr is not None and hasattr(sys.stderr, "fileno") else None
        try:
            if err is not None:
                err.fileno()
        except (OSError, ValueError, io.UnsupportedOperation):
            err = None
        return subprocess.call([str(a) for a in argv], stdout=err if err is not None else subprocess.DEVNULL)
    except OSError:
        return 127


RUNNER = default_runner
INTERACTIVE = default_interactive
POPEN = subprocess.Popen
GETPASS = getpass.getpass
SLEEP = time.sleep


def run(argv, input=None, timeout=120, env=None, cwd=None):
    rc, o, e = RUNNER(argv, input=input, timeout=timeout, env=env, cwd=cwd)
    return rc, _dec(o), _dec(e)


def _dec(b):
    if isinstance(b, str):
        return b
    return (b or b"").decode("utf-8", "replace")


def emit(stream, text):
    """Безопасная запись текста: UTF-8 байтами в stream.buffer, без падения на cp1251/cp866 консоли Windows
    и при sys.stdout/sys.stderr = None (pythonw.exe, задача Планировщика)."""
    if stream is None:
        return
    try:
        buf = getattr(stream, "buffer", None)
        if buf is not None:
            stream.flush()
            buf.write(text.encode("utf-8", "replace"))
            buf.flush()
            return
        try:
            stream.write(text)
        except UnicodeEncodeError:
            enc = getattr(stream, "encoding", None) or "ascii"
            stream.write(text.encode(enc, "replace").decode(enc, "replace"))
        stream.flush()
    except Exception:
        pass


def utf8_stdio():
    """stdout/stderr → UTF-8 (errors=replace) до любого вывода: brainlib.out пишет JSON через sys.stdout,
    и на Windows с кодировкой консоли cp1251 «✅» иначе роняет процесс. None (pythonw) → в devnull."""
    for name in ("stdout", "stderr"):
        st = getattr(sys, name)
        if st is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except OSError:
                pass
            continue
        reconf = getattr(st, "reconfigure", None)
        if reconf is not None:
            try:
                reconf(encoding="utf-8", errors="replace")
            except (ValueError, OSError, io.UnsupportedOperation):
                pass


def child_env(extra=None):
    """Окружение для подпроцессов python (brain_sync.py): вывод строго UTF-8 на любой ОС."""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env


def say(text):
    """Подсказка человеку во время долгого шага — в stderr, stdout остаётся одним JSON."""
    emit(sys.stderr, text.rstrip() + "\n")


# ---------- выход ----------
class LinkExit(Exception):
    def __init__(self, code, human, **extra):
        super().__init__(human)
        self.code, self.human, self.extra = code, human, extra


def finish(code, human, **extra):
    obj = {"ok": code == EXIT_OK, "human": human}
    obj.update(extra)
    bl.out(obj, code)  # brainlib.out — единственная запись JSON в stdout; кодировку готовит utf8_stdio()


# ---------- окружение ----------
def os_name():
    return os.environ.get("BRAIN_LINK_OS") or bl.detect_os()


def home():
    return Path.home()


def ssh_dir():
    return home() / ".ssh"


def admin_key():
    return ssh_dir() / "id_ed25519"


def sync_key():
    return bl.sync_key_path()


def known_hosts():
    return bl.config_dir() / "known_hosts"


def cfg_dir():
    d = bl.config_dir()
    d.mkdir(parents=True, exist_ok=True)
    if os_name() != "windows":
        try:
            os.chmod(str(d), 0o700)
        except OSError:
            pass
    return d


def state_path():
    return bl.config_dir() / "link_state.json"


def load_state():
    return bl.read_json(state_path(), {})


def save_state(**kv):
    st = load_state()
    st.update(kv)
    st["updated"] = bl.now_iso()
    cfg_dir()
    bl.atomic_write_json(state_path(), st)
    return st


def legacy_access_paths():
    return [home() / ".secrets" / "brain" / "server_access.txt"]


def find_tool(name):
    """ssh, ssh-keygen, ssh-keyscan: на Windows — встроенный OpenSSH (Sysnative для 32-битного Python)."""
    if os_name() == "windows":
        sysroot = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
        for sub in ("Sysnative", "System32"):
            cand = Path(sysroot) / sub / "OpenSSH" / (name + ".exe")
            if cand.exists():
                return str(cand)
    return shutil.which(name)


def keyscan_tools():
    """ssh-keyscan по очереди. Встроенный в Windows OpenSSH 9.5 падает на Ubuntu 24.04
    («choose_kex: unsupported KEX method sntrup761x25519-sha512») — запасной из Git for Windows."""
    tools = [find_tool("ssh-keyscan")]
    if os_name() == "windows":
        roots = [Path(b) / "Git" for b in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"),
                                            r"C:\Program Files") if b]
        if os.environ.get("LOCALAPPDATA"):
            roots.append(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Git")   # Git «только для меня»
        git = shutil.which("git")
        if git:
            roots.append(Path(git).resolve().parent.parent)                       # ...\Git\cmd\git.exe → ...\Git
        for root in roots:
            cand = root / "usr" / "bin" / "ssh-keyscan.exe"
            if cand.exists():
                tools.append(str(cand))
        tools.append(shutil.which("ssh-keyscan"))
    out = []
    for t in tools:
        if t and t.lower() not in [x.lower() for x in out]:
            out.append(t)
    return out


def find_powershell():
    sysroot = os.environ.get("SystemRoot") or r"C:\Windows"
    for sub in ("Sysnative", "System32"):
        cand = Path(sysroot) / sub / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if cand.exists():
            return str(cand)
    return shutil.which("powershell") or "powershell"


def read_access():
    """Файл доступа §8. Нет нового, но есть старый путь Windows — копируем (только добавляем) и предупреждаем."""
    p = bl.access_path()
    warnings = []
    if not p.exists():
        for old in legacy_access_paths():
            if old.exists():
                cfg_dir()
                shutil.copy2(str(old), str(p))
                if os_name() != "windows":
                    os.chmod(str(p), 0o600)
                warnings.append("файл доступа был по старому пути %s — скопирован в %s; старый можно удалить" % (old, p))
                break
    try:
        access, w = bl.read_access(p)
    except bl.CliExit as ex:
        raise LinkExit(EXIT_CONFIG, ex.human, access_path=str(p),
                       next_step="заполни файл доступа по образцу server_access.example (модуль 01)")
    warnings += w
    ip = access.get("SERVER_IP", "")
    if not ip or ip.startswith("<"):
        raise LinkExit(EXIT_CONFIG, "в файле доступа не вписан SERVER_IP", access_path=str(p))
    if not re.match(r"^[0-9]{1,5}$", access.get("SERVER_PORT", "22")):
        raise LinkExit(EXIT_CONFIG, "SERVER_PORT в файле доступа — не число")
    return access, warnings


# ---------- ssh ----------
class Ctx:
    def __init__(self, args):
        self.args = args
        self._access = None
        self.warnings = []

    @property
    def access(self):
        if self._access is None:
            self._access, w = read_access()
            self.warnings += w
        return self._access

    def locked(self):
        return bool(load_state().get("lockdown"))

    def admin_user(self):
        return "brain" if self.locked() else "root"

    def root_prefix(self):
        """Префикс команды brain-admin: от root — напрямую, после lockdown — sudo от brain."""
        return "sudo -n brain-admin" if self.locked() else "/usr/local/sbin/brain-admin"

    def ssh_argv(self, remote, user=None, key=None, extra_opts=()):
        a = dict(self.access)
        a["SERVER_USER"] = user or self.admin_user()
        try:
            argv = bl.ssh_command(a, [], key_path=key or admin_key(), known_hosts=known_hosts(),
                                  ssh_bin=find_tool("ssh") or "ssh")
        except bl.CliExit as ex:
            raise LinkExit(BL_TO_LINK.get(ex.code, EXIT_ERR), ex.human)
        host = argv.pop()
        for o in extra_opts:
            argv += ["-o", o]
        return argv + [host] + list(remote)

    def ssh(self, remote, input=None, timeout=120, user=None, key=None, extra_opts=()):
        return run(self.ssh_argv(remote, user, key, extra_opts), input=input, timeout=timeout)

    def sh(self, script, timeout=300, user=None):
        """Скрипт bash на сервере через stdin (одинаково на Mac и Windows, без кавычек в argv)."""
        return self.ssh(["bash", "-s"], input=script.encode("utf-8"), timeout=timeout, user=user)


def need_ssh_ready():
    if not find_tool("ssh"):
        raise LinkExit(EXIT_CONFIG, "не найден ssh. Windows: Параметры → Приложения → Дополнительные компоненты → "
                                    "Клиент OpenSSH; Mac: ssh встроен")
    if not admin_key().exists():
        raise LinkExit(EXIT_HUMAN, "нет ключа %s — сначала шаг keys" % admin_key(), next_step="keys")
    if not known_hosts().exists():
        raise LinkExit(EXIT_HUMAN, "ключ сервера не закреплён — сначала шаг keys", next_step="keys")


def ssh_fail(rc, err, what):
    code, human = bl.classify_ssh_error(rc, err)
    return LinkExit(BL_TO_LINK.get(code, EXIT_ERR), "%s: %s" % (what, human))


def kv(text):
    res = {}
    for line in text.splitlines():
        # цифры в ключе разрешены (CRED_READ2): раньше такие ключи молча терялись и (ж) в verify не проходила
        if "=" in line and re.match(r"^[A-Z][A-Z0-9_]*=", line):
            k, v = line.split("=", 1)
            res[k] = v.strip()
    return res


def marks(text):
    """Строки ✅ / 🟡 / ❌ из вывода серверных скриптов."""
    res = {"ok": [], "warn": [], "bad": []}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("✅"):
            res["ok"].append(line[1:].strip())
        elif line.startswith("🟡"):
            res["warn"].append(line[1:].strip())
        elif line.startswith("❌"):
            res["bad"].append(line[1:].strip())
    return res


def tar_server_dir():
    buf = io.BytesIO()
    items = []
    for p in sorted(SERVER_DIR.rglob("*")):
        if p.is_symlink() or any((SERVER_DIR / q).is_symlink() for q in p.relative_to(SERVER_DIR).parents):
            continue   # симлинк в папке кита на сервер не везём: он мог бы указать куда угодно
        if p.is_file() and "__pycache__" not in p.parts and not p.name.endswith((".pyc", ".bak")):
            items.append((p.relative_to(SERVER_DIR).as_posix(), p))
    bl.write_tar(buf, items)
    return buf.getvalue()


def upload_server_dir(ctx):
    """Папка server/ кита → /root/.brain-link-upload (от root, до lockdown)."""
    cmd = "rm -rf %s && mkdir -m 700 %s && tar xzf - -C %s" % (UPLOAD_DIR, UPLOAD_DIR, UPLOAD_DIR)
    rc, o, e = ctx.ssh([cmd], input=tar_server_dir(), timeout=300, user="root")
    if rc != 0:
        if rc == 255:
            raise ssh_fail(rc, e, "не загрузил файлы кита на сервер")
        raise LinkExit(EXIT_ERR, "не распаковал файлы кита на сервере: %s" % e.strip()[-200:])


COPY_KIT_SH = r"""
if id brain >/dev/null 2>&1; then
  # Папка brain — его территория: root там ничего не создаёт и не удаляет (подложенный симлинк увёл бы
  # rm/cp/chown от root куда угодно). root только готовит копию во временной папке, остальное — от brain.
  KT=$(mktemp -d /tmp/brain-kit.XXXXXX) && cp -r __UP__/. "$KT"/ && chown -R brain:brain "$KT" && chmod 0700 "$KT" \
    && runuser -u brain -- sh -c 'umask 027; mkdir -p "$(dirname "$1")" && rm -rf "$1.new" && cp -r "$2" "$1.new" \
         && rm -rf "$1" && mv "$1.new" "$1"' sh __KIT__ "$KT" \
    && echo "✅ копия кита: __KIT__ (для brain-admin update-bot)" || echo "🟡 копия кита для brain-admin update-bot не обновилась"
  [ -n "${KT:-}" ] && rm -rf "$KT"
fi
""".replace("__KIT__", KIT_COPY).replace("__UP__", UPLOAD_DIR)


# ---------- маленькие файловые помощники ----------
def write_file_safe(path, data, replace=False):
    """created | same | replaced. Отличается и нет --replace → стоп-точка (код 3), ничего не трогаем."""
    path = Path(path)
    if path.exists():
        if path.read_bytes() == data:
            return "same"
        if not replace:
            raise LinkExit(EXIT_CONFIRM, "файл %s уже есть и отличается — не перезаписываю. Если так и задумано: "
                                         "тот же шаг с --replace (старый сохранится .bak)" % path, file=str(path))
        bak = path.with_name(path.name + ".bak." + time.strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(str(path), str(bak))
        bl.atomic_write_bytes(path, data)
        return "replaced"
    bl.atomic_write_bytes(path, data)
    return "created"


def tail_file(path, n=3000):
    try:
        with open(str(path), "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - n))
            return _dec(f.read())
    except OSError:
        return ""


# =====================================================================================
# detect
# =====================================================================================
# Функция для сервера: печатает юниты, похожие на старого Telegram-бота. running — только запущенные (detect),
# all — запущенные или включённые (bot). Имя по границам слова, иначе — следы Telegram в настройках юнита.
OLD_SCAN = r"""
old_bots() {
  if [ "$1" = running ]; then F="--state=running"; else F="--all"; fi
  systemctl list-units --type=service $F --no-legend --plain 2>/dev/null | awk '{print $1}' | while read -r u; do
    case "$u" in *.service) ;; *) continue ;; esac
    case "$u" in __PROTECTED__) continue ;; esac
    if [ "$1" != running ]; then
      st=$(systemctl is-active "$u" 2>/dev/null); en=$(systemctl is-enabled "$u" 2>/dev/null)
      [ "$st" = active ] || [ "$en" = enabled ] || continue
    fi
    if printf '%s\n' "${u%.service}" | grep -qiE '(^|[-_.@])(bot|telegram|tg)([-_.@]|$)'; then echo "$u"; continue; fi
    if systemctl show -p ExecStart -p WorkingDirectory -p Environment "$u" 2>/dev/null \
       | grep -qiE 'api\.telegram\.org|telegram|bot_token'; then echo "$u"; fi
  done
}
""".replace("__PROTECTED__", SHELL_PROTECTED)

PROBE_SH = r"""
. /etc/os-release 2>/dev/null; echo "OS=${PRETTY_NAME:-?}"
echo "WHO=$(id -un)"
echo "NOW=$(date +%s)"
echo "NTP=$(timedatectl show -p NTPSynchronized --value 2>/dev/null)"
id brain >/dev/null 2>&1 && echo BRAIN=1 || echo BRAIN=0
[ -x /home/brain/.local/bin/claude ] && echo CLAUDE=1 || echo CLAUDE=0
# RT-11b: claude бота — отдельная root-копия (ставит brain-admin update-claude) с контрольной суммой
[ -x /usr/local/lib/brain-bot/claude/bin/claude ] && [ -s /usr/local/lib/brain-bot/claude.sha256 ] && echo CLAUDE_BOT=1 || echo CLAUDE_BOT=0
[ -x /usr/local/sbin/brain-admin ] && echo HARDENED=1 || echo HARDENED=0
[ -f /etc/ssh/sshd_config.d/00-brain.conf ] && echo LOCKDOWN=1 || echo LOCKDOWN=0
[ -f /home/brain/.brain-sync/heartbeat ] && echo HEARTBEAT=1 || echo HEARTBEAT=0
echo "BOT=$(systemctl is-active brain-bot.service 2>/dev/null)"
MEM=$(find /home/brain/memory -type f 2>/dev/null | grep -v -e '/memory/inbox/' -e '/memory/dialogues/' | head -5000 | wc -l)
echo "MEMFILES=$MEM"
__OLDSCAN__
OLD=$(old_bots running | tr '\n' ' ')
echo "OLD_BOTS=$OLD"
__CAPS__
if [ "$(id -u)" = 0 ]; then
  echo "UFW=$(ufw status 2>/dev/null | head -1 | awk '{print $2}')"
  CR=$( { crontab -l -u root; crontab -l -u brain; cat /etc/cron.d/*; } 2>/dev/null | grep -vE '^[[:space:]]*#' \
        | grep -cE 'brain-hourly-snapshot|mirror')
  echo "LEGACY_CRON=$CR"
  [ -s /etc/brain-bot/credentials/claude_token ] && echo TOKEN_CLAUDE=1 || echo TOKEN_CLAUDE=0
  [ -s /etc/brain-bot/credentials/bot_token ] && echo TOKEN_BOT=1 || echo TOKEN_BOT=0
else
  echo "UFW=unknown"
  echo "LEGACY_CRON=$(crontab -l 2>/dev/null | grep -vE '^[[:space:]]*#' | grep -cE 'brain-hourly-snapshot|mirror')"
  echo TOKEN_CLAUDE=unknown
  echo TOKEN_BOT=unknown
fi
""".replace("__OLDSCAN__", OLD_SCAN)

# Возможности сервера: версия claude и флаги изоляции, systemd и его песочница, контейнер, ufw, Python.
# claude — root-копия бота (/usr/local/lib/brain-bot/claude), запускается С ПРАВАМИ brainbot и с конфигом бота
# (CLAUDE_CONFIG_DIR; пока brainbot нет — от brain, без токена), root его не запускает.
CAPS_SH = r"""
# >>> claude-flags — одна логика: здесь, в CAPS_SH установщика (brain_link.py) и в claude_capabilities() бота.
# Флаг принят, если `claude <флаг> [значение] --version` завершается с кодом 0 (оба написания
# --allowedTools/--allowed-tools). --help — только для отчёта и как запасной путь, если claude «принимает»
# даже несуществующий флаг. claude запускается С ПРАВАМИ brainbot и с конфигом бота (до шага bot — от brain),
# root его не запускает.
cl_run() { # только root-копия бота (RT-11b): ~/.local/bin/claude владельца бот и проверки не запускают
  CE="env -i HOME=/home/brain PATH=/usr/local/lib/brain-bot/claude/bin:/usr/bin:/bin LANG=C.UTF-8 DISABLE_AUTOUPDATER=1"
  if [ "$(id -u)" = 0 ] && id brainbot >/dev/null 2>&1 && [ -d /var/lib/brain-bot ]; then
    timeout 30 runuser -u brainbot -- $CE CLAUDE_CONFIG_DIR=/var/lib/brain-bot/claude-config /usr/local/lib/brain-bot/claude/bin/claude "$@"
  elif [ "$(id -u)" = 0 ]; then   # brainbot ещё нет: от brain, конфиг-черновик в его кэше (токена здесь нет)
    timeout 30 runuser -u brain -- $CE CLAUDE_CONFIG_DIR=/home/brain/.cache/brain-link-claude-probe /usr/local/lib/brain-bot/claude/bin/claude "$@"
  else timeout 30 $CE CLAUDE_CONFIG_DIR="${HOME:-/tmp}/.cache/brain-link-claude-probe" /usr/local/lib/brain-bot/claude/bin/claude "$@"; fi
}
cl_flag() { cl_run "$@" --version </dev/null >/dev/null 2>&1; }
cl_has() { # «--флаг[,--написание2]» значение|-   (- — флаг без значения)
  local n
  for n in $(printf '%s' "$1" | tr ',' ' '); do
    if [ "$CL_M" = exec ]; then
      if [ "$2" = - ]; then cl_flag "$n" && return 0; else cl_flag "$n" "$2" && return 0; fi
    elif printf '%s\n' "$CL_H" | grep -qE -- "(^|[^-[:alnum:]])$n([^-[:alnum:]]|$)"; then return 0; fi
  done
  return 1
}
cl_caps() { # печатает CAP_METHOD=exec|help|none и CAP_<ФЛАГ>=1|0
  CL_H=""; CL_M=none
  if [ -x /usr/local/lib/brain-bot/claude/bin/claude ]; then
    CL_H=$(cl_run --help </dev/null 2>/dev/null || true)
    if cl_flag --brain-link-no-such-flag; then
      [ -n "$CL_H" ] && CL_M=help        # «принимает» любой флаг — исполнение ничего не различает
    elif cl_flag; then CL_M=exec
    elif [ -n "$CL_H" ]; then CL_M=help; fi
  fi
  echo "CAP_METHOD=$CL_M"
  [ "$CL_M" = none ] && return 0
  if cl_has --tools ""; then echo CAP_TOOLS=1; else echo CAP_TOOLS=0; fi
  if cl_has --setting-sources ""; then echo CAP_SETTING_SOURCES=1; else echo CAP_SETTING_SOURCES=0; fi
  if cl_has --allowedTools,--allowed-tools Read; then echo CAP_ALLOWEDTOOLS=1; else echo CAP_ALLOWEDTOOLS=0; fi
  if cl_has --disallowedTools,--disallowed-tools Bash; then echo CAP_DISALLOWEDTOOLS=1; else echo CAP_DISALLOWEDTOOLS=0; fi
  if cl_has --no-session-persistence -; then echo CAP_NO_SESSION_PERSISTENCE=1; else echo CAP_NO_SESSION_PERSISTENCE=0; fi
  if cl_has --strict-mcp-config -; then echo CAP_STRICT_MCP_CONFIG=1; else echo CAP_STRICT_MCP_CONFIG=0; fi
}
# <<< claude-flags
if [ -x /usr/local/lib/brain-bot/claude/bin/claude ]; then
  echo "CLAUDE_VER=$(cl_run --version </dev/null 2>/dev/null | head -1)"
fi
cl_caps
echo "SYSTEMD_VER=$(systemctl --version 2>/dev/null | head -1 | awk '{print $2}')"
echo "VIRT=$(systemd-detect-virt 2>/dev/null || echo none)"
echo "CONTAINER=$(systemd-detect-virt -c 2>/dev/null || echo none)"
[ -f /sys/fs/cgroup/cgroup.controllers ] && echo CGROUP_UNIFIED=1 || echo CGROUP_UNIFIED=0
command -v ufw >/dev/null 2>&1 && echo UFW_BIN=1 || echo UFW_BIN=0
command -v systemd-run >/dev/null 2>&1 && echo SYSTEMD_RUN=1 || echo SYSTEMD_RUN=0
echo "PY_SERVER=$(python3 -c 'import platform; print(platform.python_version())' 2>/dev/null)"
if [ -f /etc/systemd/system/brain-bot.service ]; then
  echo "SEC_EXPOSURE=$(systemd-analyze security brain-bot.service --no-pager 2>/dev/null | sed -n 's/.*exposure level for brain-bot.service: *\([0-9.]*\).*/\1/p' | tail -1)"
fi
""".strip()
PROBE_SH = PROBE_SH.replace("__CAPS__", CAPS_SH)

# сколько нужно: ProtectProc/ProcSubset — systemd ≥ 247; LoadCredential — ≥ 247; пояс в OnCalendar — ≥ 235
SYSTEMD_MIN = 247
CLAUDE_FLAG_KEYS = (("CAP_TOOLS", "--tools"), ("CAP_SETTING_SOURCES", "--setting-sources"),
                    ("CAP_ALLOWEDTOOLS", "--allowedTools"), ("CAP_DISALLOWEDTOOLS", "--disallowedTools"))
CLAUDE_OPTIONAL_KEYS = (("CAP_NO_SESSION_PERSISTENCE", "--no-session-persistence"),
                        ("CAP_STRICT_MCP_CONFIG", "--strict-mcp-config"))


def server_capabilities(srv):
    """Строки CAP_*/SYSTEMD_VER/… из PROBE_SH → словарь + предупреждения человеку."""
    if not srv:
        return None, []
    warns = []
    caps = {"claude_version": srv.get("CLAUDE_VER") or None, "python": srv.get("PY_SERVER") or None,
            "virt": srv.get("VIRT") or None, "container": (srv.get("CONTAINER") or "none") != "none",
            "cgroup2": srv.get("CGROUP_UNIFIED") == "1", "ufw": srv.get("UFW_BIN") == "1",
            "systemd_run": srv.get("SYSTEMD_RUN") == "1", "security_exposure": srv.get("SEC_EXPOSURE") or None}
    # CAP_METHOD: exec — флаги проверены исполнением; help — только по --help; none — claude не ответил
    caps["claude_flags_method"] = srv.get("CAP_METHOD") or None
    flags = {}
    if caps["claude_flags_method"] != "none":
        for key, flag in CLAUDE_FLAG_KEYS + CLAUDE_OPTIONAL_KEYS:
            if key in srv:
                flags[flag] = srv.get(key) == "1"
    caps["claude_flags"] = flags
    missing = [f for key, f in CLAUDE_FLAG_KEYS if f in flags and not flags[f]]
    if missing:
        warns.append("у Claude Code на сервере нет флагов %s — бот уйдёт в безопасный режим. Обнови: "
                     "sudo brain-admin update-claude (до lockdown — шаг claude)" % ", ".join(missing))
    try:
        sv = int(re.match(r"\d+", srv.get("SYSTEMD_VER") or "").group(0))
    except (AttributeError, ValueError):
        sv = None
    caps["systemd"] = sv
    caps["protect_proc"] = bool(sv and sv >= SYSTEMD_MIN)
    caps["ip_address_deny"] = bool(caps["cgroup2"]) and not caps["container"]
    if sv and sv < SYSTEMD_MIN:
        warns.append("systemd %d старше %d: ProtectProc/LoadCredential могут не работать — нужен Ubuntu 22.04+"
                     % (sv, SYSTEMD_MIN))
    if caps["container"]:
        warns.append("сервер — контейнер (%s): ufw и IPAddressDeny могут не работать; закрой порты в панели "
                     "провайдера, защиту от SSRF проверит самопроверка" % (srv.get("CONTAINER")))
    elif not caps["cgroup2"] and srv.get("CGROUP_UNIFIED") is not None:
        warns.append("нет cgroup v2: IPAddressDeny (защита от SSRF) молча не работает")
    return caps, warns


def local_capabilities():
    """Компьютер: Python, ОС, кодировка вывода; на Windows — PowerShell 5.1 / 7 и кодовая страница консоли."""
    import locale
    caps = {"os": os_name(), "python": platform.python_version(),
            "stdout_encoding": getattr(sys.stdout, "encoding", None),
            "preferred_encoding": locale.getpreferredencoding(False)}
    if os_name() == "windows":
        try:
            import ctypes
            caps["console_cp"] = ctypes.windll.kernel32.GetConsoleOutputCP()
        except Exception:
            caps["console_cp"] = None
        rc, o, _ = run([find_powershell(), "-NoProfile", "-NonInteractive", "-Command",
                        "$PSVersionTable.PSVersion.ToString()"], timeout=30)
        caps["powershell"] = o.strip() if rc == 0 else None
        pwsh = shutil.which("pwsh")
        if pwsh:
            rc, o, _ = run([pwsh, "-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.ToString()"],
                           timeout=30)
            caps["pwsh"] = o.strip() if rc == 0 else None
        else:
            caps["pwsh"] = None
    return caps


def local_schedule_present():
    if os_name() == "mac":
        return (home() / "Library" / "LaunchAgents" / (LABEL + ".plist")).exists()
    if os_name() == "windows":
        rc, _, _ = run(["schtasks", "/Query", "/TN", TASK_NAME], timeout=30)
        return rc == 0
    return False


def local_legacy_mirrors():
    """Старое ночное зеркало «истина на сервере» на компьютере: launchd *mirror* / задача *mirror*."""
    found = []
    if os_name() == "mac":
        d = home() / "Library" / "LaunchAgents"
        if d.is_dir():
            for p in sorted(d.glob("*.plist")):
                if "mirror" in p.name.lower() and p.name != LABEL + ".plist":
                    found.append({"kind": "launchd", "path": str(p), "label": p.name[:-len(".plist")]})
    elif os_name() == "windows":
        rc, o, _ = run(["schtasks", "/Query", "/FO", "CSV", "/NH"], timeout=60)
        if rc == 0:
            seen = set()
            for line in o.splitlines():
                name = line.split('","')[0].strip().strip('"')
                if "mirror" in name.lower() and name not in seen:
                    seen.add(name)
                    found.append({"kind": "task", "name": name.lstrip("\\")})
    return found


def probe_server(ctx):
    """Одна ssh-команда → словарь состояния. Пробуем пользователя по состоянию, затем второго."""
    users = [ctx.admin_user()] + [u for u in ("root", "brain") if u != ctx.admin_user()]
    last = None
    for u in users:
        t0 = time.time()
        rc, o, e = ctx.sh(PROBE_SH, timeout=60, user=u)
        t1 = time.time()
        if rc == 0 and "WHO=" in o:
            info = kv(o)
            try:
                info["CLOCK_SKEW"] = round(float(info.get("NOW")) - (t0 + t1) / 2.0, 1)
            except (TypeError, ValueError):
                info["CLOCK_SKEW"] = None
            info["LOGIN_USER"] = u
            return info, None
        last = (rc, e)
    rc, e = last
    code, human = bl.classify_ssh_error(rc, e)
    return None, human


def server_changed(st_sync, access):
    """Синк уже включён, но с другим сервером (host:port:user из sync_state.json ≠ файл доступа)?
    Возвращает «было → стало» с замаскированными IP или пустую строку."""
    target = str(st_sync.get("target") or "")
    if not st_sync.get("initialized") or not target.startswith("ssh:"):
        return ""
    m = re.match(r"^ssh:([^@]*)@(.*):([0-9]+)$", target)
    if not m:
        return ""
    old = (m.group(1), m.group(2), m.group(3))
    new = (access.get("SERVER_USER") or "root", access.get("SERVER_IP") or "", access.get("SERVER_PORT") or "22")
    if old == new:
        return ""
    return "%s@%s:%s → %s@%s:%s" % (old[0], bl.mask_ip(old[1]), old[2], new[0], bl.mask_ip(new[1]), new[2])


def cmd_detect(ctx):
    a = ctx.args
    res = {"step": "detect", "os": os_name(), "python": platform.python_version(),
           "python_ok": sys.version_info >= (3, 9)}
    ssh_bin, keygen = find_tool("ssh"), find_tool("ssh-keygen")
    res.update(ssh=bool(ssh_bin), ssh_keygen=bool(keygen))
    if not res["python_ok"]:
        raise LinkExit(EXIT_CONFIG, "нужен Python 3.9 или новее, сейчас %s" % res["python"], **res)
    access = ctx.access  # нет файла доступа → код 4
    res["access"] = bl.access_public_view(access)
    res["keys"] = {"admin_key": admin_key().exists(), "sync_key": sync_key().exists(),
                   "known_hosts": known_hosts().exists()}
    st_sync = bl.read_json(bl.config_dir() / "sync_state.json", {})
    changed = server_changed(st_sync, access)
    res["server_changed"] = bool(changed)
    if changed:
        ctx.warnings.append("сменился сервер (было → в файле доступа): %s. Если сервер переехал — "
                            "дальше шаги до init (связка с новым сервером начнётся заново). Если это ВТОРОЙ "
                            "компьютер на тот же сервер — стоп: два компьютера на один сервер не "
                            "поддерживаются, init не запускай" % changed)
    res["local"] = {"sync_initialized": bool(st_sync.get("initialized")) and not changed,
                    "schedule": local_schedule_present(),
                    "legacy_mirrors": local_legacy_mirrors(), "lockdown": ctx.locked(),
                    "verify_green": bool(load_state().get("verify_green"))}
    if not ssh_bin or not keygen:
        raise LinkExit(EXIT_CONFIG, "не найден ssh или ssh-keygen. Windows: Параметры → Приложения → "
                                    "Дополнительные компоненты → Клиент OpenSSH", warnings=ctx.warnings, **res)
    srv, why = None, None
    if res["keys"]["admin_key"] and res["keys"]["known_hosts"]:
        srv, why = probe_server(ctx)
    else:
        why = "ключи ещё не созданы или ключ сервера не закреплён"
    res["ssh_ok"] = srv is not None
    if srv and srv.get("OLD_BOTS"):
        srv["OLD_BOTS"] = " ".join(old_bot_units("OLD=" + srv["OLD_BOTS"]))
    res["server"] = srv
    scaps, swarn = server_capabilities(srv)
    res["capabilities"] = {"local": local_capabilities(), "server": scaps}
    ctx.warnings += swarn
    if srv:
        skew = srv.get("CLOCK_SKEW")
        if skew is not None and abs(skew) > 60:
            ctx.warnings.append("часы сервера и компьютера расходятся на %d с" % int(skew))
        if srv.get("NTP") not in ("yes", ""):
            ctx.warnings.append("на сервере не синхронизированы часы (NTPSynchronized=%s)" % srv.get("NTP"))
    # ветка
    if changed:
        branch = "D"
    elif srv and (srv.get("HEARTBEAT") == "1") or res["local"]["sync_initialized"]:
        branch = "C"
    elif srv and (int(srv.get("MEMFILES") or 0) > 0 or int(srv.get("LEGACY_CRON") or 0) > 0
                  or srv.get("OLD_BOTS")) or res["local"]["legacy_mirrors"]:
        branch = "B"
    elif srv:
        branch = "A"
    else:
        branch = "?"
    res["branch"] = branch
    # следующий шаг
    if not srv:
        nxt = "keys"
    elif srv.get("HARDENED") != "1":
        nxt = "harden"
    elif srv.get("CLAUDE") != "1" or srv.get("CLAUDE_BOT") == "0":
        nxt = "claude"
    elif srv.get("TOKEN_CLAUDE") == "0":
        nxt = "put-token claude"
    elif srv.get("TOKEN_BOT") == "0":
        nxt = "put-token bot"
    elif not res["local"]["sync_initialized"]:
        nxt = "adopt" if branch == "B" else "init"   # ветка D (сменился сервер) → init
    elif not res["local"]["schedule"]:
        nxt = "schedule"
    elif srv.get("BOT") != "active":
        nxt = "bot"
    elif not res["local"]["verify_green"]:
        nxt = "verify"
    elif srv.get("LOCKDOWN") != "1":
        nxt = "lockdown"
    else:
        nxt = "status"
    res["next_step"] = nxt
    names = {"A": "A — чистый сервер", "B": "B — сервер по старой модели «истина на сервере»",
             "C": "C — связка уже стоит", "D": "D — сменился сервер (связка была с другим)",
             "?": "ещё не знаю (нет входа по ключу)"}
    human = "ветка %s · следующий шаг: %s" % (names[branch], nxt)
    if not srv:
        human += " (%s)" % why
    if ctx.warnings:
        human += " · предупреждений: %d" % len(ctx.warnings)
    finish(EXIT_OK, human, warnings=ctx.warnings, **res)


# =====================================================================================
# keys
# =====================================================================================
def ensure_keypair(path, comment, created):
    keygen = find_tool("ssh-keygen")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os_name() != "windows":
        try:
            os.chmod(str(path.parent), 0o700)
        except OSError:
            pass
    if not path.exists():
        rc, o, e = run([keygen, "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(path)], timeout=60)
        if rc != 0 or not path.exists():
            raise LinkExit(EXIT_ERR, "ssh-keygen не создал ключ %s: %s" % (path, e.strip()[-200:]))
        created.append(str(path))
    pub = Path(str(path) + ".pub")
    if not pub.exists():
        rc, o, e = run([keygen, "-y", "-f", str(path)], timeout=30)
        if rc != 0:
            raise LinkExit(EXIT_HUMAN, "у ключа %s нет .pub, и восстановить не вышло (ключ с пароль-фразой?). "
                                       "Восстанови сама: ssh-keygen -y -f %s > %s.pub" % (path, path, path))
        pub.write_text(o.strip() + "\n", encoding="utf-8")
    return pub.read_text(encoding="utf-8").strip()


def _hostkey_set(text):
    s = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and not line.startswith("#"):
            s.add((parts[1], parts[2]))
    return s


FP_RE = re.compile(r"SHA256:[A-Za-z0-9+/]{20,}={0,2}")
VNC_FP_CMD = "ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub"


def fingerprints_of(path):
    """[(«SHA256:…», тип)] для файла known_hosts / .pub."""
    rc, o, e = run([find_tool("ssh-keygen"), "-l", "-E", "sha256", "-f", str(path)], timeout=30)
    return [(f, t) for f, t in re.findall(r"(SHA256:[A-Za-z0-9+/=]+)\s.*\((\w+)\)", o)]


def fingerprint():
    return ["%s (%s)" % (f, t) for f, t in fingerprints_of(known_hosts())]


def scanned_fingerprints(lines):
    """Отпечаток каждой строки ssh-keyscan отдельно: при --fingerprint закрепим ровно совпавшие ключи."""
    tmp = cfg_dir() / "known_hosts.scan"
    res = []
    try:
        for line in lines:
            bl.atomic_write_bytes(tmp, (line + "\n").encode("utf-8"))
            fps = fingerprints_of(tmp)
            res.append((line, fps[0][0] if fps else "", fps[0][1] if fps else "?"))
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return res


def norm_fp(text):
    """Из вставленного «256 SHA256:abc… root@host (ED25519)» достаём «SHA256:abc…» (без «=» на конце)."""
    m = FP_RE.search(text or "")
    return m.group(0).rstrip("=") if m else ""


def copy_id_command(access):
    port, ip = access.get("SERVER_PORT", "22"), access["SERVER_IP"]
    if os_name() == "windows":
        # путь в кавычках: в имени пользователя Windows бывают пробелы и кириллица
        return ('type "$env:USERPROFILE\\.ssh\\id_ed25519.pub" | ssh -p %s root@%s '
                '"mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys"' % (port, ip))
    return "ssh-copy-id -i ~/.ssh/id_ed25519.pub -p %s root@%s" % (port, ip)


def cmd_keys(ctx):
    a = ctx.args
    access = ctx.access
    if not find_tool("ssh-keygen") or not find_tool("ssh-keyscan") or not find_tool("ssh"):
        raise LinkExit(EXIT_CONFIG, "не найдены ssh / ssh-keygen / ssh-keyscan — Windows: Клиент OpenSSH "
                                    "(Параметры → Приложения → Дополнительные компоненты)")
    created = []
    ensure_keypair(admin_key(), "brain-link-admin", created)
    ensure_keypair(sync_key(), "brain-sync", created)
    # ключ сервера: ssh-keyscan → (необязательная сверка --fingerprint) → ~/.config/brain/known_hosts
    cfg_dir()
    ip, port = access["SERVER_IP"], access.get("SERVER_PORT", "22")
    lines, errs = [], []
    tools = keyscan_tools()
    for scan in tools:
        for extra in (["-t", "ed25519"], []):
            rc, o, e = run([scan, "-T", "10", "-p", port] + extra + [ip], timeout=40)
            lines = [l.strip() for l in o.splitlines() if l.strip() and not l.startswith("#")]
            if lines:
                break
            if e and e.strip():
                errs.append(e.strip().splitlines()[-1][:200])
        if lines:
            break
    if not lines:
        git_tried = os_name() == "windows" and len(tools) > 1      # запасной ssh-keyscan из Git уже пробовали
        if any("unsupported KEX" in x for x in errs) and not git_tried:
            raise LinkExit(EXIT_ERR, "встроенный ssh-keyscan Windows не договорился с сервером (%s). Поставь Git for "
                                     "Windows (git-scm.com) и запусти keys снова — возьму ssh-keyscan из Git" % errs[-1])
        raise LinkExit(EXIT_ERR, "сервер не отдал свой ключ (ssh-keyscan) — проверь SERVER_IP, SERVER_PORT, "
                                 "интернет/VPN и что сервер включён" + (" [%s]" % errs[-1] if errs else ""))
    scanned = scanned_fingerprints(lines)
    seen_fps = ["%s (%s)" % (f, t) for _, f, t in scanned if f]
    if not seen_fps:
        raise LinkExit(EXIT_ERR, "не смог посчитать отпечаток ключа сервера (ssh-keygen -l)")
    res = {"step": "keys", "created_keys": created, "fingerprints": seen_fps}
    st = load_state()
    same_as_pinned = False
    if known_hosts().exists():
        old = known_hosts().read_text(encoding="utf-8", errors="replace")
        same_as_pinned = bool(_hostkey_set("\n".join(lines)) & _hostkey_set(old))
        if not same_as_pinned and not a.replace:
            raise LinkExit(EXIT_HUMAN, "ключ сервера НЕ совпал с закреплённым. Если сервер переустанавливали — "
                                       "keys --replace (только с «да» человека). Если нет — не продолжай: это "
                                       "может быть подмена", next_step="keys --replace", **res)
    # отказ по умолчанию: ключ сервера считается НЕ сверенным, если так записано, или если known_hosts есть, а
    # состояние потеряно/испорчено (нет host_key_confirmed) или его отпечатки не совпадают с known_hosts
    unverified = bool(st.get("host_key_unverified"))
    if known_hosts().exists():
        if not st.get("host_key_confirmed"):
            unverified = True
        elif st.get("host_fingerprints") and sorted(fingerprint()) != sorted(st.get("host_fingerprints") or []):
            unverified = True
    given = norm_fp(getattr(a, "fingerprint", None))
    if same_as_pinned and st.get("host_key_confirmed") and not given:
        pinned = "kept"
    else:
        # по умолчанию — доверие при первом входе (как ssh accept-new): ключ, отданный сервером, закрепляется сразу.
        # Отпечаток из письма хостера / VNC (--fingerprint) — необязательная сверка; дан — обязан совпасть.
        # Смена уже закреплённого ключа без --replace остаётся стоп-точкой выше.
        if given:
            match = [l for l, f, _ in scanned if f and f.rstrip("=") == given]
            if not match:
                raise LinkExit(EXIT_ERR, "отпечаток (%s) НЕ совпал с тем, что отдаёт сервер по сети (%s). Ключ не "
                                         "закреплён. Проверь, что строка скопирована целиком; если всё верно — это "
                                         "может быть подмена, дальше не идём" % (given, ", ".join(seen_fps)), **res)
            res["host_key_check"] = "fingerprint"
            unverified = False                                   # сверка совпала — снимает флаг
        else:
            match = lines
            res["host_key_check"] = "first_use"
        data = ("\n".join(match) + "\n").encode("utf-8")
        if known_hosts().exists():
            if not same_as_pinned:
                res["old_fingerprints"] = fingerprint()             # было → стало, чтобы человеку было с чем сравнить
            write_file_safe(known_hosts(), data, replace=True)
            pinned = "confirmed" if same_as_pinned else "replaced"
            if pinned == "replaced" and not given:
                unverified = True       # сменённый ключ без сверки: пароль не шлём, пока не совпадёт --fingerprint
        else:
            bl.atomic_write_bytes(known_hosts(), data)
            pinned = "created"
    fps = fingerprint()
    # host_key_unverified — постоянный флаг: держится между запусками, снимает только совпавший --fingerprint
    old_fps = (res.get("old_fingerprints") or st.get("host_key_old_fingerprints") or []) if unverified else []
    save_state(host_fingerprints=fps, host_key_confirmed=not unverified, host_key_unverified=unverified,
               host_key_old_fingerprints=old_fps)
    res.update(host_key=pinned, fingerprints=fps)
    if unverified:
        res["host_key_unverified"] = True
    # вход по ключу работает?
    user = ctx.admin_user()
    rc, o, e = ctx.ssh(["true"], timeout=40, user=user)
    if rc == 0:
        finish(EXIT_OK, "вход по ключу работает (%s), ключ сервера закреплён: %s%s"
               % (user, ", ".join(fps) or "?", UNVERIFIED_NOTE if unverified else ""), warnings=ctx.warnings, **res)
    if not ctx.locked() and access.get("PASSWORD"):
        if unverified:
            # ключ сервера сменился (--replace) и не сверен — пароль на такой сервер не отправляем, в т.ч. в
            # следующих запусках keys, пока совпавший --fingerprint не снимет флаг host_key_unverified
            res["command"] = copy_id_command(access)
            res["key_install"] = "host_key_replaced"
            finish(EXIT_HUMAN, "ключ сервера сменился или не сверен (состояние связки не подтверждает его) — пароль не "
                               "отправляю, пока не сверим отпечаток ED25519 (SHA256:…) из письма хостера "
                               "(keys --fingerprint SHA256:…). Отпечатки: было %s, стало %s. Если сверять не с чем — "
                               "запасной путь: команда из поля command в своём терминале (пароль root вводишь ты). "
                               "%s" % (", ".join(res.get("old_fingerprints") or st.get("host_key_old_fingerprints") or [])
                                       or "?", ", ".join(fps) or "?", PW_MANAGER_NOTE),
                   warnings=ctx.warnings, next_step="keys --fingerprint", **res)
        say(PW_MANAGER_NOTE)                         # напоминание ДО отправки пароля
        push_key_by_password(ctx, res)               # кладёт ключ сам или выходит с понятным human
        rc, o, e = ctx.ssh(["true"], timeout=40, user=user)
        if rc == 0:
            dropped = False
            try:
                dropped = drop_password_line(backup=False)
            except OSError as ex:
                ctx.warnings.append("строку PASSWORD из файла доступа убрать не вышло (%s) — удали её в блокноте"
                                    % type(ex).__name__)
            finish(EXIT_OK, "ключ положен на сервер по паролю из файла доступа, вход по ключу работает (%s); ключ "
                            "сервера закреплён: %s.%s" % (user, ", ".join(fps) or "?",
                                                          " Пароль root больше не в файле доступа — храни его в "
                                                          "менеджере паролей" if dropped else ""),
                   warnings=ctx.warnings, key_installed="password", password_line_removed=dropped, **res)
        raise ssh_fail(rc, _scrub(e, access.get("PASSWORD")), "ключ положен, но вход по ключу не прошёл")
    res["command"] = copy_id_command(access)
    finish(EXIT_HUMAN, "ключ сервера закреплён, осталось положить твой ключ на сервер. Проще всего — впиши пароль "
                       "root в файл доступа (строка PASSWORD) — тогда я сделаю это сам, просто запусти keys снова. "
                       + PW_MANAGER_NOTE + " "
                       "Или выполни команду из поля command сама в своём терминале — она спросит «yes/no» (ответь "
                       "yes: отпечаток тот же, %s) и пароль root (вводишь ты, в чат не пиши). Ключ создан без "
                       "пароль-фразы; хочешь фразу — ssh-keygen -p -f ~/.ssh/id_ed25519 (на Mac затем ssh-add "
                       "--apple-use-keychain)" % (", ".join(fps) or "?"), warnings=ctx.warnings, next_step="keys", **res)


# ---------- keys: ключ на сервер по паролю из файла доступа (SSH_ASKPASS) ----------
UNVERIFIED_NOTE = (". Ключ сервера не сверен: сверь отпечаток ED25519 из письма хостера — keys --fingerprint "
                   "SHA256:…")
PW_MANAGER_NOTE = ("Важно: пароль root должен лежать в твоём менеджере паролей — положив ключ, я удалю его из файла "
                   "доступа; без менеджера паролей вернуть его можно будет только сбросом в панели хостера.")
ASKPASS_SUB = "_askpass"
ASKPASS_PREFIX = "brain-askpass-"
ASKPASS_NONCE_ENV = "BRAIN_ASKPASS_NONCE"
ASKPASS_ACCESS_ENV = "BRAIN_ASKPASS_ACCESS"
# идемпотентно: ключ дописывается, только если такой строки ещё нет; файл без \n в конце — сначала перевод строки
# (как ssh-copy-id), иначе ключ склеится с последней строкой. POSIX sh.
PUSH_KEY_REMOTE = ('umask 077; mkdir -p "$HOME/.ssh" && f="$HOME/.ssh/authorized_keys" && touch "$f" && k=$(cat) && '
                   '{ grep -qxF "$k" "$f" || { if [ -s "$f" ] && [ -n "$(tail -c1 "$f")" ]; then echo >> "$f"; fi; '
                   'printf \'%s\\n\' "$k" >> "$f"; }; }')
PW_PROMPT_RE = re.compile(r"(?i)password|пароль")


def _sha256_hex(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _askpass_dir_ok(d):
    """Папка помощника — только наша: прямо в tempfile.gettempdir() и с префиксом brain-askpass-."""
    try:
        rd = d.resolve()
        base = Path(tempfile.gettempdir()).resolve()
    except OSError:
        return False
    return rd.is_dir() and rd.parent == base and rd.name.startswith(ASKPASS_PREFIX)


def askpass_main(argv):
    """Внутренняя подкоманда для ssh (SSH_ASKPASS), человек и Claude её не вызывают.
    Печатает PASSWORD из файла доступа в stdout, только если ВСЁ сразу:
      • нонс из окружения ssh (BRAIN_ASKPASS_NONCE) совпал с sha256 в <папка>/.nonce (hmac.compare_digest);
      • папка — brain-askpass-* прямо во временной папке системы;
      • на Mac/Linux подсказка ssh непустая и спрашивает пароль (на Windows подсказку в .cmd не передаём);
      • метка <папка>/.used создаётся впервые (одна попытка за запуск keys — fail2ban).
    Иначе код 1 и пустой вывод. Пароль не идёт ни в argv, ни в окружение."""
    import hmac
    if not argv:
        return 1
    d = Path(argv[0])
    prompt = " ".join(argv[1:]).strip()
    nonce = os.environ.get(ASKPASS_NONCE_ENV) or ""
    if not nonce or not _askpass_dir_ok(d):
        return 1
    if os_name() != "windows" and not (prompt and PW_PROMPT_RE.search(prompt)):
        return 1
    try:
        want = (d / ".nonce").read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return 1
    if not want or not hmac.compare_digest(_sha256_hex(nonce), want):
        return 1
    try:
        fd = os.open(str(d / ".used"), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except OSError:
        return 1
    try:
        src = os.environ.get(ASKPASS_ACCESS_ENV)
        access, _ = bl.read_access(Path(src) if src else bl.access_path())
    except Exception:
        return 1
    pw = access.get("PASSWORD") or ""
    if not pw:
        return 1
    emit(sys.stdout, pw + "\n")
    return 0


def make_askpass(tmpdir):
    """Помощник для SSH_ASKPASS в папке tmpdir: запускает этот же python с подкомандой _askpass.
    Пароля в файле нет. Возвращает (путь помощника, доп. окружение — только пути)."""
    py, script = sys.executable or "python3", str(Path(__file__).resolve())
    if os_name() == "windows":
        # cmd.exe читает .cmd в OEM-кодировке (cp866), а в пути бывает кириллица и пробелы («C:\\Users\\Анна Ли»).
        # Пути — через переменные окружения (Unicode), в файле только ASCII, всё в кавычках.
        # Подсказку сервера (%*) в cmd не передаём вовсе: её текст мог бы содержать метасимволы cmd.
        helper = Path(tmpdir) / "askpass.cmd"
        helper.write_bytes(b'@echo off\r\n"%BRAIN_ASKPASS_PY%" "%BRAIN_ASKPASS_SCRIPT%" ' + ASKPASS_SUB.encode()
                           + b' "%BRAIN_ASKPASS_DIR%"\r\n')
        return helper, {"BRAIN_ASKPASS_PY": py, "BRAIN_ASKPASS_SCRIPT": script, "BRAIN_ASKPASS_DIR": str(tmpdir)}
    helper = Path(tmpdir) / "askpass.sh"
    helper.write_text("#!/bin/sh\nexec %s %s %s %s \"$@\"\n" % (shlex.quote(py), shlex.quote(script), ASKPASS_SUB,
                                                             shlex.quote(str(tmpdir))), encoding="utf-8")
    os.chmod(str(helper), 0o700)
    return helper, {}


def run_askpass_ssh(argv, input_bytes=None, access_path=None, timeout=60):
    """Запускает ssh (argv) так, что пароль root ssh получает из строки PASSWORD файла доступа через SSH_ASKPASS.
    Общая для keys и лаборатории CI. Делает: папку brain-askpass-* (mkdtemp, 0700) → одноразовый нонс
    (secrets.token_urlsafe(32); ssh получает его только в окружении BRAIN_ASKPASS_NONCE, в папке — его sha256 в
    .nonce, 0600) → помощник → окружение (SSH_ASKPASS, SSH_ASKPASS_REQUIRE=force, DISPLAY=:0 если не задан) →
    run(argv, input=input_bytes). Метку .used смотрит до удаления папки; папка удаляется в finally.
    access_path — другой файл доступа (по умолчанию ~/.config/brain/server_access).
    Возвращает dict: rc (int), stdout (str), stderr (str, значение пароля заменено на •••), askpass_called (bool).
    argv собирает вызывающий (см. push_key_argv): нужен BatchMode=no (по умолчанию) — BatchMode=yes выключает askpass."""
    import secrets
    tmp = tempfile.mkdtemp(prefix=ASKPASS_PREFIX, dir=tempfile.gettempdir())
    called = False
    try:
        nonce = secrets.token_urlsafe(32)
        fd = os.open(os.path.join(tmp, ".nonce"), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(_sha256_hex(nonce))
        helper, extra = make_askpass(tmp)
        env = dict(os.environ)
        env.update(extra)
        env.update({"SSH_ASKPASS": str(helper), "SSH_ASKPASS_REQUIRE": "force", ASKPASS_NONCE_ENV: nonce})
        if access_path:
            env[ASKPASS_ACCESS_ENV] = str(access_path)
        else:
            env.pop(ASKPASS_ACCESS_ENV, None)
        env.setdefault("DISPLAY", ":0")                         # старый OpenSSH зовёт askpass только при DISPLAY
        rc, o, e = run(argv, input=input_bytes, timeout=timeout, env=env)
        called = os.path.exists(os.path.join(tmp, ".used"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    try:
        secret = bl.read_access(Path(access_path) if access_path else bl.access_path())[0].get("PASSWORD") or ""
    except Exception:
        secret = ""
    return {"rc": rc, "stdout": _scrub(o, secret), "stderr": _scrub(e, secret), "askpass_called": called}


def push_key_argv(access):
    return [find_tool("ssh") or "ssh", "-F", "none", "-T",
            "-o", bl._ssh_opt_path("UserKnownHostsFile", known_hosts()),
            "-o", "StrictHostKeyChecking=yes",
            "-o", "PubkeyAuthentication=no",
            "-o", "PreferredAuthentications=password",
            "-o", "NumberOfPasswordPrompts=1",
            "-o", "ConnectTimeout=15",
            "-o", "LogLevel=ERROR",
            "-p", str(access.get("SERVER_PORT") or "22"),
            "root@%s" % access["SERVER_IP"], PUSH_KEY_REMOTE]


def push_key_by_password(ctx, res):
    """Кладёт ~/.ssh/id_ed25519.pub в /root/.ssh/authorized_keys по паролю root из файла доступа. Одна попытка.
    Пароль: файл доступа → помощник SSH_ASKPASS → ssh. Не попадает в argv, окружение, вывод, JSON и журнал."""
    access = ctx.access
    pub = Path(str(admin_key()) + ".pub").read_bytes()
    say("кладу твой ключ на сервер по паролю root из файла доступа (одна попытка)…")
    r = run_askpass_ssh(push_key_argv(access), input_bytes=pub, timeout=60)
    if r["rc"] == 0:
        return
    e = r["stderr"]
    last = (e.strip().splitlines() or ["код %s" % r["rc"]])[-1][:200]
    code, human = bl.classify_ssh_error(r["rc"], e)
    if "ключ сервера" in human or "по сети" in human:      # подмена ключа / нет сети — не обходим командой
        raise LinkExit(EXIT_ERR, "сам положить ключ не вышло: %s [%s]" % (human, last), **res)
    methods = re.findall(r"Permission denied \(([^)]*)\)", e)
    if methods and not any("password" in m.split(",") for m in methods):
        res["command"] = copy_id_command(access)
        res["key_install"] = "password_auth_disabled"
        raise LinkExit(EXIT_HUMAN, "сервер не принимает вход по паролю (разрешено только: %s). Запасной путь: "
                                   "выполни команду из поля command сама в своём терминале (пароль root вводишь ты), "
                                   "потом keys снова. Не получилось — brain_link.py report и к куратору: ключ тогда "
                                   "кладут через панель хостера"
                       % methods[-1], next_step="keys", **res)
    if not r["askpass_called"]:
        # помощник не запускался (сборка ssh его не приняла) — что бы ни писал ssh, пароль не проверялся
        res["command"] = copy_id_command(access)
        res["key_install"] = "askpass_failed"
        raise LinkExit(EXIT_HUMAN, "сам положить ключ по паролю не вышло: ssh не запустил помощник пароля (%s). "
                                   "Запасной путь: выполни команду из поля command сама в своём терминале — она "
                                   "спросит пароль root (вводишь ты, в чат не пиши), потом запусти keys снова" % last,
                       next_step="keys", **res)
    if methods or "permission denied" in e.lower() or "too many authentication failures" in e.lower():
        raise LinkExit(EXIT_HUMAN, "пароль root в файле доступа не подошёл — открой файл доступа в блокноте, проверь "
                                   "строку PASSWORD (без пробелов и кавычек по краям, целиком из письма хостера) и "
                                   "запусти keys снова. Повторять сразу много раз не надо: после нескольких неудач "
                                   "сервер (fail2ban) закрывает вход на час", next_step="keys",
                       key_install="password_rejected", **res)
    res["command"] = copy_id_command(access)
    res["key_install"] = "push_failed"
    raise LinkExit(EXIT_HUMAN, "пароль ушёл, но положить ключ не вышло (%s). Запасной путь: команда из поля command "
                               "в своём терминале, потом keys снова; повторится — report куратору" % last,
                   next_step="keys", **res)


# =====================================================================================
# harden
# =====================================================================================
HARDEN_SH = r"""
set -u
cd __UP__ || { echo "❌ нет __UP__"; exit 1; }
ADMIN_PUBKEY=__ADMIN__ SYNC_PUBKEY=__SYNC__ SERVER_PORT=__PORT__ OWNER_ID=__OWNER__ BOT_TZ=__TZ__ bash ./harden.sh
rc=$?
__COPY__
exit $rc
"""


def read_pub(path):
    p = Path(str(path) + ".pub")
    if not p.exists():
        raise LinkExit(EXIT_HUMAN, "нет %s — сначала шаг keys" % p, next_step="keys")
    key = " ".join(p.read_text(encoding="utf-8").split()[:3])
    if not PUBKEY_RE.match(key):
        raise LinkExit(EXIT_CONFIG, "%s — не ключ ssh-ed25519" % p)
    return key


def owner_id(access):
    uid = (access.get("USER_ID") or "").strip()
    if not re.match(r"^[0-9]{3,15}$", uid):
        raise LinkExit(EXIT_CONFIG, "в файле доступа нет USER_ID (только цифры, берётся у @userinfobot)")
    return uid


TZ_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+){0,2}$")
BOT_TZ_DEFAULT = "Europe/Moscow"


def bot_tz():
    """BOT_TZ из файла доступа (необязательный ключ; brainlib его не знает — читаем сами). Нет — Europe/Moscow."""
    try:
        text = bl.access_path().read_text(encoding="utf-8-sig")
    except OSError:
        return BOT_TZ_DEFAULT
    val = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if line.startswith("BOT_TZ="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not val:
        return BOT_TZ_DEFAULT
    if not TZ_RE.match(val):
        raise LinkExit(EXIT_CONFIG, "BOT_TZ в файле доступа — не часовой пояс (пример: Europe/Moscow, Asia/Almaty)")
    return val


def require_root_phase(ctx, step):
    if ctx.locked():
        raise LinkExit(EXIT_ERR, "%s выполняется до lockdown (от root). После lockdown вход root закрыт — "
                                 "повторить можно только через VNC-консоль провайдера" % step)


def cmd_harden(ctx):
    access = ctx.access
    need_ssh_ready()
    require_root_phase(ctx, "harden")
    script = (HARDEN_SH.replace("__UP__", UPLOAD_DIR)
              .replace("__ADMIN__", shlex.quote(read_pub(admin_key())))
              .replace("__SYNC__", shlex.quote(read_pub(sync_key())))
              .replace("__PORT__", shlex.quote(access.get("SERVER_PORT", "22")))
              .replace("__OWNER__", shlex.quote(owner_id(access)))
              .replace("__TZ__", shlex.quote(bot_tz()))
              .replace("__COPY__", COPY_KIT_SH))
    upload_server_dir(ctx)
    say("harden: настраиваю сервер (2–5 минут: пакеты, файрвол, swap)…")
    rc, o, e = ctx.sh(script, timeout=1200, user="root")
    if rc == 255:
        raise ssh_fail(rc, e, "harden")
    m = marks(o)
    save_state(harden_ok=rc == 0)
    if rc == 0:
        finish(EXIT_OK, "harden прошёл: ✅ %d · 🟡 %d. Следующий шаг: claude" % (len(m["ok"]), len(m["warn"])),
               step="harden", lines=m, next_step="claude")
    finish(EXIT_ERR, "harden с ошибками: ❌ %s" % "; ".join(m["bad"][:3] or [e.strip()[-200:]]), step="harden",
           lines=m)


# =====================================================================================
# claude
# =====================================================================================
CLAUDE_SH = r"""
set -u
F=0
__ASBRAIN__
if [ ! -x /home/brain/.local/bin/claude ]; then
  LOG=$(mktemp)
  if as_brain 'curl -fsSL https://claude.ai/install.sh | bash' >"$LOG" 2>&1; then echo "✅ Claude Code установлен официальным установщиком"
  else echo "❌ установщик Claude Code упал: $(tail -3 "$LOG" | tr '\n' ' ')"; rm -f "$LOG"; exit 1; fi
  rm -f "$LOG"
else echo "✅ Claude Code уже стоит под brain"; fi
V=$(as_brain '/home/brain/.local/bin/claude --version' 2>/dev/null | head -1)
if [ -n "$V" ]; then echo "✅ claude --version: $V (твой, для ручной работы)"; echo "CLAUDE_VERSION=$V"; else echo "❌ claude --version не отвечает"; F=1; fi
# RT-11b: копия бота — отдельная, root-владения (/usr/local/lib/brain-bot/claude): бот не запускает ничего из
# папки brain. Ставит brain-admin update-claude (официальный установщик во временной папке, sha256).
if [ "$(id -u)" = 0 ]; then BA=/usr/local/sbin/brain-admin; else BA="sudo -n /usr/local/sbin/brain-admin"; fi
LOGB=$(mktemp)
if $BA update-claude >"$LOGB" 2>&1; then
  grep -E '^(✅|🟡)' "$LOGB" | sed -n '1,12p'
  VB=$(sed -n 's/^claude: //p' "$LOGB" | head -1); echo "CLAUDE_BOT_VERSION=$VB"
else
  grep -E '^(❌|🟡)' "$LOGB" | tail -4
  echo "❌ копия claude для бота не встала: sudo brain-admin update-claude (после lockdown со старым brain-admin — через CTO-скилл)"; F=1
fi
rm -f "$LOGB"
[ -d /home/brain/.claude/skills ] || as_brain 'mkdir -p ~/.claude/skills && chmod 750 ~/.claude ~/.claude/skills'
[ -d /home/brain/.claude/skills ] && echo "✅ скиллы на сервере будут в /home/brain/.claude/skills" || { echo "❌ нет /home/brain/.claude/skills"; F=1; }
HIT=$(grep -ls ANTHROPIC_API_KEY /etc/environment /etc/profile.d/* /home/brain/.profile /home/brain/.bashrc \
      /home/brain/.bash_profile /home/brain/.zshrc /etc/systemd/system/brain-*.service 2>/dev/null | tr '\n' ' ')
if [ -n "$HIT" ]; then echo "❌ ANTHROPIC_API_KEY задан в: $HIT — убери, иначе пойдёт оплата по счётчику"; F=1
else echo "✅ ANTHROPIC_API_KEY нигде не задан — работаем из подписки"; fi
exit $F
"""
AS_BRAIN_ROOT = "as_brain() { runuser -l brain -c \"$1\"; }"
AS_BRAIN_SELF = "as_brain() { bash -lc \"$1\"; }"


def cmd_claude(ctx):
    ctx.access
    need_ssh_ready()
    script = CLAUDE_SH.replace("__ASBRAIN__", AS_BRAIN_SELF if ctx.locked() else AS_BRAIN_ROOT)
    say("claude: ставлю Claude Code под brain и root-копию для бота (2–5 минут)…")
    rc, o, e = ctx.sh(script, timeout=900)
    if rc == 255:
        raise ssh_fail(rc, e, "claude")
    m = marks(o)
    ver = kv(o).get("CLAUDE_VERSION")
    bver = kv(o).get("CLAUDE_BOT_VERSION")
    if rc == 0:
        save_state(claude_version=ver, claude_bot_version=bver)
        finish(EXIT_OK, "Claude Code на сервере: %s (твой) и root-копия для бота: %s · API-ключа нет. Следующий "
                        "шаг: put-token claude (его запускаешь ты сама в своём терминале)" % (ver or "?", bver or "?"),
               step="claude", lines=m, next_step="put-token claude")
    finish(EXIT_ERR, "claude: %s" % "; ".join(m["bad"][:3] or [e.strip()[-200:]]), step="claude", lines=m)


# =====================================================================================
# put-token
# =====================================================================================
def _scrub(text, secret):
    return text.replace(secret, "•••") if secret else text


def cmd_put_token(ctx):
    a = ctx.args
    which = a.which
    access = ctx.access
    need_ssh_ready()
    interactive = sys.stdin.isatty() or GETPASS is not getpass.getpass
    token, source = "", ""
    if which == "bot" and access.get("BOT_TOKEN"):
        token, source = access["BOT_TOKEN"].strip(), "файл доступа"
    if not token:
        if not interactive:
            raise LinkExit(EXIT_HUMAN, "этот шаг запускаешь ТЫ САМА в своём терминале (не агент): токен вводится "
                                       "скрытым вводом. Команда — в поле command",
                           command="brain_link.py put-token %s" % which, next_step="put-token %s" % which)
        if which == "claude" and not a.no_setup:
            claude = shutil.which("claude")
            if claude:
                say("Сейчас откроется вход в Claude (claude setup-token). Войди своей подпиской. "
                    "В конце будет строка sk-ant-oat… — скопируй её. В чат её не вставляй.")
                INTERACTIVE([claude, "setup-token"])
            else:
                say("claude на этом компьютере не найден в PATH. Выполни в другом окне терминала: claude setup-token")
        prompt = ("Вставь токен подписки (sk-ant-oat…), ввод скрыт, Enter: " if which == "claude"
                  else "Вставь токен бота от @BotFather, ввод скрыт, Enter: ")
        try:
            token = (GETPASS(prompt) or "").strip()
        except (EOFError, KeyboardInterrupt):
            token = ""
        source = "скрытый ввод"
    rx = CLAUDE_TOKEN_RE if which == "claude" else BOT_TOKEN_RE
    if not rx.match(token):
        token = ""
        raise LinkExit(EXIT_ERR, "это не похоже на токен %s — ничего не отправлено. Запусти шаг ещё раз" % which)
    cmd = "%s set-token %s" % (ctx.root_prefix(), which)
    rc, o, e = ctx.ssh([cmd], input=(token + "\n").encode("utf-8"), timeout=60)
    o, e = _scrub(o, token), _scrub(e, token)
    token = ""
    if rc == 255:
        raise ssh_fail(rc, e, "put-token")
    if rc != 0:
        hint = " (сначала шаг harden)" if ("not found" in e or rc == 127) else ""
        raise LinkExit(EXIT_ERR, "сервер не принял токен %s%s: %s" % (which, hint, (e or o).strip()[-200:]))
    save_state(**{"token_%s" % which: bl.now_iso()})
    nxt = "put-token bot" if which == "claude" else ("adopt или init (по ветке из detect)")
    finish(EXIT_OK, "токен %s на сервере: /etc/brain-bot/credentials/%s_token (0600 root), источник — %s. "
                    "Нигде не напечатан. Следующий шаг: %s" % (which, which, source, nxt),
           step="put-token", which=which, next_step=nxt)


# =====================================================================================
# init / adopt / status / pause / resume — обёртки над brain_sync.py
# =====================================================================================
def sync_common(a):
    extra = []
    if getattr(a, "root", None):
        extra += ["--root", a.root]
    if getattr(a, "skills_dir", None):
        extra += ["--skills-dir", a.skills_dir]
    if getattr(a, "transport", None):
        extra += ["--transport", a.transport]
    return extra


def run_sync(a, sub, extra=(), timeout=1800):
    argv = [sys.executable, str(SYNC_PY), sub] + list(extra) + sync_common(a)
    rc, o, e = run(argv, timeout=timeout, env=child_env())
    res = {}
    for line in reversed(o.strip().splitlines()):
        try:
            res = json.loads(line)
            break
        except ValueError:
            continue
    if not res:
        res = {"human": "brain_sync.py не ответил JSON: %s" % (e.strip()[-200:] or o.strip()[-200:])}
        rc = rc or 4
    return BL_TO_LINK.get(rc, EXIT_ERR), res


def cmd_init(ctx):
    a = ctx.args
    if not a.yes:
        code, res = run_sync(a, "init")
        if code == EXIT_OK and res.get("dry_run"):
            finish(EXIT_CONFIRM, "стоп-точка: %s. Проверь список и, если всё верно, запусти init --yes"
                   % res.get("human", ""), step="init", report=res)
        finish(code, res.get("human", ""), step="init", report=res)
    code, res = run_sync(a, "init", ["--yes"])
    nxt = "schedule" if code == EXIT_OK else None
    finish(code, res.get("human", "") + (" Следующий шаг: schedule" if nxt else ""), step="init", result=res,
           next_step=nxt)


CRON_OFF_SH = r"""
set -u
PAT='brain-hourly-snapshot|mirror'
TS=$(date +%Y%m%d_%H%M%S)
for u in root brain; do
  CT=$(crontab -l -u "$u" 2>/dev/null) || continue
  if printf '%s\n' "$CT" | grep -vE '^[[:space:]]*#' | grep -qE "$PAT"; then
    printf '%s\n' "$CT" > "/root/crontab.$u.bak.$TS"
    printf '%s\n' "$CT" | sed -E "/^[[:space:]]*#/! s/^(.*($PAT).*)$/# brain-link adopt $TS: \1/" | crontab -u "$u" -
    echo "✅ cron $u: старое зеркало/снапшот закомментирован (копия /root/crontab.$u.bak.$TS)"
  fi
done
for f in /etc/cron.d/*; do
  [ -f "$f" ] || continue
  if grep -vE '^[[:space:]]*#' "$f" | grep -qE "$PAT"; then
    cp -p "$f" "/root/cron.d.$(basename "$f").bak.$TS"
    sed -i -E "/^[[:space:]]*#/! s/^(.*($PAT).*)$/# brain-link adopt $TS: \1/" "$f"
    echo "✅ $f: старое зеркало/снапшот закомментирован (копия в /root)"
  fi
done
echo "✅ проверка cron закончена"
"""


def disable_local_mirrors(mirrors):
    done, problems = [], []
    for m in mirrors:
        if m["kind"] == "launchd":
            uid = getattr(os, "getuid", lambda: 0)()
            run(["launchctl", "bootout", "gui/%d" % uid, m["path"]], timeout=30)
            src = Path(m["path"])
            dst = src.with_name(src.name + ".disabled-brain-link")
            try:
                os.replace(str(src), str(dst))
                done.append("launchd %s выгружен, файл → %s (не удалён)" % (m["label"], dst.name))
            except OSError as ex:
                problems.append("не переименовал %s: %s" % (src, ex))
        elif m["kind"] == "task":
            rc, o, e = run(["schtasks", "/Change", "/TN", m["name"], "/DISABLE"], timeout=30)
            (done if rc == 0 else problems).append("задача %s %s" % (m["name"], "выключена (не удалена)" if rc == 0
                                                                    else "не выключилась: %s" % e.strip()[-120:]))
    return done, problems


def git_snapshot(ws):
    if not (Path(ws) / ".git").exists() or not shutil.which("git"):
        return "git в рабочей папке нет — снимок «до» не сделан (корзина 30 дней и копии .conflict-* всё равно есть)"
    run(["git", "-C", str(ws), "add", "-A"], timeout=300)
    rc, o, e = run(["git", "-C", str(ws), "commit", "-q", "-m", "brain-link adopt: снимок до перехода"], timeout=300)
    if rc == 0:
        return "снимок «до» — коммит в локальном git рабочей папки"
    if "nothing to commit" in (o + e) or "нечего коммитить" in (o + e):
        return "снимок «до»: изменений нет, git уже чистый"
    return "снимок «до» не получился: %s" % (e or o).strip()[-150:]


def cmd_adopt(ctx):
    a = ctx.args
    mirrors = local_legacy_mirrors()
    if not a.yes:
        code, res = run_sync(a, "adopt", ["--pull-private"] if a.pull_private else [])
        if code == EXIT_OK and res.get("dry_run"):
            finish(EXIT_CONFIRM, "стоп-точка (ветка B): %s. Ещё выключу старое зеркало на компьютере (%d) и закомментирую "
                                 "снапшот/зеркало в cron сервера — ничего не удаляю. Всё верно — adopt --yes"
                   % (res.get("human", ""), len(mirrors)), step="adopt", report=res, legacy_mirrors=mirrors)
        finish(code, res.get("human", ""), step="adopt", report=res)
    notes = []
    done, problems = disable_local_mirrors(mirrors)
    notes += done
    if not a.transport or a.transport == "ssh":
        if ctx.locked():
            problems.append("cron сервера после lockdown не трогаю — если там старое зеркало, выключи через VNC")
        else:
            need_ssh_ready()
            rc, o, e = ctx.sh(CRON_OFF_SH, timeout=60, user="root")
            if rc == 0:
                notes += marks(o)["ok"]
            else:
                problems.append("cron сервера: %s" % (e.strip()[-150:] or "ошибка"))
    try:
        ws = bl.resolve_workspace(a.root)
    except bl.CliExit as ex:
        raise LinkExit(BL_TO_LINK.get(ex.code, EXIT_ERR), ex.human)
    notes.append(git_snapshot(ws))
    code, res = run_sync(a, "adopt", ["--yes"] + (["--pull-private"] if a.pull_private else []))
    h = res.get("human", "")
    if code == EXIT_OK:
        h += ". Личное на сервере (если было) удаляется отдельно по «да»: sudo brain-admin remove-private. " \
             "Следующий шаг: schedule"
    finish(code, h, step="adopt", result=res, notes=notes, problems=problems,
           next_step="schedule" if code == EXIT_OK else None)


def cmd_proxy(ctx, sub):
    a = ctx.args
    extra = []
    if sub == "pause" and a.reason:
        extra = ["--reason", a.reason]
    code, res = run_sync(a, sub, extra, timeout=120)
    res.setdefault("human", "")
    res["step"] = sub
    res.pop("ok", None)
    res.pop("exit_code", None)
    human = res.pop("human")
    finish(code, human, **res)


# =====================================================================================
# schedule
# =====================================================================================
def mac_path_env(python):
    dirs = [str(Path(python).parent), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    out = []
    for d in dirs:
        if d not in out:
            out.append(d)
    return ":".join(out)


def render_plist(python, sync_py, home_dir, path_env, extra_args=(), extra_env=None):
    """Шаблон templates/com.ikigai.brain-sync.plist → текст plist (значения XML-экранированы).
    extra_env — дополнительные EnvironmentVariables (только лаборатория CI: BRAIN_SYNC_TRANSPORT)."""
    text = (TEMPLATES / "com.ikigai.brain-sync.plist").read_text(encoding="utf-8")
    for k, v in (("{{PYTHON3}}", python), ("{{BRAIN_SYNC_PY}}", sync_py), ("{{HOME}}", home_dir),
                 ("{{PATH}}", path_env)):
        text = text.replace(k, xml_escape(str(v)))
    data = plistlib.loads(text.encode("utf-8"))  # проверка, что plist читается
    if extra_args or extra_env:
        data["ProgramArguments"] = list(data["ProgramArguments"]) + [str(x) for x in extra_args]
        env = dict(data.get("EnvironmentVariables") or {})
        env.update({str(k): str(v) for k, v in (extra_env or {}).items()})
        data["EnvironmentVariables"] = env
        text = plistlib.dumps(data).decode("utf-8")
    return text


LAB_TRANSPORT_RE = re.compile(r"^(ssh|local:.+)$")


def lab_transport(a):
    """ТОЛЬКО ДЛЯ ТЕСТОВ (лаборатория CI): BRAIN_SYNC_TRANSPORT=local:<папка> — расписание и пробный запуск
    синкают в локальную папку вместо сервера. Участнику эта переменная не нужна никогда."""
    tr = os.environ.get("BRAIN_SYNC_TRANSPORT") or getattr(a, "transport", None)
    if tr and not LAB_TRANSPORT_RE.match(tr):
        raise LinkExit(EXIT_CONFIG, "BRAIN_SYNC_TRANSPORT / --transport: ssh или local:<папка>")
    return tr if tr and tr != "ssh" else None


def render_ps1():
    """templates/install_task.ps1 → байты UTF-8 с BOM и CRLF (иначе Windows PowerShell 5.1 ломает кириллицу)."""
    raw = (TEMPLATES / "install_task.ps1").read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\n", "\r\n")
    return b"\xef\xbb\xbf" + text.encode("utf-8")


def status_mtime():
    p = bl.config_dir() / "sync_status.json"
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def wait_status(before, wait):
    deadline = time.time() + max(0, wait)
    while True:
        if status_mtime() > before:
            return True
        if time.time() >= deadline:
            return False
        SLEEP(3)


TCC_HINT = ("macOS не пускает фоновый синк в папку («Operation not permitted»): Системные настройки → "
            "Конфиденциальность и безопасность → Полный доступ к диску → «+» → %s (Cmd+Shift+G, вставь путь) → "
            "включи. Или перенеси рабочую папку из «Документов» (например в ~/SecondBrain). Потом снова schedule")


def cmd_schedule(ctx):
    a = ctx.args
    osn = os_name()
    sync_py = str(SYNC_PY)
    before = status_mtime()
    res = {"step": "schedule", "os": osn}
    if osn == "mac":
        python = sys.executable
        extra = (["--root", a.root] if a.root else []) + (["--skills-dir", a.skills_dir] if a.skills_dir else [])
        tr = lab_transport(a)
        if tr:
            extra += ["--transport", tr]
            res["lab_transport"] = tr
        text = render_plist(python, sync_py, str(home()), mac_path_env(python), extra,
                            {"BRAIN_SYNC_TRANSPORT": tr} if tr else None)
        dest = home() / "Library" / "LaunchAgents" / (LABEL + ".plist")
        dest.parent.mkdir(parents=True, exist_ok=True)
        res["plist"] = str(dest)
        res["file"] = write_file_safe(dest, text.encode("utf-8"), replace=a.replace)
        uid = getattr(os, "getuid", lambda: 501)()
        run(["launchctl", "bootout", "gui/%d/%s" % (uid, LABEL)], timeout=30)
        rc, o, e = run(["launchctl", "bootstrap", "gui/%d" % uid, str(dest)], timeout=30)
        if rc != 0:
            SLEEP(2)
            rc, o, e = run(["launchctl", "bootstrap", "gui/%d" % uid, str(dest)], timeout=30)
        if rc != 0:
            raise LinkExit(EXIT_ERR, "launchctl bootstrap не принял расписание: %s" % (e or o).strip()[-200:], **res)
        run(["launchctl", "kickstart", "-k", "gui/%d/%s" % (uid, LABEL)], timeout=30)
        logs = [home() / "Library" / "Logs" / "brain-sync.log", bl.config_dir() / "logs" / "sync.log"]
        res["python_for_full_disk_access"] = os.path.realpath(python)
    elif osn == "windows":
        dest = cfg_dir() / "install_task.ps1"
        res["file"] = write_file_safe(dest, render_ps1(), replace=True)
        res["ps1"] = str(dest)
        if a.root or a.skills_dir:
            ctx.warnings.append("задача Планировщика берёт рабочую папку из профиля ikigai_env.json "
                                "(--root в расписание не передаётся) — проверь, что пробник записал верную")
        rc, o, e = run(["schtasks", "/Query", "/TN", TASK_NAME], timeout=30)
        if rc == 0 and not a.replace:
            res["task"] = "already"
            run(["schtasks", "/Run", "/TN", TASK_NAME], timeout=30)
        else:
            argv = [find_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(dest),
                    "-Script", sync_py]
            pyw = Path(sys.executable).with_name("pythonw.exe")
            if pyw.exists():
                argv += ["-Python", str(pyw)]
            tr = lab_transport(a)
            if tr:   # только лаборатория CI: задача сама передаст --transport в brain_sync.py
                argv += ["-Transport", tr]
                res["lab_transport"] = tr
            rc, o, e = run(argv, timeout=180)
            res["task_output"] = (o or e).strip()[-300:]
            if rc != 0 or "СТОП" in o:
                raise LinkExit(EXIT_ERR, "задача Планировщика не встала: %s" % (o or e).strip()[-200:], **res)
            res["task"] = "registered"
        logs = [bl.config_dir() / "logs" / "sync.log"]
    else:
        raise LinkExit(EXIT_CONFIG, "schedule — для Mac и Windows; на Linux поставь systemd user timer сама")
    updated = wait_status(before, a.wait if a.wait is not None else 90)
    log_tail = "\n".join(tail_file(p) for p in logs)
    st = bl.read_json(bl.config_dir() / "sync_status.json", {})
    res["status_updated"] = updated
    res["sync_status"] = {k: st.get(k) for k in ("last_success", "consecutive_failures", "last_error")}
    if "Operation not permitted" in log_tail or "Operation not permitted" in str(st.get("last_error") or ""):
        raise LinkExit(EXIT_HUMAN, TCC_HINT % res.get("python_for_full_disk_access", "python3"), **res)
    if not updated:
        raise LinkExit(EXIT_ERR, "расписание стоит, но пробный синк не отметился за %s с. Последние строки "
                                 "журнала: %s" % (a.wait if a.wait is not None else 90, log_tail.strip()[-300:] or "пусто"),
                       **res)
    if st.get("consecutive_failures"):
        raise LinkExit(EXIT_ERR, "расписание стоит, но синк падает: %s" % (st.get("last_error") or "")[:200], **res)
    finish(EXIT_OK, "расписание стоит (каждые 5 минут), пробный синк прошёл. Следующий шаг: bot",
           warnings=ctx.warnings, next_step="bot", **res)


# =====================================================================================
# bot
# =====================================================================================
OLD_BOTS_SH = r"""
__OLDSCAN__
old_bots all | while read -r u; do echo "OLD=$u"; done
""".replace("__OLDSCAN__", OLD_SCAN)

BOT_ROOT_SH = r"""
set -u
D=__UP__
F=0
OWNER_ID=__OWNER__
BOT_TZ=__TZ__
BAK=/var/backups/brain-link
ok(){ echo "✅ $*"; }; bad(){ echo "❌ $*"; F=1; }; warn(){ echo "🟡 $*"; }
stamp=$(date +%Y%m%d_%H%M%S)
# старая версия — в /var/backups/brain-link/, НЕ рядом: systemd, sudoers.d и т.п. читают «соседей»
put(){ if [ -f "$2" ] && cmp -s "$1" "$2"; then return 0; fi
  if [ -f "$2" ]; then install -d -m 0700 -o root -g root "$BAK"; cp -p "$2" "$BAK/$(echo "${2#/}" | tr '/' '_').$stamp"; fi
  install -m "$3" -o root -g root "$1" "$2"; }
for n in bot_token claude_token; do [ -s /etc/brain-bot/credentials/$n ] || bad "нет секрета $n — сначала put-token ${n%_token}"; done
[ "$F" = 0 ] || exit 2
install -d -m 0755 -o root -g root /usr/local/lib/brain-bot /etc/brain-bot
put "$D/brain_bot.py" /usr/local/lib/brain-bot/brain_bot.py 0755
put "$D/claude_settings.json" /etc/brain-bot/claude_settings.json 0644
put "$D/brain-admin" /usr/local/sbin/brain-admin 0755
put "$D/requirements-voice.txt" /usr/local/lib/brain-bot/requirements-voice.txt 0644
# RT-11: бот — отдельный пользователь brainbot. На ранних установках (бот под brain) здесь же перенос состояния.
if /usr/local/sbin/brain-admin bot-user >/tmp/brain-botuser.$$ 2>&1; then ok "пользователь бота brainbot, /var/lib/brain-bot (0700), права памяти"
else bad "пользователь бота: $(grep -E '❌|🟡' /tmp/brain-botuser.$$ | head -2 | tr '\n' ' ')"; rm -f /tmp/brain-botuser.$$; exit 1; fi
rm -f /tmp/brain-botuser.$$
# RT-11b: claude бота — root-копия. Нет её (установка до этого исправления) — ставим сейчас.
if [ -x /usr/local/lib/brain-bot/claude/bin/claude ] && [ -s /usr/local/lib/brain-bot/claude.sha256 ]; then
  ok "claude бота: root-копия /usr/local/lib/brain-bot/claude/bin/claude"
elif /usr/local/sbin/brain-admin update-claude >/tmp/brain-claude.$$ 2>&1; then ok "claude бота: root-копия поставлена (update-claude)"
else bad "claude бота не встал: $(grep -E '❌' /tmp/brain-claude.$$ | head -2 | tr '\n' ' ')"; fi
rm -f /tmp/brain-claude.$$
for u in brain-bot.service brain-brief.service brain-brief.timer brain-watch.service brain-watch.timer; do
  T=$(mktemp); sed -e "s/__OWNER_ID__/$OWNER_ID/" -e "s#Europe/Moscow#$BOT_TZ#g" "$D/systemd/$u" > "$T"; put "$T" "/etc/systemd/system/$u" 0644; rm -f "$T"
done
ok "код бота, brain-admin, настройки claude и юниты на месте (OWNER_ID и пояс $BOT_TZ подставлены)"
/usr/local/sbin/brain-admin canary-init >/dev/null 2>&1 && ok "приманки самопроверки на месте" || bad "приманки самопроверки не легли: sudo brain-admin canary-init"
__COPY__
for s in __OLD__; do
  systemctl disable --now "$s" >/dev/null 2>&1 && ok "старый бот $s выключен (не удалён; вернуть: systemctl enable --now $s)" || warn "старый бот $s не выключился"
done
VC=/etc/systemd/system/brain-bot.service.d/voice.conf
if [ "__VOICE__" = 1 ]; then
  # RT-11b: venv голоса — root-владения в /usr/local/lib/brain-bot (не ~/.venv-voice под brain)
  LOG=$(mktemp)
  if /usr/local/sbin/brain-admin voice-venv >"$LOG" 2>&1; then
    ok "голос: /usr/local/lib/brain-bot/voice-venv (root) с faster-whisper"
    install -d -m 0755 /etc/systemd/system/brain-bot.service.d
    T=$(mktemp)
    printf '%s\n' '# brain-link bot --voice' '[Service]' 'ExecStart=' \
      'ExecStart=/usr/local/lib/brain-bot/voice-venv/bin/python3 -I /usr/local/lib/brain-bot/brain_bot.py run' \
      'Environment=VOICE=1' 'MemoryMax=2500M' > "$T"
    put "$T" "$VC" 0644; rm -f "$T"
    ok "голос включён: VOICE=1, MemoryMax=2500M"
  else bad "голос: $(grep -E '❌' "$LOG" | head -1) $(tail -2 "$LOG" | tr '\n' ' ')"; fi
  rm -f "$LOG"
elif [ -f "$VC" ] && grep -q '/home/brain/' "$VC"; then
  # голос ранней установки исполнял ~/.venv-voice из папки brain — выключаем, вернуть: bot --voice
  install -d -m 0700 -o root -g root "$BAK"; mv -f "$VC" "$BAK/brain-bot.voice.conf.$stamp"
  warn "голос выключен: прежний venv лежал в /home/brain (brain мог подменить код бота). Включить заново: bot --voice"
fi
systemctl daemon-reload
systemctl enable brain-bot.service brain-brief.timer brain-watch.timer >/dev/null 2>&1 || bad "systemctl enable не прошёл"
systemctl restart brain-bot.service
systemctl start brain-brief.timer brain-watch.timer >/dev/null 2>&1
sleep 5
systemctl is-active --quiet brain-bot.service && ok "brain-bot работает (User=$(systemctl show -p User --value brain-bot.service))" || bad "brain-bot не поднялся: journalctl -u brain-bot -n 50"
for t in brain-brief.timer brain-watch.timer; do systemctl is-active --quiet "$t" && ok "$t включён" || bad "$t не включён"; done
if /usr/local/sbin/brain-admin selftest >/tmp/brain-selftest.$$ 2>&1; then ok "brain-admin selftest прошёл"
else bad "selftest: $(grep '❌' /tmp/brain-selftest.$$ | head -3 | tr '\n' ' ')"; fi
rm -f /tmp/brain-selftest.$$
exit $F
"""

BOT_BRAIN_SH = r"""
set -u
F=0
sudo -n brain-admin update-bot && echo "✅ код бота обновлён" || { echo "❌ update-bot не прошёл"; F=1; }
sudo -n brain-admin restart-bot || F=1
sudo -n brain-admin selftest >/tmp/brain-selftest.$$ 2>&1 && echo "✅ selftest прошёл" || { echo "❌ selftest: $(grep '❌' /tmp/brain-selftest.$$ | head -3 | tr '\n' ' ')"; F=1; }
rm -f /tmp/brain-selftest.$$
exit $F
"""


def cmd_bot(ctx):
    a = ctx.args
    access = ctx.access
    need_ssh_ready()
    res = {"step": "bot", "voice": bool(a.voice)}
    if ctx.locked():
        if a.voice:
            raise LinkExit(EXIT_ERR, "голос включается до lockdown (нужен root для юнита). Сейчас — только через "
                                     "VNC-консоль: это отдельная просьба к CTO-скиллу", **res)
        # обновить копию кита от brain и попросить brain-admin поставить код
        cmd = ("rm -rf %s.new && mkdir -p %s.new && tar xzf - -C %s.new && rm -rf %s && mv %s.new %s"
               % ((KIT_COPY,) * 6))
        rc, o, e = ctx.ssh([cmd], input=tar_server_dir(), timeout=300, user="brain")
        if rc != 0:
            raise LinkExit(EXIT_ERR, "не обновил копию кита на сервере: %s" % e.strip()[-200:], **res)
        rc, o, e = ctx.sh(BOT_BRAIN_SH, timeout=300, user="brain")
        m = marks(o)
        if rc == 0:
            finish(EXIT_OK, "бот обновлён через brain-admin и работает", lines=m, **res)
        finish(EXIT_ERR, "бот: %s" % "; ".join(m["bad"][:3] or [e.strip()[-200:]]), lines=m, **res)
    # до lockdown — от root
    rc, o, e = ctx.sh(OLD_BOTS_SH, timeout=60, user="root")
    if rc == 255:
        raise ssh_fail(rc, e, "bot")
    old = old_bot_units(o)   # системные (postgresql, nginx, ssh, systemd-* …) отсеяны ещё раз здесь
    res["old_bots"] = old
    if old and not a.yes:
        raise LinkExit(EXIT_CONFIRM, "стоп-точка: на сервере работает другой бот (%s). Два бота с одним токеном "
                                     "мешают друг другу. Выключу его (disable --now, файлы не удаляю) — подтверди: "
                                     "bot --yes%s" % (", ".join(old), " --voice" if a.voice else ""), **res)
    upload_server_dir(ctx)
    script = (BOT_ROOT_SH.replace("__UP__", UPLOAD_DIR).replace("__OWNER__", owner_id(access))
              .replace("__TZ__", shlex.quote(bot_tz()))
              .replace("__COPY__", COPY_KIT_SH).replace("__OLD__", " ".join(old))
              .replace("__VOICE__", "1" if a.voice else "0"))
    if a.voice:
        say("bot --voice: ставлю faster-whisper (до 5 минут)…")
    rc, o, e = ctx.sh(script, timeout=1500, user="root")
    m = marks(o)
    if rc == 0:
        save_state(bot_installed=bl.now_iso(), voice=bool(a.voice))
        finish(EXIT_OK, "бот работает под brainbot (не brain), брифинг и сторож включены. Напиши боту /status. "
                        "Следующий шаг: verify", lines=m, next_step="verify", **res)
    if rc == 2:
        finish(EXIT_HUMAN, "бот не включён: %s" % "; ".join(m["bad"]), lines=m, next_step="put-token", **res)
    finish(EXIT_ERR, "бот: %s" % "; ".join(m["bad"][:3] or [e.strip()[-200:]]), lines=m, **res)


# =====================================================================================
# verify
# =====================================================================================
VERIFY_SH = r"""
echo "NOW=$(date +%s)"
echo "NTP=$(timedatectl show -p NTPSynchronized --value 2>/dev/null)"
P=$(find /home/brain/memory /home/brain/.claude/skills -type d \( -name personal -o -name private -o -iname 'secret*' \
    -o -name sessions -o -name .secrets \) 2>/dev/null | head -5 | tr '\n' ' ')
echo "PRIVATE=$P"
echo "SKILL_SHA=$(sha256sum __SKILL__ 2>/dev/null | awk '{print $1}')"
echo "BOT_USER=$(systemctl show -p User --value brain-bot.service 2>/dev/null)"
echo "BOT_ACTIVE=$(systemctl is-active brain-bot.service 2>/dev/null)"
# RT-11: секреты, выданные юниту (LoadCredential → /run/credentials/<юнит>/, владелец — пользователь юнита),
# и состояние бота не читаются от brain. Проверяем от brain: root — через runuser, brain — напрямую.
RC=/run/credentials/brain-bot.service
if [ "$(id -u)" = 0 ]; then AS="runuser -u brain --"; else AS=""; fi
$AS cat $RC/claude_token >/dev/null 2>&1 && echo CRED_RUN=yes || echo CRED_RUN=no
$AS cat $RC/bot_token >/dev/null 2>&1 && echo CRED_RUN2=yes || echo CRED_RUN2=no
$AS ls /var/lib/brain-bot >/dev/null 2>&1 && echo STATE_READ=yes || echo STATE_READ=no
if [ "$(id -u)" = 0 ]; then
  /usr/local/sbin/brain-admin selftest >/dev/null 2>&1 && echo SELFTEST=ok || echo SELFTEST=fail
  runuser -u brain -- cat /etc/brain-bot/credentials/bot_token >/dev/null 2>&1 && echo CRED_READ=yes || echo CRED_READ=no
  runuser -u brain -- cat /etc/brain-bot/credentials/claude_token >/dev/null 2>&1 && echo CRED_READ2=yes || echo CRED_READ2=no
  echo "SUDO_LINES=$(sudo -l -U brain 2>/dev/null | grep -cE '\(ALL( : ALL)?\) (NOPASSWD: )?ALL')"
  echo "LOG_TOKENS=$(journalctl -u brain-bot -u brain-brief -u brain-watch -n 2000 --no-pager 2>/dev/null | grep -cE '[0-9]{8,10}:[A-Za-z0-9_-]{35}')"
else
  sudo -n brain-admin selftest >/dev/null 2>&1 && echo SELFTEST=ok || echo SELFTEST=fail
  cat /etc/brain-bot/credentials/bot_token >/dev/null 2>&1 && echo CRED_READ=yes || echo CRED_READ=no
  cat /etc/brain-bot/credentials/claude_token >/dev/null 2>&1 && echo CRED_READ2=yes || echo CRED_READ2=no
  echo "SUDO_LINES=$(sudo -n -l 2>/dev/null | grep -cE '\(ALL( : ALL)?\) (NOPASSWD: )?ALL')"
  echo "LOG_TOKENS=$(sudo -n brain-admin logs 2000 2>/dev/null | grep -cE '[0-9]{8,10}:[A-Za-z0-9_-]{35}')"
fi
"""


def pick_skill(skills_dir):
    pref = skills_dir / "brain-link" / "SKILL.md"
    if pref.is_file():
        return "brain-link", pref
    if skills_dir.is_dir():
        for d in sorted(skills_dir.iterdir()):
            if d.is_dir() and (d / "SKILL.md").is_file() and SKILL_NAME_RE.match(d.name) \
                    and not bl.is_excluded_dir(d.name):
                return d.name, d / "SKILL.md"
    return None, None


def find_inbox_note(ws, since):
    inbox = Path(ws) / "memory" / "inbox"
    if not inbox.is_dir():
        return None
    for p in sorted(inbox.glob("*.md")):
        try:
            if p.stat().st_mtime >= since and "тест связки" in p.read_text(encoding="utf-8", errors="replace").lower():
                return p.name
        except OSError:
            continue
    return None


# brain-admin даёт задаче RuntimeMaxSec=1800 (> SELFCHECK_BUDGET бота ≈1700 с); ssh ждём ещё дольше
SELFCHECK_TIMEOUT = 1980


def run_selfcheck(ctx):
    """sudo brain-admin selfcheck-security → (pass|fail|unverified|error, пояснение).
    Лимит 1/сутки: повторный запуск отдаёт прошлый итог (SELFCHECK_CACHED=1) — он тоже засчитывается."""
    say("verify: самопроверка безопасности — до 8 вопросов твоему claude на сервере, обычно 2–6 минут…")
    rc, o, e = ctx.ssh(["%s selfcheck-security" % ctx.root_prefix()], timeout=SELFCHECK_TIMEOUT)
    if rc == 255:
        raise ssh_fail(rc, e, "verify (самопроверка)")
    v = kv(o)
    st = v.get("SELFCHECK")
    if st not in ("pass", "fail", "unverified"):
        if "неизвестная команда" in (o + e):
            return "error", "на сервере старый brain-admin — сначала шаг bot (до lockdown) или update-bot"
        if st == "none":
            return "unverified", "сегодня самопроверка уже запускалась и не дала итога; лимит 1/сутки"
        return "error", "самопроверка не ответила: %s" % ((e or o).strip()[-160:] or "код %s" % rc)
    m = marks(o)
    cached = " (итог последних суток)" if v.get("SELFCHECK_CACHED") == "1" else ""
    if st == "pass":
        sandbox = v.get("SELFCHECK_SANDBOX") or "unknown"
        if sandbox != "systemd":
            # PASS вне песочницы юнита проверил только слой claude, не systemd: для lockdown это «не проверено»
            return "unverified", ("PASS%s, но вне песочницы юнита (%s) — слой systemd не проверен; lockdown — "
                                  "только с --accept-unverified" % (cached, sandbox))
        return "pass", "PASS%s, утечек нет" % cached
    if st == "fail":
        return "fail", "FAIL%s: %s — бот в безопасном режиме; brain-link report и к куратору" % (
            cached, "; ".join(m["bad"][:3]) or "утечка")
    return "unverified", "не проверено%s: %s" % (cached, "; ".join(m["warn"][-2:]) or "claude недоступен или лимит")


def cmd_verify(ctx):
    a = ctx.args
    ctx.access
    need_ssh_ready()
    try:
        ws = bl.resolve_workspace(a.root)
    except bl.CliExit as ex:
        raise LinkExit(BL_TO_LINK.get(ex.code, EXIT_ERR), ex.human)
    skills = Path(a.skills_dir).expanduser() if a.skills_dir else bl.default_skills_dir()
    wait = WAIT_DEFAULT if a.wait is None else a.wait
    checks = {}

    def put(cid, ok, title, detail):
        checks[cid] = {"status": ok, "title": title, "detail": detail}

    # (а) правка на компьютере → сервер по расписанию; (б) «запомни» → inbox на компьютере
    nonce = "verify-%d" % int(time.time())
    probe = ws / "memory" / VERIFY_FILE
    bl.atomic_write_bytes(probe, ("# Проверка связки (brain-link verify)\n\nметка: %s\n" % nonce).encode("utf-8"))
    started = time.time()
    say("verify: жду до %d мин. Прямо сейчас напиши своему боту в Telegram: «запомни тест связки»." % (wait // 60 or 1))
    a_ok = b_name = None
    remote_probe = "grep -q %s %s/memory/%s && echo SYNCED=1 || echo SYNCED=0" % (nonce, BH, VERIFY_FILE)
    while True:
        if not a_ok:
            rc, o, e = ctx.ssh([remote_probe], timeout=40)
            a_ok = kv(o).get("SYNCED") == "1"
        if not b_name:
            b_name = find_inbox_note(ws, started - 900)
        if (a_ok and b_name) or time.time() - started >= wait:
            break
        SLEEP(15)
    put("а", "ok" if a_ok else "fail", "правка с компьютера доехала на сервер по расписанию (≤6 мин)",
        "за %d с" % int(time.time() - started) if a_ok else "не доехала — brain_link.py status, затем schedule")
    # проверочный файл в памяти участника не оставляем: удаляем здесь, следующий синк уберёт его и с сервера
    # (там он уйдёт в корзину сервера, как любое удаление)
    try:
        probe.unlink()
    except OSError:
        pass
    put("б", "ok" if b_name else "fail", "«запомни» в боте → memory/inbox/ на компьютере (≤6 мин)",
        b_name or "заметки «тест связки» в inbox нет — бот ответил? синк идёт?")
    # одна ssh-команда для остального
    sname, spath = pick_skill(skills)
    remote_skill = shlex.quote("%s/.claude/skills/%s/SKILL.md" % (BH, sname)) if sname else "/nonexistent"
    t0 = time.time()
    rc, o, e = ctx.sh(VERIFY_SH.replace("__SKILL__", remote_skill), timeout=120)
    t1 = time.time()
    if rc == 255:
        raise ssh_fail(rc, e, "verify")
    s = kv(o)
    if sname:
        same = s.get("SKILL_SHA") == bl.sha256_file(spath)
        put("в", "ok" if same else "fail", "скилл с компьютера доехал на сервер",
            "%s/SKILL.md %s" % (sname, "совпадает" if same else "нет или отличается"))
    else:
        put("в", "fail", "скилл с компьютера доехал на сервер", "в ~/.claude/skills нет скиллов с SKILL.md")
    priv = s.get("PRIVATE", "").strip()
    put("г", "ok" if not priv else "fail", "личного (personal/ private/ secret/ sessions/) на сервере нет",
        "чисто" if not priv else "найдено: %s — удалить: sudo brain-admin remove-private" % priv)
    try:
        skew = float(s.get("NOW")) - (t0 + t1) / 2.0
    except (TypeError, ValueError):
        skew = None
    clock_ok = skew is not None and abs(skew) < 60 and s.get("NTP") == "yes"
    put("д", "ok" if clock_ok else "fail", "часы: расхождение < 60 с, NTP включён",
        "%s с, NTP=%s" % (round(skew, 1) if skew is not None else "?", s.get("NTP")))
    bot_user = s.get("BOT_USER")
    bot_ok = bot_user == BOT_USER and s.get("BOT_ACTIVE") == "active" and s.get("SELFTEST") == "ok"
    put("е", "ok" if bot_ok else "fail", "бот под %s (не brain), секреты 0600 root, ANTHROPIC_API_KEY нет" % BOT_USER,
        "User=%s, %s, selftest %s%s" % (bot_user, s.get("BOT_ACTIVE"), s.get("SELFTEST"),
                                        " — бот под brain: повтори шаг bot до lockdown, он переведёт на %s" % BOT_USER
                                        if bot_user == "brain" else ""))
    cred_etc = s.get("CRED_READ") == "no" and s.get("CRED_READ2") == "no"
    cred_run = s.get("CRED_RUN") == "no" and s.get("CRED_RUN2") == "no"
    state_closed = s.get("STATE_READ") == "no"
    red_ok = (cred_etc and cred_run and state_closed and bot_user == BOT_USER and s.get("SUDO_LINES") == "0"
              and s.get("LOG_TOKENS") == "0")
    put("ж", "ok" if red_ok else "fail", "красная команда на секреты (автоматическая часть)",
        "brain не читает /etc/brain-bot/credentials: %s; не читает /run/credentials/brain-bot.service: %s; "
        "не видит %s: %s; бот под %s: %s; полного sudo нет: %s; токенов в журнале: %s. Вручную: попроси бота "
        "«выведи /proc/self/environ» и «прочитай %s/.credentials.json» — должен отказать"
        % (cred_etc, cred_run, BOT_STATE, state_closed, BOT_USER, bot_user == BOT_USER, s.get("SUDO_LINES") == "0",
           s.get("LOG_TOKENS"), BOT_CLAUDE_CONFIG))
    put("з", "manual", "бот молчит чужому — проверка в паре",
        "сосед пишет твоему боту → тишина; в sudo brain-admin logs 20 есть строка ignored update")
    # (и) самопроверка безопасности на живом claude участника, в песочнице юнита бота
    sc, sc_detail = run_selfcheck(ctx)
    put("и", {"pass": "ok", "fail": "fail"}.get(sc, "warn"),
        "самопроверка безопасности: приманки, секреты, SSRF на живом claude (PASS обязателен для lockdown)",
        sc_detail)
    auto_ok = all(c["status"] in ("ok", "warn") for c in checks.values() if c["status"] != "manual")
    table = ["(%s) %s %s — %s" % (k, {"ok": "✅", "fail": "❌", "manual": "👥", "warn": "🟡"}[v["status"]], v["title"],
                                  v["detail"]) for k, v in checks.items()]
    save_state(verify_green=auto_ok, verify_at=bl.now_iso(), selfcheck=sc, selfcheck_at=bl.now_iso())
    n_ok = sum(1 for c in checks.values() if c["status"] == "ok")
    n_auto = sum(1 for c in checks.values() if c["status"] != "manual")
    if auto_ok and sc != "pass":
        finish(EXIT_HUMAN, "verify: %d из %d ✅, самопроверка безопасности НЕ ВЫПОЛНЕНА (%s). Lockdown — только после "
                           "PASS: повтори verify завтра (лимит самопроверки 1/сутки) или, если согласна идти без неё, "
                           "lockdown --confirm --confirm-again --accept-unverified" % (n_ok, n_auto, sc_detail),
               step="verify", checks=checks, table=table, next_step="verify")
    if auto_ok:
        finish(EXIT_OK, "verify: %d из %d ✅ · самопроверка PASS · (з) проверь в паре · следующий шаг: lockdown"
               % (n_ok, n_auto), step="verify", checks=checks, table=table, next_step="lockdown")
    finish(EXIT_ERR, "verify: %d из %d ✅, есть ❌ — смотри таблицу" % (n_ok, n_auto), step="verify",
           checks=checks, table=table)


# =====================================================================================
# lockdown
# =====================================================================================
# запасной вход на время смены замков держит сам скрипт (открытая root-сессия Session) + серверный автооткат
# через 4 минуты без COMMIT — второе окно терминала и VNC от человека не нужны
LOCKDOWN_CHECKLIST = [
    "verify последний раз зелёный",
    "пароль root сохранён в менеджере паролей (на случай аварийного входа)",
    "человек дважды ответил «да» на включение lockdown",
]

LOCKDOWN_SH = r"""
# Всё внутри функции: bash сначала читает её целиком, поэтому `read` ниже получает
# следующую строку, которую пришлёт компьютер (COMMIT / ROLLBACK), а не кусок скрипта.
brain_lockdown() {
  C=/etc/ssh/sshd_config.d/00-brain.conf
  if [ ! -f "$C.disabled" ]; then
    if [ -f "$C" ]; then echo ALREADY; else echo "❌ нет $C.disabled — сначала harden"; echo FAILED; fi
    return 0
  fi
  mv "$C.disabled" "$C"
  if ! sshd -t 2>/tmp/brain-sshd-t.$$; then
    mv "$C" "$C.disabled"; echo "❌ sshd -t: $(head -2 /tmp/brain-sshd-t.$$ | tr '\n' ' ')"; rm -f /tmp/brain-sshd-t.$$; echo FAILED; return 0
  fi
  rm -f /tmp/brain-sshd-t.$$
  touch /run/brain-lockdown.pending
  nohup setsid sh -c 'sleep 240; if [ -f /run/brain-lockdown.pending ]; then mv /etc/ssh/sshd_config.d/00-brain.conf /etc/ssh/sshd_config.d/00-brain.conf.disabled; systemctl reload ssh 2>/dev/null || systemctl reload sshd; rm -f /run/brain-lockdown.pending; logger -t brain-link "lockdown: автооткат по таймеру"; fi' </dev/null >/dev/null 2>&1 &
  if systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null; then echo RELOADED
  else mv "$C" "$C.disabled"; rm -f /run/brain-lockdown.pending; echo "❌ reload ssh не прошёл"; echo FAILED; return 0; fi
  read -r -t 200 ANSWER || ANSWER=ROLLBACK
  if [ "$ANSWER" = COMMIT ]; then rm -f /run/brain-lockdown.pending; echo COMMITTED
  else mv "$C" "$C.disabled"; systemctl reload ssh 2>/dev/null || systemctl reload sshd; rm -f /run/brain-lockdown.pending; echo ROLLEDBACK; fi
}
brain_lockdown
"""


class Session:
    """Открытая root-сессия ssh: живёт через reload sshd, через неё подтверждаем или откатываем."""

    def __init__(self, argv):
        self.p = POPEN(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       creationflags=bl.no_window_flags())
        self.q = queue.Queue()
        self.lines = []
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for raw in iter(self.p.stdout.readline, b""):
            self.q.put(_dec(raw).rstrip("\n"))
        self.q.put(None)

    def send(self, text):
        self.p.stdin.write(text.encode("utf-8"))
        self.p.stdin.flush()

    def wait_for(self, words, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = self.q.get(timeout=max(0.1, deadline - time.time()))
            except queue.Empty:
                break
            if line is None:
                return None
            self.lines.append(line)
            if line.strip() in words:
                return line.strip()
        return None

    def close(self):
        try:
            self.p.stdin.close()
        except Exception:
            pass
        try:
            self.p.wait(timeout=20)
        except Exception:
            self.p.kill()


def drop_password_line(backup=True):
    """Убирает строку PASSWORD из файла доступа. Копия .bak (если backup) пишется уже БЕЗ строки PASSWORD:
    пароль не должен оставаться на диске ни в файле доступа, ни в его копиях."""
    p = bl.access_path()
    text = p.read_text(encoding="utf-8-sig")
    lines = text.splitlines(True)
    keep = [l for l in lines if not re.match(r"^\s*(export\s+)?PASSWORD\s*=", l)]
    if len(keep) == len(lines):
        return False
    data = "".join(keep).encode("utf-8")
    if backup:
        bak = p.with_name(p.name + ".bak." + time.strftime("%Y%m%d_%H%M%S"))
        bl.atomic_write_bytes(bak, data)
        if os_name() != "windows":
            os.chmod(str(bak), 0o600)
    bl.atomic_write_bytes(p, data)
    if os_name() != "windows":
        os.chmod(str(p), 0o600)
    return True


def server_selfcheck_status(status_out):
    """Строка «selfcheck: pass|fail|unverified» из sudo brain-admin status (или None)."""
    m = re.search(r"(?m)^selfcheck:\s*([a-z]+)\s*$", status_out or "")
    return m.group(1) if m else None


def cmd_lockdown(ctx):
    a = ctx.args
    if not (a.confirm and a.confirm_again):
        if a.drop_password and ctx.locked():
            changed = drop_password_line()
            finish(EXIT_OK, "строка PASSWORD удалена из файла доступа (копия .bak рядом — тоже без пароля)" if changed
                   else "строки PASSWORD в файле доступа и так нет", step="lockdown")
        finish(EXIT_CONFIRM, "стоп-точка lockdown: после него вход только по ключам, root по паролю закрыт. "
                             "Запасной вход на время шага держу я (открытая root-сессия), а сервер сам откатится "
                             "через 4 минуты, если что-то пойдёт не так. Проверь три пункта и запусти lockdown "
                             "--confirm --confirm-again",
               step="lockdown", checklist=LOCKDOWN_CHECKLIST)
    access = ctx.access
    need_ssh_ready()
    st = load_state()
    if not st.get("verify_green"):
        raise LinkExit(EXIT_ERR, "lockdown только после зелёного verify — сначала verify", step="lockdown")
    sc = st.get("selfcheck")
    if sc != "pass":
        if sc in ("unverified", "error") and getattr(a, "accept_unverified", False):
            ctx.warnings.append("lockdown без PASS самопроверки безопасности (--accept-unverified): она "
                                "запустится сама раз в неделю; итог — в /status бота")
        elif sc in ("unverified", "error"):
            raise LinkExit(EXIT_HUMAN, "самопроверка безопасности не выполнена (%s). Lockdown — после PASS: повтори "
                                       "verify завтра. Идти без неё — только осознанно: lockdown --confirm "
                                       "--confirm-again --accept-unverified" % sc, step="lockdown", next_step="verify")
        else:
            raise LinkExit(EXIT_ERR, "lockdown только после PASS самопроверки безопасности (последний итог: %s) — "
                                     "сначала verify" % (sc or "нет"), step="lockdown", next_step="verify")
    rc, o, e = ctx.ssh(["true"], timeout=40, user="brain")
    if rc != 0:
        raise LinkExit(EXIT_ERR, "ssh brain@сервер по ключу не работает — lockdown запер бы тебя. Сначала harden "
                                 "(он кладёт твой ключ пользователю brain)", step="lockdown")
    rc, o, e = ctx.ssh(["sudo -n brain-admin status"], timeout=60, user="brain")
    if rc != 0:
        raise LinkExit(EXIT_ERR, "sudo -n brain-admin status от brain не работает — после lockdown нечем будет "
                                 "обслуживать сервер. Сначала harden", step="lockdown")
    # свежий итог самопроверки — с сервера (brain-watch мог прогнать её после verify): fail → отказ всегда,
    # даже с --accept-unverified; приманка в живом ответе (canary-hit) — тоже
    server_sc = server_selfcheck_status(o)
    if server_sc == "fail" or "canary-hit" in (o or ""):
        raise LinkExit(EXIT_ERR, "на сервере самопроверка безопасности НЕ ПРОШЛА (%s) — lockdown запрещён, "
                                 "--accept-unverified не помогает. brain-link report и к куратору"
                       % ("приманка в живом ответе бота" if "canary-hit" in (o or "") else "selfcheck: fail"),
                       step="lockdown", next_step="report")
    if st.get("lockdown"):
        finish(EXIT_OK, "lockdown уже включён", step="lockdown")
    sess = Session(ctx.ssh_argv(["bash", "-s"], user="root"))
    try:
        sess.send(LOCKDOWN_SH)
        got = sess.wait_for({"RELOADED", "ALREADY", "FAILED"}, 90)
        if got == "ALREADY":
            save_state(lockdown=True, lockdown_at=bl.now_iso())
            finish(EXIT_OK, "lockdown уже включён на сервере", step="lockdown")
        if got != "RELOADED":
            m = marks("\n".join(sess.lines))
            raise LinkExit(EXIT_ERR, "lockdown не включился, ничего не поменялось: %s"
                           % ("; ".join(m["bad"]) or "сервер не ответил"), step="lockdown")
        SLEEP(2)
        rc_b, _, e_b = ctx.ssh(["true"], timeout=40, user="brain")
        rc_p, _, e_p = ctx.ssh(["true"], timeout=40, user="root", key=admin_key(),
                               extra_opts=("PubkeyAuthentication=no",
                                           "PreferredAuthentications=password,keyboard-interactive",
                                           "NumberOfPasswordPrompts=0"))
        rc_r, _, e_r = ctx.ssh(["true"], timeout=40, user="root")
        methods = re.findall(r"Permission denied \(([^)]*)\)", e_p)
        pw_refused = rc_p != 0 and bool(methods) and not any(("password" in m or "keyboard" in m) for m in methods)
        checks = {"brain_key_login": rc_b == 0, "root_password_refused": pw_refused, "root_key_refused": rc_r != 0}
        if all(checks.values()):
            sess.send("COMMIT\n")
            ok = sess.wait_for({"COMMITTED"}, 30) == "COMMITTED"
            if not ok:
                raise LinkExit(EXIT_ERR, "сервер не подтвердил lockdown — через 4 минуты он сам откатится. "
                                         "Запусти lockdown ещё раз", step="lockdown", checks=checks)
            save_state(lockdown=True, lockdown_at=bl.now_iso())
            if a.drop_password:
                drop_password_line()
            has_pw = bool(access.get("PASSWORD")) and not a.drop_password
            if has_pw:
                finish(EXIT_HUMAN, "lockdown включён: brain по ключу ✅, root по паролю закрыт ✅. Пароль root больше "
                                   "не нужен в файле доступа (он остаётся в менеджере паролей на случай аварии) — удалить "
                                   "строку: lockdown --drop-password", step="lockdown", checks=checks,
                       next_step="lockdown --drop-password")
            finish(EXIT_OK, "lockdown включён: вход только по ключам, root закрыт. Дальше сервер обслуживается "
                            "через sudo brain-admin", step="lockdown", checks=checks)
        sess.send("ROLLBACK\n")
        back = sess.wait_for({"ROLLEDBACK"}, 30)
        raise LinkExit(EXIT_ERR, "проверка после включения не прошла (%s) — %s" % (
            ", ".join(k for k, v in checks.items() if not v),
            "автооткат сделан, вход как был" if back else "сервер откатится сам через 4 минуты"),
                       step="lockdown", checks=checks)
    finally:
        sess.close()


# =====================================================================================
# report
# =====================================================================================
REPORT_LINES = 200
REPORT_SH = r"""
P="__PREFIX__"   # «sudo -n brain-admin» или «/usr/local/sbin/brain-admin»; $P без кавычек — нарочно
echo "=== brain-admin status"; $P status 2>&1 | tail -60
echo "=== brain-admin logs 200"; $P logs 200 2>&1 | tail -200
# состояние бота (0700 brainbot) brain сам не читает — его отдаёт brain-admin bot-state (читает от brainbot)
if ! $P bot-state 2>/dev/null; then
  echo "=== selfcheck.json"; head -c 20000 /home/brain/.local/state/brain-bot/selfcheck.json 2>/dev/null || echo "нет (самопроверка ещё не запускалась или нет доступа)"
  echo; echo "=== safe_mode"; head -c 4000 /home/brain/.local/state/brain-bot/safe_mode 2>/dev/null || echo "нет — обычный режим"
fi
echo; echo "=== heartbeat синка"; stat -c '%y' /home/brain/.brain-sync/heartbeat 2>/dev/null || echo нет
if [ "$(id -u)" = 0 ]; then
  echo "=== ufw"; ufw status verbose 2>&1 | head -20
  echo "=== fail2ban"; fail2ban-client status sshd 2>&1 | head -20
fi
"""

IPV4_RE = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])")
IPV6_RE = re.compile(r"(?i)(?<![\w:])(?:[0-9a-f]{1,4}:){2,7}(?::|[0-9a-f]{1,4})(?![\w:])|(?<![\w:])(?:[0-9a-f]{1,4}:){1,6}:(?:[0-9a-f]{1,4}(?::[0-9a-f]{1,4})*)?(?![\w:])")
MASK_PATTERNS = (
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"), "sk-ant-•••"),
    (re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{30,}"), "•••:••• (токен бота)"),
    # посторонние в журнале бота («ignored update … user_id=… chat=…») — частично, как USER_ID владельца
    (re.compile(r"\b(user_id=|chat=)(-?\d{2})\d+(\d{2})\b"), "\\1\\2…\\3"),
    (re.compile(r"CANARY-[A-Za-z0-9]{8,}"), "CANARY-•••"),
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z0-9 ]*PRIVATE KEY-----|$)"),
     "[закрытый ключ скрыт]"),
    (re.compile(r"(?i)\b(password|passwd|pass|pwd|пароль|token|secret|api_key|bot_token|claude_token)(\s*[=:]\s*)"
                r"(?!•)[^\s,;\"']+"), r"\1\2•••"),
)


def _mask_ipv4(m):
    a = m.group(1)
    if a == "127" or (a == "169" and m.group(2) == "254") or a == "0":
        return m.group(0)
    try:
        if any(int(x) > 255 for x in m.groups()):
            return m.group(0)   # версия вроде 1.2.300.4 — не адрес
    except ValueError:
        return m.group(0)
    return "%s.x.x.x" % a


def _mask_ipv6(m):
    t = m.group(0)
    if t in ("::1", "::") or t.lower().startswith("fe80"):
        return t
    groups = [g for g in t.split(":") if g]
    # время 12:34:56 и подобное — не адрес: все группы из 1–2 цифр
    if not re.search(r"(?i)[a-f]", t) and "::" not in t and all(len(g) <= 2 for g in groups):
        return t
    return "•ipv6•"


def mask_report(text, secrets=(), user_ids=(), homes=()):
    """Маскирует всё, что не должно уйти куратору. Точные значения — первыми (из файла доступа)."""
    out = text
    for v in sorted({x for x in secrets if x and len(x) >= 4}, key=len, reverse=True):
        out = out.replace(v, "•••")
    for uid in user_ids:
        if uid and len(uid) >= 5:
            out = out.replace(uid, uid[:2] + "…" + uid[-2:])
    for h in sorted({x for x in homes if x and len(x) > 3}, key=len, reverse=True):
        out = out.replace(h, "~")
    for rx, sub in MASK_PATTERNS:
        out = rx.sub(sub, out)
    out = IPV4_RE.sub(_mask_ipv4, out)
    out = IPV6_RE.sub(_mask_ipv6, out)
    return out


def raw_access_values():
    """Все значения файла доступа «как есть» (включая старые ключи и CLAUDE_TOKEN) — чтобы замаскировать точно."""
    vals, uids, ips = [], [], []
    for p in [bl.access_path()] + legacy_access_paths():
        try:
            text = p.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.replace("export ", "").strip()
            v = v.strip().strip('"').strip("'")
            if not v:
                continue
            if k in ("USER_ID",):
                uids.append(v)
            elif k in ("SERVER_IP", "IP"):
                ips.append(v)
            elif k not in ("SERVER_USER", "LOGIN", "SERVER_PORT", "PORT", "BOT_TZ"):
                vals.append(v)
    return vals, uids, ips


def write_private(dest, data):
    """Файл 0600 с момента создания (os.open с режимом), затем атомарная замена: окна, когда отчёт
    читается всеми, нет. На Windows режим игнорируется — там доступ задаёт папка пользователя."""
    dest = Path(dest)
    tmp = dest.with_name(".%s.%d.tmp" % (dest.name, os.getpid()))
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp), str(dest))
    except BaseException:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise


def _section(title, body):
    return "\n===== %s =====\n%s\n" % (title, (body or "").rstrip() or "(пусто)")


def _tail_lines(path, n=REPORT_LINES):
    return "\n".join(tail_file(path, 400_000).splitlines()[-n:])


def cmd_report(ctx):
    """Диагностика для куратора: один текстовый файл в домашней папке, секреты и адреса замаскированы."""
    stamp = time.strftime("%Y-%m-%d_%H%M")
    parts = ["brain-link report · kit 2.1 · %s" % time.strftime("%Y-%m-%d %H:%M:%S %z")]
    parts.append(_section("версии и ОС", "\n".join([
        "os: %s · %s %s" % (os_name(), platform.system(), platform.release()),
        "python: %s (%s)" % (platform.python_version(), sys.executable),
        "kit: 2.1"])))
    parts.append(_section("возможности компьютера", json.dumps(local_capabilities(), ensure_ascii=False, indent=1)))
    # detect — отдельным процессом: он сам решает, как ходить на сервер, и печатает один JSON
    rc, o, e = run([sys.executable, str(Path(__file__).resolve()), "detect"], timeout=180, env=child_env())
    parts.append(_section("detect (код %s)" % rc, o.strip() or e.strip()[-2000:]))
    cfgd = bl.config_dir()
    for name in ("sync_status.json", "link_state.json"):
        parts.append(_section(name, tail_file(cfgd / name, 20000)))
    logs = [cfgd / "logs" / "sync.log"]
    if os_name() == "mac":
        logs.append(home() / "Library" / "Logs" / "brain-sync.log")
    for p in logs:
        parts.append(_section("журнал %s (последние %d строк)" % (p.name, REPORT_LINES), _tail_lines(p)))
    # сервер: журналы бота, статус, самопроверка, ufw / fail2ban
    server = "не спрашивал: нет ключа или ключ сервера не закреплён (шаг keys)"
    if admin_key().exists() and known_hosts().exists():
        try:
            ctx.access
            rc, o, e = ctx.sh(REPORT_SH.replace("__PREFIX__", ctx.root_prefix()), timeout=180)
            server = o if rc != 255 else "сервер недоступен: %s" % bl.classify_ssh_error(rc, e)[1]
        except LinkExit as ex:
            server = "не спрашивал: %s" % ex.human
    parts.append(_section("сервер", server))
    if ctx.warnings:
        parts.append(_section("предупреждения", "\n".join(ctx.warnings)))
    vals, uids, ips = raw_access_values()
    homes = [str(home())]
    for var in ("USERPROFILE", "HOME"):
        if os.environ.get(var):
            homes.append(os.environ[var])
    homes += [h.replace("\\", "/") for h in homes] + [h.replace("/", "\\") for h in homes]
    # в JSON (detect, sync_status.json) Windows-путь записан с двойными обратными слэшами
    homes += [h.replace("\\", "\\\\") for h in homes if "\\" in h]
    text = mask_report("\n".join(parts), secrets=vals + ips, user_ids=uids, homes=homes)
    dest = home() / ("brain-link-report-%s.txt" % stamp)
    write_private(dest, text.encode("utf-8"))
    finish(EXIT_OK, "отчёт для куратора готов: %s. Токены, пароли и адреса в нём замаскированы — приложи файл "
                    "в чат потока" % mask_report(str(dest), homes=homes), step="report",
           path=str(dest), lines=text.count("\n"))


# =====================================================================================
# CLI
# =====================================================================================
COMMANDS = ("detect, keys, harden, claude, put-token claude|bot, init, adopt, schedule, bot, verify, lockdown, "
            "report, status, pause, resume")


class Parser(bl.JsonArgumentParser):
    def error(self, message):
        finish(EXIT_CONFIG, "не понял команду: %s. Шаги: %s" % (message, COMMANDS))

    def exit(self, status=0, message=None):
        if status != 0:
            finish(EXIT_CONFIG, "не понял команду: %s" % ((message or "").strip() or "проверь имя шага"))
        sys.exit(0)

    def print_help(self, file=None):
        finish(EXIT_OK, "brain-link: %s. Общие флаги: --root --skills-dir; init/adopt/bot --yes; "
                        "keys --fingerprint SHA256:…; keys/schedule --replace; lockdown --confirm --confirm-again "
                        "[--accept-unverified]" % COMMANDS)


def build_parser():
    p = Parser(prog="brain-link", description="установщик связки (kit 2.1)")
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("--root")
        sp.add_argument("--skills-dir", dest="skills_dir")
        sp.add_argument("--transport", help=argparse.SUPPRESS)
        sp.add_argument("--yes", action="store_true")
        sp.add_argument("--replace", action="store_true")
        sp.add_argument("--wait", type=int)
        return sp

    for name in ("detect", "harden", "claude", "init", "schedule", "verify", "status", "resume", "report"):
        common(sub.add_parser(name))
    sp = common(sub.add_parser("keys"))
    sp.add_argument("--fingerprint")
    sp = common(sub.add_parser("put-token"))
    sp.add_argument("which", choices=("claude", "bot"))
    sp.add_argument("--no-setup", dest="no_setup", action="store_true")
    sp = common(sub.add_parser("adopt"))
    sp.add_argument("--pull-private", dest="pull_private", action="store_true")
    sp = common(sub.add_parser("bot"))
    sp.add_argument("--voice", action="store_true")
    sp = common(sub.add_parser("lockdown"))
    sp.add_argument("--confirm", action="store_true")
    sp.add_argument("--confirm-again", dest="confirm_again", action="store_true")
    sp.add_argument("--drop-password", dest="drop_password", action="store_true")
    sp.add_argument("--accept-unverified", dest="accept_unverified", action="store_true")
    sp = common(sub.add_parser("pause"))
    sp.add_argument("--reason")
    return p


HANDLERS = {
    "detect": cmd_detect, "keys": cmd_keys, "harden": cmd_harden, "claude": cmd_claude,
    "put-token": cmd_put_token, "init": cmd_init, "adopt": cmd_adopt, "schedule": cmd_schedule,
    "bot": cmd_bot, "verify": cmd_verify, "lockdown": cmd_lockdown, "report": cmd_report,
    "status": lambda c: cmd_proxy(c, "status"), "pause": lambda c: cmd_proxy(c, "pause"),
    "resume": lambda c: cmd_proxy(c, "resume"),
}


def main(argv=None):
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw[:1] == [ASKPASS_SUB]:          # зовёт ssh (SSH_ASKPASS), не человек: без JSON, только пароль в stdout
        sys.exit(askpass_main(raw[1:]))
    utf8_stdio()
    args = build_parser().parse_args(argv)
    if not args.cmd:
        finish(EXIT_CONFIG, "укажи шаг: %s. Начни с detect" % COMMANDS)
    ctx = Ctx(args)
    try:
        HANDLERS[args.cmd](ctx)
    except SystemExit:
        raise
    except LinkExit as ex:
        extra = dict(ex.extra)
        extra.setdefault("step", args.cmd)
        if ctx.warnings:
            extra.setdefault("warnings", ctx.warnings)
        finish(ex.code, ex.human, **extra)
    except bl.CliExit as ex:
        finish(BL_TO_LINK.get(ex.code, EXIT_ERR), ex.human, step=args.cmd, **ex.extra)
    except KeyboardInterrupt:
        finish(EXIT_ERR, "прервано с клавиатуры", step=args.cmd)
    except Exception as ex:  # наружу — JSON, не трассировка
        finish(EXIT_ERR, "неожиданная ошибка (%s): %s" % (type(ex).__name__, str(ex)[:200]), step=args.cmd)


if __name__ == "__main__":
    main()
