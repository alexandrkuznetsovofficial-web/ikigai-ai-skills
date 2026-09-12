#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kit_tools.py — инструменты почты и календаря для личного бота (стек A: python-telegram-bot + Anthropic API).

Этот файл копируется в папку бота рядом с main.py (скриптом bot_tools_patch.py) и подключается так:

    from kit_tools import KIT_TOOLS, KIT_SYSTEM_RULES, run_kit_tool, has_pending, execute_pending, cancel_pending

Как работает:
  * KIT_TOOLS — описания инструментов для Claude (tool_use);
  * run_kit_tool(name, input) — запускает скрипты пака через subprocess и возвращает их JSON как текст;
  * отправка письма и создание встречи — в два шага: вызов инструмента ВСЕГДА даёт только превью
    и запоминает действие; когда владелец отвечает «да», бот вызывает execute_pending(), и только
    она добавляет --confirm. Модель передать подтверждение не может — такого поля у неё нет.

Настройки берутся из переменных окружения бота (.env): MCK_PYTHON, MCK_DIR, MCK_ENV.
"""
import json
import os
import subprocess
import time
from pathlib import Path

# Имена переменных свои у каждого пака: KIT_* было бы общим на два пака и приводило бы
# к запуску скриптов почты из окружения Telegram. Старые имена поддерживаются как запасные.
_VENV = Path.home() / ".venvs" / "mck"
_DEFAULT_PY = _VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
KIT_PYTHON = (os.environ.get("MCK_PYTHON") or os.environ.get("KIT_PYTHON") or str(_DEFAULT_PY))
KIT_DIR = (os.environ.get("MCK_DIR") or os.environ.get("KIT_DIR")
           or str(Path.home() / ".claude" / "skills" / "mail-calendar-kit"))
MCK_ENV = os.environ.get("MCK_ENV") or str(Path.home() / ".config" / "mail-calendar-kit" / ".env")
TIMEOUT = 90

YES_WORDS = {"да", "yes", "ок", "ok", "окей", "подтверждаю", "давай", "отправляй", "создавай", "поехали", "+"}
NO_WORDS = {"нет", "no", "отмена", "отмени", "стоп", "не надо"}

def kit_now_line() -> str:
    """Без этой строки бот не знает, какое сегодня число, и «во вторник» превращается в лотерею."""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        tz_name = _env_value("TZ") or "Europe/Moscow"
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:
        tz_name, now = "местное время", datetime.now()
    wd = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][now.weekday()]
    return (f"Сейчас {now.strftime('%d.%m.%Y')}, {wd}, {now.strftime('%H:%M')} ({tz_name}). "
            f"От этой точки считай «завтра», «во вторник», «через неделю». "
            f"Год подставляй сам и никогда не спрашивай его у владельца.")


def _env_value(key: str) -> str:
    """Одно значение из файла доступов, без разбора всего файла."""
    try:
        for raw in Path(MCK_ENV).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith(key + "=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def kit_rules() -> str:
    """Правила плюс сегодняшняя дата. Вызывается на каждый запрос, не константа."""
    return KIT_SYSTEM_RULES + "\n" + kit_now_line()


KIT_SYSTEM_RULES = (
    "У тебя есть инструменты почты и календаря владельца. Правила:\n"
    "1) адрес email участника берёшь только из слов владельца или из его памяти; никогда не придумывай адрес — "
    "если адреса нет, спроси;\n"
    "2) инструменты отправки письма и создания встречи всегда возвращают ТОЛЬКО превью — покажи его владельцу "
    "и попроси ответить «да». Отправку выполняет сам бот, когда владелец ответил; у тебя такой возможности нет. "
    "Не пиши «отправлено» никогда: это делает не твой вызов;\n"
    "3) даты и время считай в часовом поясе владельца; формат для инструментов: 2026-09-12T15:00;\n"
    "4) перенос и отмена встречи работают так же, как создание: инструмент даёт превью, "
    "решение принимает владелец, выполняет бот. Номер встречи (uid) бери из cal_find или cal_list, "
    "никогда не придумывай его сам;\n"
    "5) если инструмент вернул ok=false — перескажи его human-строку, не выдумывай причин."
)

KIT_TOOLS = [
    {"name": "mail_unread", "description": "Непрочитанные письма во Входящих: uid, дата, от кого, тема.",
     "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 10}}}},
    {"name": "mail_search",
     "description": "Поиск писем по отправителю, теме, тексту и дате. Возвращает заголовки с uid (для mail_read).",
     "input_schema": {"type": "object", "properties": {
         "from": {"type": "string", "description": "часть адреса или имени отправителя"},
         "subject": {"type": "string"}, "text": {"type": "string"},
         "days": {"type": "integer", "description": "за сколько последних дней, по умолчанию 30"},
         "limit": {"type": "integer", "default": 10}}}},
    {"name": "mail_read", "description": "Прочитать письмо целиком по uid из mail_search/mail_unread.",
     "input_schema": {"type": "object", "properties": {"uid": {"type": "string"}, "max_chars": {"type": "integer", "default": 3000}},
                      "required": ["uid"]}},
    {"name": "mail_send",
     "description": "Подготовить письмо и показать владельцу превью. Отправку выполнит бот после ответа «да» — сам ты отправить не можешь.",
     "input_schema": {"type": "object", "properties": {
         "to": {"type": "string", "description": "адрес получателя (только из слов владельца)"},
         "subject": {"type": "string"}, "body": {"type": "string"},
         "reply_uid": {"type": "string", "description": "uid письма, на которое отвечаем (необязательно)"}},
         "required": ["to", "body"]}},
    {"name": "cal_today", "description": "События сегодня.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "cal_list", "description": "События на N дней вперёд (по умолчанию 7).",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer", "default": 7}}}},
    {"name": "cal_freeslots", "description": "Свободные окна в рабочие часы.",
     "input_schema": {"type": "object", "properties": {
         "days": {"type": "integer", "default": 7}, "duration": {"type": "integer", "default": 60},
         "weekdays": {"type": "boolean", "default": False}}}},
    {"name": "cal_find",
     "description": "Найти встречу по названию и получить её номер (uid) — он нужен для переноса и отмены.",
     "input_schema": {"type": "object", "properties": {
         "text": {"type": "string"},
         "days": {"type": "integer", "description": "на сколько дней вперёд смотреть, по умолчанию 90"}},
         "required": ["text"]}},
    {"name": "cal_move",
     "description": "Подготовить перенос встречи на другое время и показать владельцу превью. "
                    "Перенесёт бот после ответа «да». Номер встречи бери из cal_find.",
     "input_schema": {"type": "object", "properties": {
         "uid": {"type": "string", "description": "номер встречи из cal_find"},
         "start": {"type": "string", "description": "новое время, 2026-09-15T15:00"},
         "duration": {"type": "integer", "description": "если нужно изменить длительность"}},
         "required": ["uid", "start"]}},
    {"name": "cal_delete",
     "description": "Подготовить отмену встречи и показать владельцу превью с её названием и временем. "
                    "Удалит бот после ответа «да». Номер встречи бери из cal_find.",
     "input_schema": {"type": "object", "properties": {
         "uid": {"type": "string", "description": "номер встречи из cal_find"}}, "required": ["uid"]}},
    {"name": "cal_create",
     "description": "Подготовить встречу и показать владельцу превью. Создаст её бот после ответа «да» — сам ты создать не можешь.",
     "input_schema": {"type": "object", "properties": {
         "start": {"type": "string", "description": "2026-09-12T15:00"},
         "duration": {"type": "integer", "default": 60}, "summary": {"type": "string"},
         "location": {"type": "string"}, "description": {"type": "string"},
         "attendees": {"type": "array", "items": {"type": "string"}, "description": "email участников только из слов владельца"},
         "invite": {"type": "boolean", "default": False, "description": "разослать приглашения участникам"}},
         "required": ["start", "summary"]}},
]

_PENDING = {"name": None, "input": None, "ts": 0}


def _run(script: str, argv: list[str]) -> str:
    cmd = [KIT_PYTHON, str(Path(KIT_DIR) / "scripts" / script)] + argv
    env = dict(os.environ)
    env["MCK_ENV"] = MCK_ENV
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, env=env)
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "human": f"скрипт {script} не ответил за {TIMEOUT} с"}, ensure_ascii=False)
    except Exception as ex:
        return json.dumps({"ok": False, "human": f"не удалось запустить {script}: {ex}"}, ensure_ascii=False)
    out = (r.stdout or "").strip()
    if not out:
        return json.dumps({"ok": False, "human": f"{script} вернул пусто (код {r.returncode}): {(r.stderr or '')[-300:]}"},
                          ensure_ascii=False)
    return out.splitlines()[-1]


def _mail_args(inp: dict) -> list[str]:
    a = []
    for key, flag in (("from", "--from"), ("subject", "--subject"), ("text", "--text")):
        if inp.get(key):
            a += [flag, str(inp[key])]
    if inp.get("days"):
        a += ["--days", str(_int(inp["days"], 30))]
    a += ["--limit", str(_int(inp.get("limit"), 10))]
    a.append("--all-folders")   # письмо часто лежит не во «Входящих»
    return a


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def run_kit_tool(name: str, inp: dict) -> str:
    """Любой кривой ввод от модели превращается в JSON с объяснением, а не в падение бота."""
    inp = inp or {}
    try:
        return _dispatch(name, inp)
    except Exception as ex:
        return json.dumps({"ok": False, "human": f"инструмент {name} не отработал: {type(ex).__name__} {str(ex)[:160]}"},
                          ensure_ascii=False)


def _dispatch(name: str, inp: dict) -> str:
    if name == "mail_unread":
        return _run("mail_cli.py", ["unread", "--limit", str(_int(inp.get("limit"), 10))])
    if name == "mail_search":
        return _run("mail_cli.py", ["search"] + _mail_args(inp))
    if name == "mail_read":
        uid = str(inp.get("uid") or "").strip()
        if not uid.isdigit():
            return json.dumps({"ok": False, "human": "нужен номер письма (uid) из поиска или списка непрочитанных"},
                              ensure_ascii=False)
        return _run("mail_cli.py", ["read", "--uid", uid, "--all-folders",
                                    "--max-chars", str(_int(inp.get("max_chars"), 3000))])
    if name == "cal_today":
        return _run("cal_cli.py", ["today"])
    if name == "cal_list":
        return _run("cal_cli.py", ["list", "--days", str(_int(inp.get("days"), 7))])
    if name == "cal_freeslots":
        a = ["freeslots", "--days", str(_int(inp.get("days"), 7)), "--duration", str(_int(inp.get("duration"), 60))]
        if inp.get("weekdays"):
            a.append("--weekdays")
        return _run("cal_cli.py", a)
    if name == "cal_find":
        text = str(inp.get("text") or "").strip()
        if not text:
            return json.dumps({"ok": False, "human": "нужно название события для поиска"}, ensure_ascii=False)
        a = ["find", "--text", text]
        if inp.get("days"):
            a += ["--days", str(_int(inp["days"], 90))]
        return _run("cal_cli.py", a)
    if name in ("mail_send", "cal_create", "cal_move", "cal_delete"):
        # Подтверждение НИКОГДА не приходит от модели: она физически не может его передать.
        # Первый вызов всегда даёт превью; --confirm добавляет только execute_pending(),
        # которую вызывает код бота, увидев «да» от владельца.
        inp.pop("confirm", None)
        argv = _outbound_args(name, inp)
        _PENDING.update(name=name, input=inp, ts=time.time())
        return _run("mail_cli.py" if name == "mail_send" else "cal_cli.py", argv)
    return json.dumps({"ok": False, "human": f"неизвестный инструмент {name}"}, ensure_ascii=False)


def _outbound_args(name: str, inp: dict) -> list[str]:
    if name == "mail_send":
        to, body = str(inp.get("to") or "").strip(), str(inp.get("body") or "")
        if not to or not body.strip():
            raise ValueError("нужны адрес получателя и текст письма")
        a = ["send", "--to", to, "--body", body]
        if inp.get("subject"):
            a += ["--subject", str(inp["subject"])]
        if inp.get("reply_uid"):
            a += ["--reply-uid", str(inp["reply_uid"])]
        return a
    if name == "cal_move":
        uid, start = str(inp.get("uid") or "").strip(), str(inp.get("start") or "").strip()
        if not uid or not start:
            raise ValueError("нужны номер встречи и новое время")
        a = ["move", "--uid", uid, "--start", start]
        if inp.get("duration"):
            a += ["--duration", str(_int(inp["duration"], 60))]
        return a
    if name == "cal_delete":
        uid = str(inp.get("uid") or "").strip()
        if not uid:
            raise ValueError("нужен номер встречи из поиска")
        return ["delete", "--uid", uid]
    if not inp.get("start") or not inp.get("summary"):
        raise ValueError("нужны дата-время начала и название встречи")
    a = ["create", "--start", str(inp["start"]), "--duration", str(_int(inp.get("duration"), 60)),
         "--summary", str(inp["summary"])]
    if inp.get("location"):
        a += ["--location", str(inp["location"])]
    if inp.get("description"):
        a += ["--description", str(inp["description"])]
    for at in inp.get("attendees") or []:
        a += ["--attendee", str(at)]
    if inp.get("invite"):
        a.append("--invite")
    return a


def has_pending() -> bool:
    return bool(_PENDING["name"]) and (time.time() - _PENDING["ts"] < 15 * 60)


def cancel_pending() -> None:
    _PENDING.update(name=None, input=None, ts=0)


def execute_pending() -> str:
    """Вызывается, когда владелец ответил «да» на превью. Возвращает JSON-строку результата."""
    if not has_pending():
        return json.dumps({"ok": False, "human": "нечего подтверждать — превью устарело или не было"}, ensure_ascii=False)
    name, inp = _PENDING["name"], dict(_PENDING["input"])
    _PENDING.update(name=None, input=None, ts=0)
    argv = _outbound_args(name, inp) + ["--confirm"]
    return _run("mail_cli.py" if name == "mail_send" else "cal_cli.py", argv)


def is_yes(text: str) -> bool:
    return text.strip().lower().strip("!.") in YES_WORDS


def is_no(text: str) -> bool:
    return text.strip().lower().strip("!.") in NO_WORDS
