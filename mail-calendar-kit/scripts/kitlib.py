#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kitlib.py — общая библиотека пака «Второй мозг ↔ почта и календарь».

Правила, которые соблюдают все скрипты пака:
  * stdout — ровно один JSON-объект, в нём поле "human" — одна строка по-русски для человека;
  * коды выхода: 0 ок · 1 нет конфига / плохие аргументы · 2 не пустили (логин/пароль) ·
    3 действие требует --confirm или отключено предохранителем · 4 ошибка провайдера;
  * секреты никогда не печатаются, только маска вида "ab…yz (16 символов)".

Файл доступов: $MCK_ENV, иначе ~/.config/mail-calendar-kit/.env
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_ENV = Path.home() / ".config" / "mail-calendar-kit" / ".env"

EXIT_OK, EXIT_CONFIG, EXIT_AUTH, EXIT_CONFIRM, EXIT_PROVIDER = 0, 1, 2, 3, 4

# ---------- пресеты провайдеров (проверены по официальным справкам 11.09.2026) ----------
MAIL_PRESETS = {
    "yandex": {"imap_host": "imap.yandex.ru", "imap_port": 993,
               "smtp_host": "smtp.yandex.ru", "smtp_port": 465, "smtp_mode": "ssl",
               "imap_login": "full", "smtp_login": "full"},
    "gmail":  {"imap_host": "imap.gmail.com", "imap_port": 993,
               "smtp_host": "smtp.gmail.com", "smtp_port": 465, "smtp_mode": "ssl",
               "imap_login": "full", "smtp_login": "full"},
    "mailru": {"imap_host": "imap.mail.ru", "imap_port": 993,
               "smtp_host": "smtp.mail.ru", "smtp_port": 465, "smtp_mode": "ssl",
               "imap_login": "full", "smtp_login": "full"},
    # iCloud: IMAP-логин — имя БЕЗ домена, SMTP — полный адрес, SMTP только STARTTLS 587
    "icloud": {"imap_host": "imap.mail.me.com", "imap_port": 993,
               "smtp_host": "smtp.mail.me.com", "smtp_port": 587, "smtp_mode": "starttls",
               "imap_login": "local", "smtp_login": "full"},
}

CALDAV_PRESETS = {
    "yandex": "https://caldav.yandex.ru",
    "mailru": "https://calendar.mail.ru",
    "icloud": "https://caldav.icloud.com",
}

_WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
_MON = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


# ---------- вывод ----------
_BAD_CHARS = {c: " " for c in list(range(0x00, 0x20)) + [0x7F, 0x2028, 0x2029]}


def clean(value):
    """Чистит строки от переводов строк и управляющих символов: JSON должен оставаться одной строкой.
    Письма и события приносят произвольный текст, поэтому это делается для всего вывода."""
    if isinstance(value, str):
        return " ".join(value.translate(_BAD_CHARS).split())
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def out(obj: dict, code: int = EXIT_OK):
    """Единственный способ печатать результат: один JSON в одну строку и выход."""
    obj.setdefault("ok", code == EXIT_OK)
    sys.stdout.write(json.dumps(clean(obj), ensure_ascii=False) + "\n")
    sys.stdout.flush()
    sys.exit(code)


def fail(code: int, human: str, **extra):
    obj = {"ok": False, "human": human}
    obj.update(extra)
    out(obj, code)


class JsonArgumentParser(argparse.ArgumentParser):
    """argparse по умолчанию пишет usage в stderr и выходит с кодом 2 — это ломает контракт:
    бот видит пустой stdout и читает код 2 как «не пустили по паролю». Здесь любая ошибка
    разбора аргументов превращается в обычный JSON с кодом 1."""

    def error(self, message):
        fail(EXIT_CONFIG, f"не понял команду: {message}. Посмотри список команд в начале файла скрипта.")

    def exit(self, status=0, message=None):
        if status != 0:
            fail(EXIT_CONFIG, f"не понял команду: {(message or '').strip() or 'проверь имя команды и флаги'}")
        sys.exit(0)


