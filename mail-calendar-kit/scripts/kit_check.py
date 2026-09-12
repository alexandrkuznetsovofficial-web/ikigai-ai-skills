#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kit_check.py — аудит: что уже стоит у ученика и в каком состоянии файл доступов.

Команды:
  system                      ОС, python, venv пака, claude, VS Code CLI, git, ssh (опц. --ssh-host/--ssh-port)
  env [--path P]              проверка файла доступов: ключи есть/нет, значения замаскированы
  bot-detect [--dir D ...]    какой бот у ученика: A (python-telegram-bot + Anthropic API) / B (бридж на Claude Code) / none
  all                         всё разом

Вывод — один JSON с полем "human". Секреты не печатаются.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

IS_WINDOWS = platform.system() == "Windows"
_VENV_ROOT = Path(os.environ.get("MCK_VENV", Path.home() / ".venvs" / "mck"))
VENV_PY = _VENV_ROOT / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
MAC_CODE_BIN = Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")


def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or r.stderr).strip()
    except Exception as ex:
        return 127, str(ex)


# ---------- system ----------
def cmd_system(args) -> dict:
    info = {"os": platform.system(), "os_version": platform.release(), "home": str(Path.home()),
            "python": platform.python_version(), "python_path": sys.executable}
    info["venv_ready"] = VENV_PY.exists()
    info["venv_python"] = str(VENV_PY)
    rc, outp = run(["claude", "--version"])
    info["claude"] = outp.splitlines()[0] if rc == 0 and outp else None
    code = shutil.which("code")
    if code:
        info["vscode_cli"] = code
    elif MAC_CODE_BIN.exists():
        info["vscode_cli"] = str(MAC_CODE_BIN)
        info["vscode_cli_note"] = "code нет в PATH; открывать файлы через: open -a \"Visual Studio Code\" <путь>"
    else:
        info["vscode_cli"] = None
    # Ветка системы: от неё зависят все команды, которые дальше выполняет Claude.
    info["os_branch"] = "windows" if IS_WINDOWS else ("mac" if platform.system() == "Darwin" else "linux")
    info["setup_script"] = "setup_venv.ps1" if IS_WINDOWS else "setup_venv.sh"
    info["python_cmd"] = "py -3" if IS_WINDOWS else "python3"
    if IS_WINDOWS:
        info["open_file_cmd"] = "code <путь>  (нет code → notepad <путь>)"
        info["config_dir"] = str(Path.home() / ".config" / "mail-calendar-kit")
        info["perms_note"] = ("на Windows прав 600 нет: файл доступов лежит в твоей личной папке, "
                              "куда другие пользователи компьютера не заходят")
    else:
        info["open_file_cmd"] = ("code <путь>" if shutil.which("code")
                                 else ('open -a "Visual Studio Code" <путь>' if MAC_CODE_BIN.exists() else "open -e <путь>"))
        info["config_dir"] = str(Path.home() / ".config" / "mail-calendar-kit")
    info["git"] = shutil.which("git") is not None
    info["ssh"] = shutil.which("ssh") is not None
    info["is_remote_session"] = bool(os.environ.get("SSH_CONNECTION")) or (
        platform.system() == "Linux" and not os.environ.get("DISPLAY"))
    if args.ssh_host:
        port = str(args.ssh_port or 22)
        rc, outp = run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-p", port, args.ssh_host, "true"], timeout=15)
        info["ssh_server_ok"] = (rc == 0)
        info["ssh_server_note"] = None if rc == 0 else "без пароля не пускает: нужен ssh-ключ (урок «Новоселье») или Remote-SSH в VS Code"
    parts = [{"windows": "Windows", "mac": "Mac", "linux": "Linux"}[info["os_branch"]] + f" · python {info['python']}",
             "venv пака есть" if info["venv_ready"] else "venv пака ещё нет (запусти setup_venv.sh)",
             f"claude: {info['claude'] or 'не найден'}",
             "VS Code CLI есть" if info["vscode_cli"] else "VS Code CLI не найден"]
    if "ssh_server_ok" in info:
        parts.append("сервер по ssh доступен" if info["ssh_server_ok"] else "сервер по ssh без пароля недоступен")
    info["human"] = " · ".join(parts)
    return info


# ---------- env ----------
REQUIRED_MAIL = ["MAIL_PROVIDER", "MAIL_USER", "MAIL_PASSWORD"]
REQUIRED_CALDAV = ["CAL_PROVIDER", "CALDAV_USER", "CALDAV_PASSWORD"]


