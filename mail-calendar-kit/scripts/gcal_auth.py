#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gcal_auth.py — одноразовая авторизация в Google Calendar (OAuth, приложение типа «Desktop app»).

  init [--credentials PATH]   открыть браузер, получить согласие, сохранить токен в GCAL_TOKEN_PATH (600)
  check                       обновить токен при необходимости и показать список календарей
  where                       пути к credentials/token (чтобы скопировать токен на сервер)

Делается ОДИН раз на Маке (нужен браузер). Потом файл токена копируется на сервер.
Важно: пока OAuth-приложение в Google Cloud в статусе «Testing», токен живёт 7 дней —
нажми «Publish app» в настройках OAuth consent screen, и токен станет постоянным.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def paths(env, args):
    cred = Path(getattr(args, "credentials", None) or env.get("GCAL_CREDENTIALS_PATH")
                or "~/.config/mail-calendar-kit/gcal_credentials.json").expanduser()
    tok = Path(env.get("GCAL_TOKEN_PATH") or "~/.config/mail-calendar-kit/gcal_token.json").expanduser()
    return cred, tok


def cmd_init(env, args):
    cred, tok = paths(env, args)
    if not cred.exists():
        kitlib.fail(kitlib.EXIT_CONFIG,
                    f"нет файла {cred}. Скачай его из Google Cloud Console (APIs & Services → Credentials → OAuth client ID → Desktop app → Download JSON) и положи по этому пути")
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except Exception:
        kitlib.fail(kitlib.EXIT_CONFIG, "не установлен google-auth-oauthlib — запусти setup_venv.sh")
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(cred), SCOPES)
        # authorization_prompt_message="" — иначе библиотека печатает ссылку с client_id прямо в stdout
        # и ломает правило «ровно один JSON».
        creds = flow.run_local_server(port=0, open_browser=True, prompt="consent",
                                      authorization_prompt_message="")
    except Exception as ex:
        kitlib.fail(kitlib.EXIT_AUTH, f"авторизация не завершилась: {str(ex)[:200]}. Это делается на компьютере с браузером, не на сервере")
    tok.parent.mkdir(parents=True, exist_ok=True)
    tok.write_text(creds.to_json(), encoding="utf-8")
    os.chmod(tok, 0o600)
    kitlib.out({"token_path": str(tok), "has_refresh_token": bool(creds.refresh_token),
                "human": f"токен сохранён в {tok}" + ("" if creds.refresh_token else " — без refresh_token: удали доступ приложения в аккаунте Google и повтори init")})


def cmd_check(env, args):
    cred, tok = paths(env, args)
    if not tok.exists():
        kitlib.fail(kitlib.EXIT_AUTH, f"нет токена {tok} — сначала gcal_auth.py init")
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except Exception:
        kitlib.fail(kitlib.EXIT_CONFIG, "не установлены модули Google — запусти setup_venv.sh")
    creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
    refreshed = False
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                tok.write_text(creds.to_json(), encoding="utf-8")
                refreshed = True
            except Exception as ex:
                kitlib.fail(kitlib.EXIT_AUTH, f"токен не обновился ({str(ex)[:120]}). Если приложение в статусе Testing — «Publish app» и повторить init")
        else:
            kitlib.fail(kitlib.EXIT_AUTH, "токен недействителен — повтори gcal_auth.py init")
    svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
    items = svc.calendarList().list().execute().get("items", [])
    cals = [{"name": i.get("summary"), "id": i.get("id"), "primary": i.get("primary", False)} for i in items]
    kitlib.out({"refreshed": refreshed, "calendars": cals,
                "human": f"Google Calendar доступен, календарей: {len(cals)}" + (" (токен обновлён)" if refreshed else "")})


def cmd_where(env, args):
    cred, tok = paths(env, args)
    kitlib.out({"credentials": str(cred), "credentials_exists": cred.exists(), "token": str(tok), "token_exists": tok.exists(),
                "human": f"токен: {tok} ({'есть' if tok.exists() else 'нет'}); на сервер копировать только токен, права 600"})


def main():
    p = kitlib.JsonArgumentParser(description="OAuth для Google Calendar")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init"); i.add_argument("--credentials")
    sub.add_parser("check"); sub.add_parser("where")
    args = p.parse_args()
    env = kitlib.load_env(required=False)
    kitlib.run_cli({"init": cmd_init, "check": cmd_check, "where": cmd_where}[args.cmd], env, args)


if __name__ == "__main__":
    main()