def run_cli(func, *args, **kwargs):
    """Единственная точка входа: что бы ни случилось, наружу уходит JSON, а не трассировка."""
    try:
        func(*args, **kwargs)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        fail(EXIT_CONFIG, "прервано с клавиатуры")
    except Exception as ex:
        fail(EXIT_PROVIDER, f"неожиданная ошибка ({type(ex).__name__}): {str(ex)[:200]}")


def mask(value: str) -> str:
    if not value:
        return "(пусто)"
    if len(value) <= 4:
        return "•" * len(value)
    return f"{value[:2]}…{value[-2:]} ({len(value)} символов)"


# ---------- конфиг ----------
def env_path() -> Path:
    p = os.environ.get("MCK_ENV")
    return Path(p).expanduser() if p else DEFAULT_ENV


def load_env(required: bool = True) -> dict:
    """Читает .env как плоский словарь. Пустые значения = ключ есть, значение ''. Без print."""
    path = env_path()
    if not path.exists():
        if required:
            fail(EXIT_CONFIG,
                 f"нет файла доступов {path}. Скопируй scripts/env.example туда и заполни.",
                 env_path=str(path))
        return {}
    env = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    # Переменные окружения процесса могут переопределить настройки — но НЕ предохранитель:
    # иначе один `export` включил бы отправку для всей сессии в обход файла доступов.
    for k in list(env.keys()) + ["TZ"]:
        if k == "MCK_SEND_ALLOWED":
            continue
        if k in os.environ and os.environ[k] != "":
            env[k] = os.environ[k]
    return env


def get_tz(env: dict):
    for name in (env.get("TZ") or "Europe/Moscow", "Europe/Moscow", "UTC"):
        try:
            return ZoneInfo(name)
        except Exception:
            continue
    from datetime import timezone
    return timezone.utc  # база часовых поясов недоступна — работаем в UTC, но не падаем


def resolve_mail(env: dict) -> dict:
    """Собирает параметры IMAP/SMTP из пресета и переопределений."""
    provider = (env.get("MAIL_PROVIDER") or "").strip().lower()
    user = (env.get("MAIL_USER") or "").strip()
    password = env.get("MAIL_PASSWORD") or ""
    if not user or not password:
        fail(EXIT_CONFIG, "в файле доступов не заполнены MAIL_USER и/или MAIL_PASSWORD")
    if provider in MAIL_PRESETS:
        cfg = dict(MAIL_PRESETS[provider])
    elif provider == "custom":
        cfg = {"imap_host": env.get("IMAP_HOST"), "imap_port": int(env.get("IMAP_PORT") or 993),
               "smtp_host": env.get("SMTP_HOST"), "smtp_port": int(env.get("SMTP_PORT") or 465),
               "smtp_mode": (env.get("SMTP_MODE") or "ssl").lower(),
               "imap_login": "full", "smtp_login": "full"}
        if not cfg["imap_host"] or not cfg["smtp_host"]:
            fail(EXIT_CONFIG, "для MAIL_PROVIDER=custom нужны IMAP_HOST и SMTP_HOST")
    else:
        fail(EXIT_CONFIG, f"неизвестный MAIL_PROVIDER='{provider}'. Допустимо: yandex, gmail, mailru, icloud, custom")
    # точечные переопределения поверх пресета
    for k_env, k_cfg, cast in (("IMAP_HOST", "imap_host", str), ("IMAP_PORT", "imap_port", int),
                               ("SMTP_HOST", "smtp_host", str), ("SMTP_PORT", "smtp_port", int),
                               ("SMTP_MODE", "smtp_mode", str)):
        v = env.get(k_env)
        if v:
            cfg[k_cfg] = cast(v)
    local = user.split("@", 1)[0]
    cfg["provider"] = provider
    cfg["user"] = user
    cfg["imap_user"] = local if cfg["imap_login"] == "local" else user
    cfg["smtp_user"] = user
    cfg["password"] = password
    cfg["from_name"] = env.get("MAIL_FROM_NAME") or ""
    return cfg