def cmd_env(args) -> dict:
    if args.path:
        os.environ["MCK_ENV"] = args.path
    path = kitlib.env_path()
    res = {"env_path": str(path), "exists": path.exists()}
    if not path.exists():
        res["human"] = f"файла доступов нет: {path}. Создать из scripts/env.example."
        res["ok"] = False
        return res
    try:
        mode = oct(path.stat().st_mode & 0o777)
        res["mode"] = mode
        res["mode_ok"] = mode in ("0o600", "0o400")
    except Exception:
        res["mode_ok"] = None
    env = kitlib.load_env(required=False)
    # Маскируем всё, кроме явного белого списка: в файле доступов ученика может лежать что угодно,
    # включая ключи от других сервисов. Показывать «всё, где нет слова PASSWORD» — это утечка.
    SAFE = {"MAIL_PROVIDER", "CAL_PROVIDER", "TZ", "WORK_HOUR_FROM", "WORK_HOUR_TO",
            "MCK_SEND_ALLOWED", "GCAL_CALENDAR_ID", "CALDAV_CALENDAR", "SMTP_MODE",
            "IMAP_HOST", "IMAP_PORT", "SMTP_HOST", "SMTP_PORT", "MAIL_FROM_NAME",
            "GCAL_CREDENTIALS_PATH", "GCAL_TOKEN_PATH", "KIT_PYTHON", "KIT_DIR", "MCK_ENV",
            "MCK_PYTHON", "MCK_DIR"}
    def shown(k, v):
        if k in SAFE:
            return v or "(пусто)"
        if k == "MAIL_USER" or k == "CALDAV_USER":
            local, _, dom = (v or "").partition("@")
            return f"{local[:2]}…@{dom}" if dom else kitlib.mask(v)
        if k == "CALDAV_URL":       # часто вставляют вида https://логин:пароль@хост
            return v if v and "@" not in v else kitlib.mask(v)
        return kitlib.mask(v)
    present = {k: shown(k, v) for k, v in env.items()}
    res["values"] = present
    problems = []
    for k in REQUIRED_MAIL:
        if not env.get(k):
            problems.append(f"не заполнено {k}")
    mp = (env.get("MAIL_PROVIDER") or "").lower()
    if mp and mp not in list(kitlib.MAIL_PRESETS) + ["custom"]:
        problems.append(f"MAIL_PROVIDER='{mp}' неизвестен (yandex/gmail/mailru/icloud/custom)")
    user = env.get("MAIL_USER") or ""
    if user and "@" not in user:
        problems.append("MAIL_USER должен быть полным адресом с @")
    pw = env.get("MAIL_PASSWORD") or ""
    if pw and (" " in pw):
        problems.append("в MAIL_PASSWORD есть пробел — Яндекс показывает пароль приложения группами через пробел, вставь без пробелов")
    cp = (env.get("CAL_PROVIDER") or "none").lower()
    if cp in kitlib.CALDAV_PRESETS or cp == "custom":
        for k in ("CALDAV_PASSWORD",):
            if not env.get(k):
                problems.append(f"не заполнено {k} (у Яндекса — отдельный пароль приложения типа «Календарь»)")
    elif cp == "google":
        cred = Path(env.get("GCAL_CREDENTIALS_PATH") or "~/.config/mail-calendar-kit/gcal_credentials.json").expanduser()
        tok = Path(env.get("GCAL_TOKEN_PATH") or "~/.config/mail-calendar-kit/gcal_token.json").expanduser()
        res["gcal_credentials_exists"] = cred.exists()
        res["gcal_token_exists"] = tok.exists()
        if not cred.exists():
            problems.append(f"нет файла {cred} (скачать из Google Cloud Console: OAuth client → Desktop app)")
    elif cp != "none":
        problems.append(f"CAL_PROVIDER='{cp}' неизвестен (yandex/mailru/icloud/google/custom/none)")
    if res.get("mode_ok") is False:
        problems.append("права файла не 600 — выполни chmod 600")
    res["problems"] = problems
    res["send_allowed"] = kitlib.send_allowed(env)
    res["ok"] = not problems
    res["human"] = "файл доступов в порядке" if not problems else "файл доступов: " + "; ".join(problems)
    return res