def resolve_cal(env: dict) -> dict:
    provider = (env.get("CAL_PROVIDER") or "none").strip().lower()
    if provider == "none":
        fail(EXIT_CONFIG, "CAL_PROVIDER=none: календарь не подключён. Заполни CAL_PROVIDER в файле доступов.")
    if provider in ("ics_link", "google_ical"):
        # Один путь на все календари, умеющие отдавать ссылку .ics: секретный адрес Google,
        # открытый адрес календаря iCloud, публичная ссылка Яндекса. Только чтение.
        url = (env.get("CALENDAR_ICS_URL") or env.get("GCAL_ICS_URL") or "").strip()
        if not url:
            fail(EXIT_CONFIG, "для CAL_PROVIDER=ics_link нужен CALENDAR_ICS_URL — ссылка на календарь в формате iCal "
                              "(у Google это «Секретный адрес в формате iCal», у Apple — ссылка открытого календаря)")
        if url.startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]   # webcal — тот же https, так отдают ссылку Apple и Яндекс
        if not url.startswith("http"):
            fail(EXIT_CONFIG, "ссылка на календарь должна начинаться с https:// или webcal:// — скопируй её целиком")
        return {"provider": "ics_link", "ics_url": url, "readonly": True}
    if provider == "google":
        return {"provider": "google",
                "credentials": str(Path(env.get("GCAL_CREDENTIALS_PATH") or "~/.config/mail-calendar-kit/gcal_credentials.json").expanduser()),
                "token": str(Path(env.get("GCAL_TOKEN_PATH") or "~/.config/mail-calendar-kit/gcal_token.json").expanduser()),
                "calendar_id": env.get("GCAL_CALENDAR_ID") or "primary"}
    if provider not in CALDAV_PRESETS and provider != "custom":
        fail(EXIT_CONFIG, f"неизвестный CAL_PROVIDER='{provider}'. "
                          f"Допустимо: yandex, mailru, icloud, google, ics_link, custom, none")
    url = (env.get("CALDAV_URL") or CALDAV_PRESETS.get(provider) or "").strip()
    user = (env.get("CALDAV_USER") or env.get("MAIL_USER") or "").strip()
    password = env.get("CALDAV_PASSWORD") or ""
    if provider == "custom" and not url:
        fail(EXIT_CONFIG, "для CAL_PROVIDER=custom нужен CALDAV_URL")
    if not user or not password:
        fail(EXIT_CONFIG, "в файле доступов не заполнены CALDAV_USER и/или CALDAV_PASSWORD "
                          "(у Яндекса это отдельный пароль приложения типа «Календарь»)")
    return {"provider": provider, "url": url, "user": user, "password": password,
            "calendar": (env.get("CALDAV_CALENDAR") or "").strip()}


def send_allowed(env: dict) -> bool:
    """Разрешение на отправку читается ТОЛЬКО из файла доступов, не из окружения."""
    path = env_path()
    if not path.exists():
        return False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("MCK_SEND_ALLOWED") and "=" in line:
            return line.split("=", 1)[1].strip().strip('"').strip("'") == "1"
    return False


# ---------- даты ----------
def fmt_dt(dt: datetime, tz: ZoneInfo) -> str:
    """'Чт 12 сен · 15:00'"""
    dt = dt.astimezone(tz)
    return f"{_WD[dt.weekday()]} {dt.day} {_MON[dt.month - 1]} · {dt.strftime('%H:%M')}"


def fmt_day(dt: datetime, tz: ZoneInfo) -> str:
    dt = dt.astimezone(tz)
    return f"{_WD[dt.weekday()]} {dt.day} {_MON[dt.month - 1]}"


def parse_local(s: str, tz: ZoneInfo) -> datetime:
    """Принимает '2026-09-12T15:00', '2026-09-12 15:00', '12.09.2026 15:00', '2026-09-12' (00:00)."""
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=tz)
        except ValueError:
            continue
    raise ValueError(f"не понял дату '{s}'. Формат: 2026-09-12T15:00 или 12.09.2026 15:00")