# ---------- bot-detect ----------
CANDIDATE_DIRS = ["~/my-second-brain", "~/second-brain", "~/brain", "/opt/brain", "~/bridge",
                  "~/claude-code-telegram", "/opt/claude-code-telegram", "~/bot", "~/telegram-bot"]


def detect_in(d: Path) -> dict | None:
    if not d.exists():
        return None
    # стек B: бридж на claude-agent-sdk
    for f in (d / "pyproject.toml", d / "requirements.txt"):
        if f.exists():
            try:
                t = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                t = ""
            if "claude-agent-sdk" in t or "claude_agent_sdk" in t or "claude-code-sdk" in t:
                return {"stack": "B", "dir": str(d), "bot_file": None,
                        "env_file": str(d / ".env") if (d / ".env").exists() else None}
    if (d / "src" / "claude" / "sdk_integration.py").exists():
        return {"stack": "B", "dir": str(d), "bot_file": None,
                "env_file": str(d / ".env") if (d / ".env").exists() else None}
    # стек A: python-telegram-bot + anthropic
    for cand in (d / "bot" / "main.py", d / "main.py", d / "bot.py"):
        if cand.exists():
            try:
                t = cand.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                t = ""
            if "anthropic" in t and ("telegram" in t):
                venv = d / "venv" / "bin" / "python"
                return {"stack": "A", "dir": str(d), "bot_file": str(cand),
                        "venv_python": str(venv) if venv.exists() else None,
                        "env_file": str(d / ".env") if (d / ".env").exists() else None,
                        "has_tools_already": "KIT_TOOLS" in t or "tools=" in t}
    return None


def cmd_bot_detect(args) -> dict:
    dirs = [Path(x).expanduser() for x in (args.dir or [])] + [Path(x).expanduser() for x in CANDIDATE_DIRS]
    home = Path.home()
    try:
        for child in home.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                dirs.append(child)
                if (child / "bridge").is_dir():
                    dirs.append(child / "bridge")
    except Exception:
        pass
    seen, found = set(), []
    for d in dirs:
        rd = str(d.resolve()) if d.exists() else str(d)
        if rd in seen:
            continue
        seen.add(rd)
        r = detect_in(d)
        if r:
            found.append(r)
    services = []
    if platform.system() == "Linux" and shutil.which("systemctl"):
        rc, outp = run(["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--plain", "--no-legend"], timeout=15)
        for line in outp.splitlines():
            name = line.split()[0] if line.split() else ""
            if any(k in name.lower() for k in ("bot", "brain", "bridge", "claude")):
                services.append(name)
    primary = found[0] if found else {"stack": "none"}
    res = {"stack": primary["stack"], "primary": primary, "all_found": found, "services": services}
    if primary["stack"] == "A":
        res["human"] = f"бот стека A (python-telegram-bot + Anthropic API) в {primary['dir']}"
    elif primary["stack"] == "B":
        res["human"] = f"бот стека B (бридж на Claude Code) в {primary['dir']} — код править не нужно"
    else:
        res["human"] = "личный бот не найден в стандартных папках (это нормально, если урок про бота ещё впереди)"
    if services:
        res["human"] += f" · systemd: {', '.join(services)}"
    res["ok"] = True
    return res


def main():
    p = kitlib.JsonArgumentParser(description="аудит окружения пака")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("system"); s.add_argument("--ssh-host"); s.add_argument("--ssh-port", type=int)
    e = sub.add_parser("env"); e.add_argument("--path")
    b = sub.add_parser("bot-detect"); b.add_argument("--dir", action="append")
    a = sub.add_parser("all"); a.add_argument("--ssh-host"); a.add_argument("--ssh-port", type=int); a.add_argument("--path"); a.add_argument("--dir", action="append")
    args = p.parse_args()
    if args.cmd == "system":
        kitlib.out(cmd_system(args))
    elif args.cmd == "env":
        r = cmd_env(args)
        kitlib.out(r, kitlib.EXIT_OK if r.get("ok") else kitlib.EXIT_CONFIG)
    elif args.cmd == "bot-detect":
        kitlib.out(cmd_bot_detect(args))
    else:
        res = {"system": cmd_system(args), "env": cmd_env(args), "bot": cmd_bot_detect(args)}
        res["human"] = " | ".join(res[k]["human"] for k in ("system", "env", "bot"))
        kitlib.out(res)


if __name__ == "__main__":
    main()
