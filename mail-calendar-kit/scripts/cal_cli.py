#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cal_cli.py — календарь второго мозга. Бэкенд по CAL_PROVIDER:
  yandex / mailru / icloud / custom → CalDAV с паролем приложения (discovery, без хардкода путей)
  google                            → Google Calendar API с OAuth-токеном (см. gcal_auth.py)

Команды:
  check                                   вход и список календарей
  calendars
  today                                   события сегодня
  list (--days N | --from D --to D)       события в диапазоне (по умолчанию 7 дней вперёд)
  freeslots [--days 7] [--from-hour 10] [--to-hour 19] [--duration 60] [--step 60]
            [--lead-hours 3] [--weekdays] [--limit 15]
  find --text T [--from D --to D]         поиск по названию/описанию (по умолчанию −30…+90 дней)
  create --start D (--duration 60 | --end D) --summary S [--location L] [--description T]
         [--attendee EMAIL ...] [--invite] [--confirm]
  move --uid U --start D [--duration N] [--confirm]    перенести встречу на другое время
  delete --uid U [--from D --to D] [--confirm]

Даты: 2026-09-12T15:00 · 2026-09-12 15:00 · 12.09.2026 15:00 · 12.09.2026 (весь день с 00:00)

Безопасность:
  * create/delete без --confirm — превью и код 3;
  * --invite (письмо-приглашение участникам) работает только при MCK_SEND_ALLOWED=1;
  * адреса участников берутся только из слов владельца — скрипт их не придумывает.
"""
import argparse
import os
import re
import smtplib
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ======================================================================
#  CalDAV backend
# ======================================================================
class CalDavBackend:
    def __init__(self, cfg: dict, tz):
        import caldav  # noqa
        self.caldav = caldav
        self.cfg, self.tz = cfg, tz
        try:
            self.client = caldav.DAVClient(url=cfg["url"], username=cfg["user"], password=cfg["password"])
            self.principal = self.client.principal()
            self.calendars = self.principal.calendars()
        except Exception as ex:
            text = str(ex)
            if "401" in text or "Unauthorized" in text or "403" in text:
                hint = {"yandex": "у Яндекса это отдельный пароль приложения типа «Календарь», и он начинает действовать через 2–3 часа после создания — если только что создал, это норма, вернись позже",
                        "icloud": "у iCloud нужен app-specific password, а не обычный пароль",
                        "mailru": "у Mail.ru при включённой 2FA нужен «пароль для внешнего приложения»"}.get(cfg["provider"], "проверь логин и пароль приложения")
                kitlib.fail(kitlib.EXIT_AUTH, f"календарь не пустил (401). {hint}")
            kitlib.fail(kitlib.EXIT_PROVIDER, f"не могу открыть CalDAV {cfg['url']}: {text[:200]}")
        if not self.calendars:
            kitlib.fail(kitlib.EXIT_PROVIDER, "на аккаунте не найдено ни одного календаря")
        self.cal = self._pick(cfg.get("calendar"))

    def _pick(self, name):
        if name:
            for c in self.calendars:
                if (self._name(c) or "").strip().lower() == name.strip().lower():
                    return c
            kitlib.fail(kitlib.EXIT_CONFIG, f"календарь «{name}» не найден; есть: " + ", ".join(self._name(c) or "?" for c in self.calendars))
        return self.calendars[0]

    @staticmethod
    def _name(c):
        try:
            return c.get_display_name()
        except Exception:
            try:
                return c.name
            except Exception:
                return None

    def list_calendars(self) -> list[dict]:
        return [{"name": self._name(c), "url": str(c.url)} for c in self.calendars]

    def _to_dt(self, v):
        if isinstance(v, datetime):
            return v.astimezone(self.tz) if v.tzinfo else v.replace(tzinfo=self.tz)
        if isinstance(v, date):
            return datetime(v.year, v.month, v.day, tzinfo=self.tz)
        return None

    def events(self, start: datetime, end: datetime) -> list[dict]:
        try:
            results = self.cal.search(start=start, end=end, event=True, expand=True)
        except Exception:
            try:
                results = self.cal.date_search(start=start, end=end, expand=True)
            except Exception as ex:
                kitlib.fail(kitlib.EXIT_PROVIDER, f"не удалось прочитать события: {str(ex)[:200]}")
        out = []
        for ev in results:
            try:
                comp = ev.icalendar_component
            except Exception:
                comp = None
            if comp is None:
                continue
            ds = comp.get("dtstart")
            if ds is None:
                continue
            allday = not isinstance(ds.dt, datetime)
            s = self._to_dt(ds.dt)
            de = comp.get("dtend")
            e = self._to_dt(de.dt) if de is not None else (s + timedelta(days=1) if allday else s + timedelta(hours=1))
            out.append({"uid": str(comp.get("uid") or ""), "summary": str(comp.get("summary") or "(без названия)"),
                        "start": s, "end": e, "allday": allday,
                        "location": str(comp.get("location") or ""), "description": str(comp.get("description") or ""),
                        "_obj": ev})
        out.sort(key=lambda x: x["start"])
        return out

    def create(self, ev: dict, invite: bool = False) -> dict:
        """invite=False → на сервер кладётся обычное событие (PUBLISH, без участников):
        иначе сервер с поддержкой планирования разошлёт приглашения сам, в обход предохранителя.
        Участники нужны только в том ICS, который уходит письмом."""
        ics = build_ics(ev, self.cfg["user"], with_attendees=invite)
        try:
            self.cal.save_event(ics.decode())
        except Exception as ex:
            kitlib.fail(kitlib.EXIT_PROVIDER, f"событие не сохранилось: {str(ex)[:200]}")
        return {"calendar": True, "ics": ics}

    def find_raw(self, uid: str, start: datetime, end: datetime):
        """Поиск БЕЗ expand: у развёрнутого экземпляра повтора uid совпадает с мастер-событием,
        и удаление снесло бы всю серию."""
        try:
            results = self.cal.search(start=start, end=end, event=True, expand=False)
        except Exception:
            try:
                results = self.cal.date_search(start=start, end=end, expand=False)
            except Exception as ex:
                kitlib.fail(kitlib.EXIT_PROVIDER, f"не удалось прочитать события: {str(ex)[:200]}")
        for ev in results:
            try:
                comp = ev.icalendar_component
            except Exception:
                continue
            if comp is None or str(comp.get("uid") or "") != uid:
                continue
            ds = comp.get("dtstart")
            s = self._to_dt(ds.dt) if ds is not None else None
            recurring = bool(comp.get("rrule") or comp.get("rdate"))
            de = comp.get("dtend")
            e = self._to_dt(de.dt) if de is not None else None
            return {"obj": ev, "summary": str(comp.get("summary") or "(без названия)"),
                    "start": s, "end": e, "recurring": recurring,
                    "location": str(comp.get("location") or ""),
                    "description": str(comp.get("description") or "")}
        return None

    def delete(self, uid: str, start: datetime, end: datetime) -> bool:
        found = self.find_raw(uid, start, end)
        if not found:
            return False
        if found["recurring"]:
            kitlib.fail(kitlib.EXIT_CONFIRM,
                        f"«{found['summary']}» — повторяющееся событие: удаление снесёт всю серию, "
                        f"а не один день. Не удаляю. Отмени нужную встречу в календаре вручную.")
        try:
            found["obj"].delete()
            return True
        except Exception as ex:
            kitlib.fail(kitlib.EXIT_PROVIDER, f"не удалось удалить: {str(ex)[:200]}")
        return False


def build_ics(ev: dict, organizer: str, with_attendees: bool) -> bytes:
    """Один сборщик .ics на все пути. with_attendees=True → METHOD:REQUEST, то есть приглашение.
    На сервер такое кладут только осознанно: сервер с планированием разошлёт письма сам."""
    from icalendar import Calendar, Event
    cal = Calendar()
    cal.add("prodid", "-//mail-calendar-kit//RU")
    cal.add("version", "2.0")
    cal.add("method", "REQUEST" if (ev["attendees"] and with_attendees) else "PUBLISH")
    e = Event()
    e.add("uid", ev["uid"])
    e.add("dtstamp", datetime.now(timezone.utc))
    e.add("dtstart", ev["start"])
    e.add("dtend", ev["end"])
    e.add("summary", ev["summary"])
    if ev.get("location"):
        e.add("location", ev["location"])
    if ev.get("description"):
        e.add("description", ev["description"])
    if ev["attendees"] and with_attendees:
        e.add("organizer", f"mailto:{organizer}")
        for a in ev["attendees"]:
            e.add("attendee", f"mailto:{a}", parameters={"RSVP": "TRUE", "ROLE": "REQ-PARTICIPANT"})
    cal.add_component(e)
    return cal.to_ical()


# ======================================================================
#  Календарь по секретному адресу iCal (Google и любой другой) — только чтение
# ======================================================================
class IcsUrlBackend:
    """Чтение календаря по ссылке .ics — работает с Google, Apple и Яндексом одинаково.

    Зачем: у Google полный доступ включается через консоль разработчика, это двадцать минут
    и пять экранов, на которых новички отваливаются. Ссылка копируется за минуту и сразу даёт
    «что у меня сегодня», «найди окно», «когда была та встреча». Создавать встречи по ней нельзя."""

    CACHE_TTL = 600  # календарь перечитывается не чаще раза в 10 минут

    def __init__(self, cfg: dict, tz, fresh: bool = False):
        self.cfg, self.tz = cfg, tz
        self.stale = False
        raw = self._load(fresh)
        try:
            from icalendar import Calendar as ICal
            self.cal = ICal.from_ical(raw)
        except Exception as ex:
            kitlib.fail(kitlib.EXIT_PROVIDER, f"адрес открылся, но разобрать календарь не вышло: {str(ex)[:160]}")
        self.name = str(self.cal.get("X-WR-CALNAME") or "календарь")

    def _cache_file(self):
        return kitlib.env_path().parent / "calendar_ics_cache.ics"

    def _load(self, fresh: bool) -> bytes:
        import urllib.error
        import urllib.request
        cache = self._cache_file()
        if not fresh and cache.exists() and (time.time() - cache.stat().st_mtime) < self.CACHE_TTL:
            return cache.read_bytes()
        req = urllib.request.Request(self.cfg["ics_url"], headers={"User-Agent": "mail-calendar-kit"})
        # Python в отдельном окружении на Маке не видит системные сертификаты и падает на https.
        # Поэтому берём набор корневых сертификатов из certifi — он ставится вместе с паком.
        ctx = None
        try:
            import ssl

            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = None
        try:
            with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
                data = r.read()
        except urllib.error.HTTPError as ex:
            if ex.code in (401, 403, 404):
                kitlib.fail(kitlib.EXIT_AUTH,
                            f"календарь по этой ссылке не открывается (код {ex.code}). Нужна ссылка именно "
                            f"на календарь в формате iCal, а не адрес из строки браузера: у Google это "
                            f"«Секретный адрес в формате iCal», у Apple — ссылка открытого календаря. "
                            f"Если ссылку недавно сбрасывали, она сменилась — возьми новую.")
            kitlib.fail(kitlib.EXIT_PROVIDER, f"календарь не отдался: HTTP {ex.code}")
        except Exception as ex:
            if cache.exists():
                self.stale = True
                return cache.read_bytes()
            hint = ""
            if "CERTIFICATE_VERIFY_FAILED" in str(ex):
                hint = (" Похоже, у Python нет набора корневых сертификатов: выполни "
                        "~/.venvs/mck/bin/python -m pip install --upgrade certifi и повтори")
            kitlib.fail(kitlib.EXIT_PROVIDER, f"не смог скачать календарь: {str(ex)[:160]}.{hint}")
        if not data.lstrip()[:15].upper().startswith(b"BEGIN:VCALENDAR"):
            kitlib.fail(kitlib.EXIT_PROVIDER,
                        "по адресу пришёл не календарь, а веб-страница. Скорее всего скопирован адрес "
                        "из браузера; нужен «Секретный адрес в формате iCal», он заканчивается на .ics")
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
            os.chmod(cache, 0o600)
        except Exception:
            pass
        return data

    def list_calendars(self) -> list[dict]:
        return [{"name": self.name, "access": "только чтение", "source": "секретный адрес iCal"}]

    def _to_dt(self, v):
        if isinstance(v, datetime):
            return v.astimezone(self.tz) if v.tzinfo else v.replace(tzinfo=self.tz)
        if isinstance(v, date):
            return datetime(v.year, v.month, v.day, tzinfo=self.tz)
        return None

    def events(self, start: datetime, end: datetime) -> list[dict]:
        try:
            import recurring_ical_events
        except ImportError:
            kitlib.fail(kitlib.EXIT_CONFIG,
                        "не установлен recurring-ical-events (он разворачивает повторяющиеся встречи) — "
                        "запусти scripts/setup_venv.sh ещё раз")
        try:
            comps = recurring_ical_events.of(self.cal).between(start, end)
        except Exception as ex:
            kitlib.fail(kitlib.EXIT_PROVIDER, f"не удалось разобрать события: {str(ex)[:160]}")
        out = []
        for c in comps:
            ds = c.get("DTSTART")
            if ds is None:
                continue
            allday = not isinstance(ds.dt, datetime)
            s = self._to_dt(ds.dt)
            de = c.get("DTEND")
            e = self._to_dt(de.dt) if de is not None else (
                s + timedelta(days=1) if allday else s + timedelta(hours=1))
            out.append({"uid": str(c.get("UID") or ""), "summary": str(c.get("SUMMARY") or "(без названия)"),
                        "start": s, "end": e, "allday": allday,
                        "location": str(c.get("LOCATION") or ""), "description": str(c.get("DESCRIPTION") or ""),
                        "_obj": None})
        out.sort(key=lambda x: x["start"])
        return out

    def create(self, ev: dict, invite: bool = False):
        kitlib.fail(kitlib.EXIT_CONFIG, "по секретному адресу календарь только читается")

    def delete(self, uid: str, start: datetime, end: datetime) -> bool:
        kitlib.fail(kitlib.EXIT_CONFIG,
                    "по секретному адресу календарь только читается: удалить встречу можно в самом Google "
                    "или подключив полный доступ (gcal_auth.py init)")


# ======================================================================
#  Google Calendar backend (по документации; машинно проверен только импорт)
# ======================================================================
class GoogleBackend:
    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    def __init__(self, cfg: dict, tz):
        self.cfg, self.tz = cfg, tz
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except Exception:
            kitlib.fail(kitlib.EXIT_CONFIG, "не установлены модули Google — запусти setup_venv.sh")
        tok = Path(cfg["token"])
        if not tok.exists():
            kitlib.fail(kitlib.EXIT_AUTH, f"нет токена {tok}. Сначала: gcal_auth.py init (один раз, с браузером)")
        creds = Credentials.from_authorized_user_file(str(tok), self.SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    tok.write_text(creds.to_json(), encoding="utf-8")
                except Exception as ex:
                    kitlib.fail(kitlib.EXIT_AUTH, f"токен Google не обновился ({str(ex)[:120]}). Если OAuth-приложение в статусе Testing, токен живёт 7 дней — нажми «Publish app» и повтори gcal_auth.py init")
            else:
                kitlib.fail(kitlib.EXIT_AUTH, "токен Google недействителен — повтори gcal_auth.py init")
        self.svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self.cal_id = cfg["calendar_id"]

    def list_calendars(self):
        items = self.svc.calendarList().list().execute().get("items", [])
        return [{"name": i.get("summary"), "id": i.get("id"), "primary": i.get("primary", False)} for i in items]

    def _parse(self, v: dict):
        if "dateTime" in v:
            return datetime.fromisoformat(v["dateTime"].replace("Z", "+00:00")).astimezone(self.tz), False
        d = date.fromisoformat(v["date"])
        return datetime(d.year, d.month, d.day, tzinfo=self.tz), True

    def events(self, start, end):
        items, page = [], None
        while True:      # без пагинации часть занятости не видна, и freeslots предлагает занятые окна
            res = self.svc.events().list(calendarId=self.cal_id, timeMin=start.astimezone(timezone.utc).isoformat(),
                                         timeMax=end.astimezone(timezone.utc).isoformat(), singleEvents=True,
                                         orderBy="startTime", maxResults=250, pageToken=page).execute()
            items += res.get("items", [])
            page = res.get("nextPageToken")
            if not page or len(items) > 2500:
                break
        out = []
        for it in items:
            s, allday = self._parse(it.get("start", {}))
            e, _ = self._parse(it.get("end", {}))
            out.append({"uid": it.get("id"), "summary": it.get("summary", "(без названия)"), "start": s, "end": e,
                        "allday": allday, "location": it.get("location", ""), "description": it.get("description", ""),
                        "_obj": it})
        return out

    def create(self, ev: dict, invite=False):
        body = {"summary": ev["summary"],
                "start": {"dateTime": ev["start"].isoformat(), "timeZone": str(self.tz)},
                "end": {"dateTime": ev["end"].isoformat(), "timeZone": str(self.tz)}}
        if ev.get("location"):
            body["location"] = ev["location"]
        if ev.get("description"):
            body["description"] = ev["description"]
        if ev["attendees"]:
            body["attendees"] = [{"email": a} for a in ev["attendees"]]
        created = self.svc.events().insert(calendarId=self.cal_id, body=body,
                                           sendUpdates="all" if (invite and ev["attendees"]) else "none").execute()
        ev["uid"] = created.get("id")
        return {"calendar": True, "ics": None, "emailed_by_google": bool(invite and ev["attendees"])}

    def delete(self, uid, start, end):
        try:
            self.svc.events().delete(calendarId=self.cal_id, eventId=uid).execute()
            return True
        except Exception:
            return False


# ======================================================================
def backend(env, fresh: bool = False):
    cfg = kitlib.resolve_cal(env)
    tz = kitlib.get_tz(env)
    if cfg["provider"] == "google":
        return GoogleBackend(cfg, tz), cfg, tz
    if cfg["provider"] == "ics_link":
        return IcsUrlBackend(cfg, tz, fresh=fresh), cfg, tz
    return CalDavBackend(cfg, tz), cfg, tz


def pub(ev: dict, tz) -> dict:
    return {"uid": ev["uid"], "summary": ev["summary"], "allday": ev["allday"],
            "start": ev["start"].isoformat(timespec="minutes"), "end": ev["end"].isoformat(timespec="minutes"),
            "when": (kitlib.fmt_day(ev["start"], tz) + " · весь день") if ev["allday"]
                    else f"{kitlib.fmt_dt(ev['start'], tz)}–{ev['end'].astimezone(tz).strftime('%H:%M')}",
            "location": ev["location"], "description": (ev["description"] or "")[:300]}


def range_args(args, tz, default_days=7, back_days=0):
    now = datetime.now(tz)
    if getattr(args, "from_", None):
        start = kitlib.parse_local(args.from_, tz)
    else:
        start = (now - timedelta(days=back_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    if getattr(args, "to", None):
        end = kitlib.parse_local(args.to, tz)
        if end.hour == 0 and end.minute == 0:
            end = end + timedelta(days=1)
    else:
        end = start + timedelta(days=int(getattr(args, "days", None) or default_days) + back_days)
    return start, end


# ---------- команды ----------
def cmd_check(env, args):
    be, cfg, tz = backend(env, fresh=getattr(args, 'fresh', False))
    cals = be.list_calendars()
    kitlib.out({"provider": cfg["provider"], "user": cfg.get("user") or cfg.get("calendar_id"), "calendars": cals,
                "human": f"календарь подключён ({cfg['provider']}), доступно календарей: {len(cals)}"})


def cmd_calendars(env, args):
    be, cfg, tz = backend(env, fresh=getattr(args, 'fresh', False))
    cals = be.list_calendars()
    kitlib.out({"calendars": cals, "human": "календари: " + ", ".join(str(c.get('name')) for c in cals)})


def cmd_today(env, args):
    be, cfg, tz = backend(env, fresh=getattr(args, 'fresh', False))
    now = datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    evs = [pub(e, tz) for e in be.events(start, start + timedelta(days=1))]
    kitlib.out({"date": start.date().isoformat(), "count": len(evs), "events": evs,
                "human": f"сегодня ({kitlib.fmt_day(now, tz)}) событий: {len(evs)}" +
                         ("" if not evs else " — " + "; ".join(f"{e['when']} {e['summary']}" for e in evs[:6]))})


def cmd_list(env, args):
    be, cfg, tz = backend(env, fresh=getattr(args, 'fresh', False))
    start, end = range_args(args, tz)
    evs = [pub(e, tz) for e in be.events(start, end)]
    kitlib.out({"from": start.isoformat(timespec="minutes"), "to": end.isoformat(timespec="minutes"),
                "count": len(evs), "events": evs,
                "human": f"с {kitlib.fmt_day(start, tz)} по {kitlib.fmt_day(end - timedelta(minutes=1), tz)}: событий {len(evs)}"})


def cmd_freeslots(env, args):
    be, cfg, tz = backend(env, fresh=getattr(args, 'fresh', False))
    now = datetime.now(tz)
    earliest = now + timedelta(hours=args.lead_hours)
    def hour_of(value, fallback, name):
        try:
            h = int(value if value is not None else fallback)
        except (TypeError, ValueError):
            kitlib.fail(kitlib.EXIT_CONFIG, f"{name} должен быть числом от 0 до 23")
        if not 0 <= h <= 23:
            kitlib.fail(kitlib.EXIT_CONFIG, f"{name}={h} — часы бывают от 0 до 23")
        return h
    h_from = hour_of(args.from_hour, env.get("WORK_HOUR_FROM") or 10, "начало рабочего дня")
    h_to = hour_of(args.to_hour, env.get("WORK_HOUR_TO") or 19, "конец рабочего дня")
    if h_to <= h_from:
        kitlib.fail(kitlib.EXIT_CONFIG, f"конец рабочего дня ({h_to}) должен быть позже начала ({h_from})")
    win_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    win_end = win_start + timedelta(days=args.days + 1)
    busy = [(e["start"], e["end"]) for e in be.events(win_start, win_end) if not e["allday"] or args.allday_busy]
    dur = timedelta(minutes=args.duration)
    slots = []
    for d in range(0, args.days + 1):
        day = (now + timedelta(days=d)).date()
        if args.weekdays and day.weekday() >= 5:
            continue
        t = datetime(day.year, day.month, day.day, h_from, 0, tzinfo=tz)
        day_end = datetime(day.year, day.month, day.day, h_to, 0, tzinfo=tz)
        while t + dur <= day_end:
            s, e = t, t + dur
            if s >= earliest and not any(bs < e and s < be_ for bs, be_ in busy):
                slots.append({"iso": s.strftime("%Y-%m-%dT%H:%M"), "label": kitlib.fmt_dt(s, tz),
                              "end": e.strftime("%H:%M")})
            t += timedelta(minutes=args.step)
        if len(slots) >= args.limit:
            break
    slots = slots[:args.limit]
    kitlib.out({"duration_min": args.duration, "hours": f"{h_from:02d}:00–{h_to:02d}:00", "busy_count": len(busy),
                "slots": slots,
                "human": f"свободных окон по {args.duration} мин: {len(slots)}" +
                         ("" if not slots else " — " + ", ".join(s['label'] for s in slots[:5]) + ("…" if len(slots) > 5 else ""))})


def cmd_find(env, args):
    be, cfg, tz = backend(env, fresh=getattr(args, 'fresh', False))
    start, end = range_args(args, tz, default_days=90, back_days=30)
    q = args.text.lower()
    evs = [pub(e, tz) for e in be.events(start, end)
           if q in e["summary"].lower() or q in (e["description"] or "").lower() or q in (e["location"] or "").lower()]
    kitlib.out({"query": args.text, "count": len(evs), "events": evs,
                "human": f"по запросу «{args.text}» найдено: {len(evs)}"})


def send_invites(env, ev: dict, ics: bytes, tz) -> tuple[list[str], list[str]]:
    """Отдельное письмо-приглашение с .ics METHOD:REQUEST каждому участнику (CalDAV-серверы сами не рассылают)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mail_cli import smtp_connect  # noqa
    mcfg = kitlib.resolve_mail(env)
    sent, failed = [], []
    for to in ev["attendees"]:
        msg = MIMEMultipart("mixed")
        msg["From"] = mcfg["user"]
        msg["To"] = to
        msg["Subject"] = f"Приглашение: {ev['summary']}"
        when = f"{kitlib.fmt_dt(ev['start'], tz)}–{ev['end'].astimezone(tz).strftime('%H:%M')}"
        text = f"Приглашаю на встречу «{ev['summary']}»\n{when} ({tz.key})\n"
        if ev.get("location"):
            text += f"Где: {ev['location']}\n"
        if ev.get("description"):
            text += f"\n{ev['description']}\n"
        text += "\nФайл-приглашение во вложении — открой его, чтобы добавить встречу в свой календарь."
        msg.attach(MIMEText(text, "plain", "utf-8"))
        part = MIMEText(ics.decode(), "calendar", "utf-8")
        part.add_header("Content-Disposition", "attachment", filename="invite.ics")
        part.set_param("method", "REQUEST")
        msg.attach(part)
        try:
            srv = smtp_connect(mcfg)
            srv.sendmail(mcfg["user"], [to], msg.as_string())
            srv.quit()
            sent.append(to)
        except Exception as ex:
            sys.stderr.write(f"invite to {to} failed: {ex}\n")
            failed.append(to)
    return sent, failed


def cmd_create(env, args):
    tz = kitlib.get_tz(env)
    cal_cfg = kitlib.resolve_cal(env)
    # Универсальный запасной путь записи: если в календарь нельзя писать напрямую (мы знаем только
    # ссылку на него), встречу всё равно можно поставить — письмом-приглашением себе. Файл .ics
    # понимают все календари: Apple, Google, Яндекс, Outlook. Владелец жмёт «Да» — встреча у него.
    via_email = bool(getattr(args, "via_email", False)) or cal_cfg.get("readonly")
    try:
        start = kitlib.parse_local(args.start, tz)
    except ValueError as ex:
        kitlib.fail(kitlib.EXIT_CONFIG, str(ex))
    if args.end:
        end = kitlib.parse_local(args.end, tz)
    else:
        end = start + timedelta(minutes=args.duration)
    if end <= start:
        kitlib.fail(kitlib.EXIT_CONFIG, "конец раньше начала")
    attendees = [a.strip() for a in (args.attendee or []) if a.strip()]
    bad = [a for a in attendees if not EMAIL_RE.match(a)]
    if bad:
        kitlib.fail(kitlib.EXIT_CONFIG, f"это не адрес: {', '.join(bad)}. Email участника берётся только из слов владельца.")
    ev = {"uid": f"mck-{uuid.uuid4()}", "start": start, "end": end, "summary": args.summary,
          "location": args.location or "", "description": args.description or "", "attendees": attendees}
    preview = {"summary": ev["summary"], "when": f"{kitlib.fmt_dt(start, tz)}–{end.strftime('%H:%M')}",
               "start": start.isoformat(timespec="minutes"), "end": end.isoformat(timespec="minutes"),
               "location": ev["location"], "attendees": attendees, "invite": bool(args.invite),
               "mode": "письмо-приглашение" if via_email else "прямая запись в календарь"}
    if via_email and not kitlib.send_allowed(env):
        kitlib.out({"ok": False, "created": False, "preview": preview,
                    "human": "этот календарь доступен только на чтение, поэтому встреча ставится письмом-приглашением — "
                             "а отправка сейчас выключена предохранителем (MCK_SEND_ALLOWED=0). "
                             "Включи его в файле доступов, и способ заработает."},
                   kitlib.EXIT_CONFIRM)
    if args.invite and attendees and not kitlib.send_allowed(env):
        kitlib.out({"ok": False, "created": False, "preview": preview,
                    "human": "рассылка приглашений выключена предохранителем (MCK_SEND_ALLOWED=0). Событие не создано. Либо без --invite, либо включи предохранитель на приёмке."},
                   kitlib.EXIT_CONFIRM)
    if not args.confirm:
        kitlib.out({"ok": False, "created": False, "preview": preview,
                    "human": f"превью: «{ev['summary']}» {preview['when']}" + (f", участники {', '.join(attendees)}" if attendees else "") +
                             ". Не создано: нужен --confirm после «да» владельца."},
                   kitlib.EXIT_CONFIRM)
    be, cfg, tz = backend(env, fresh=getattr(args, 'fresh', False))
    # накладки ±: сообщаем, но не блокируем
    overlaps = [pub(e, tz) for e in be.events(start - timedelta(hours=1), end + timedelta(hours=1))
                if not e["allday"] and e["start"] < end and start < e["end"]]
    failed = []
    if via_email:
        mcfg = kitlib.resolve_mail(env)
        # приглашение идёт владельцу, а при --invite ещё и участникам
        recipients = [mcfg["user"]] + ([a for a in attendees if a != mcfg["user"]] if args.invite else [])
        ics = build_ics({**ev, "attendees": recipients}, mcfg["user"], with_attendees=True)
        sent, failed = send_invites(env, {**ev, "attendees": recipients}, ics, tz)
        got_self = mcfg["user"] in sent
        kitlib.out({"created": False, "invitation_sent": got_self, "uid": ev["uid"], "summary": ev["summary"],
                    "when": preview["when"], "sent_to": sent, "failed": failed, "overlaps": overlaps,
                    "human": (f"письмо-приглашение «{ev['summary']}» на {preview['when']} отправлено тебе"
                              + (f" и участникам: {', '.join(a for a in sent if a != mcfg['user'])}"
                                 if len(sent) > 1 else "")
                              + ". Открой его в почте и нажми «Да» — встреча встанет в календарь. "
                                "Прямо писать в этот календарь нельзя: он подключён по ссылке, только на чтение."
                              if got_self else
                              f"🔴 приглашение не ушло: {', '.join(failed)}. Встреча НЕ поставлена.")
                              + (f" ВНИМАНИЕ, накладка с: {', '.join(o['summary'] for o in overlaps)}" if overlaps else "")},
                   kitlib.EXIT_OK if got_self else kitlib.EXIT_PROVIDER)
    if cfg["provider"] == "google":
        r = be.create(ev, invite=bool(args.invite))
        emailed = r.get("emailed_by_google", False)
        sent = attendees if emailed else []
    else:
        r = be.create(ev, invite=bool(args.invite and attendees))
        sent, failed = [], []
        if args.invite and attendees:
            sent, failed = send_invites(env, ev, r["ics"], tz)
    kitlib.out({"created": True, "uid": ev["uid"], "summary": ev["summary"], "when": preview["when"],
                "attendees": attendees, "invites_sent": sent, "invites_failed": failed, "overlaps": overlaps,
                "human": f"встреча «{ev['summary']}» создана на {preview['when']}" +
                         (f"; приглашения ушли: {', '.join(sent)}" if sent else "") +
                         (f"; 🔴 приглашение НЕ ушло: {', '.join(failed)} — позови человека другим способом"
                          if failed else "") +
                         (f"; ВНИМАНИЕ, накладка с: {', '.join(o['summary'] for o in overlaps)}" if overlaps else "")})


def cmd_move(env, args):
    """Перенос встречи: создаём копию на новое время, потом удаляем старую.
    Порядок именно такой: если второй шаг сорвётся, останется дубль — это видно и чинится,
    а обратный порядок мог бы стереть встречу и не создать новую."""
    be, cfg, tz = backend(env)
    if cfg.get("readonly"):
        kitlib.fail(kitlib.EXIT_CONFIG,
                    "этот календарь подключён по ссылке, только на чтение: перенести встречу нельзя. "
                    "Поставь новую письмом-приглашением (create --via-email), а старую убери руками в календаре")
    if not hasattr(be, "find_raw"):
        kitlib.fail(kitlib.EXIT_CONFIG, "для этого календаря перенос пока не поддержан — создай новую встречу и удали старую")
    now = datetime.now(tz)
    try:
        new_start = kitlib.parse_local(args.start, tz)
    except ValueError as ex:
        kitlib.fail(kitlib.EXIT_CONFIG, str(ex))
    found = be.find_raw(args.uid, now - timedelta(days=730), now + timedelta(days=1825))
    if not found:
        kitlib.fail(kitlib.EXIT_PROVIDER, f"встреча {args.uid} не найдена — проверь номер через find")
    if found["recurring"]:
        kitlib.fail(kitlib.EXIT_CONFIG,
                    f"«{found['summary']}» — повторяющаяся встреча. Перенос одного раза из серии "
                    f"я делать не буду: это меняет всю серию. Перенеси её в самом календаре")
    minutes = args.duration or (int((found["end"] - found["start"]).total_seconds() // 60)
                                if found.get("end") and found.get("start") else 60)
    new_end = new_start + timedelta(minutes=minutes)
    preview = {"summary": found["summary"],
               "from": kitlib.fmt_dt(found["start"], tz) if found["start"] else "?",
               "to": f"{kitlib.fmt_dt(new_start, tz)}–{new_end.strftime('%H:%M')}"}
    if not args.confirm:
        kitlib.out({"ok": False, "moved": False, "uid": args.uid, "preview": preview,
                    "human": f"перенести «{preview['summary']}» с {preview['from']} на {preview['to']}? "
                             f"Не перенесено: нужен --confirm после «да» владельца."},
                   kitlib.EXIT_CONFIRM)
    overlaps = [pub(e, tz) for e in be.events(new_start - timedelta(hours=1), new_end + timedelta(hours=1))
                if not e["allday"] and e["uid"] != args.uid and e["start"] < new_end and new_start < e["end"]]
    ev = {"uid": f"mck-{uuid.uuid4()}", "start": new_start, "end": new_end, "summary": found["summary"],
          "location": found.get("location", ""), "description": found.get("description", ""), "attendees": []}
    be.create(ev, invite=False)
    removed = be.delete(args.uid, now - timedelta(days=730), now + timedelta(days=1825))
    kitlib.out({"moved": True, "new_uid": ev["uid"], "old_uid": args.uid, "old_removed": removed,
                "preview": preview, "overlaps": overlaps,
                "human": f"«{preview['summary']}» перенесена на {preview['to']}"
                         + ("" if removed else "; 🔴 старую запись удалить не удалось, убери её в календаре руками")
                         + (f"; ВНИМАНИЕ, накладка с: {', '.join(o['summary'] for o in overlaps)}" if overlaps else "")})


def cmd_delete(env, args):
    be, cfg, tz = backend(env, fresh=getattr(args, 'fresh', False))
    now = datetime.now(tz)
    try:
        start = kitlib.parse_local(args.from_, tz) if args.from_ else now - timedelta(days=730)
        end = kitlib.parse_local(args.to, tz) if args.to else now + timedelta(days=1825)
    except ValueError as ex:
        kitlib.fail(kitlib.EXIT_CONFIG, str(ex))
    # Сначала показываем, ЧТО удаляем: подтверждать «да» на строку вида mck-7f3a… нельзя.
    what = None
    if hasattr(be, "find_raw"):
        found = be.find_raw(args.uid, start, end)
        if found:
            what = {"summary": found["summary"],
                    "when": kitlib.fmt_dt(found["start"], tz) if found["start"] else "?",
                    "recurring": found["recurring"]}
    if not args.confirm:
        kitlib.out({"ok": False, "deleted": False, "uid": args.uid, "event": what,
                    "human": (f"удалить «{what['summary']}» {what['when']}?" if what
                              else f"событие {args.uid} в этом диапазоне не найдено")
                             + " Не удалено: нужен --confirm после «да» владельца."},
                   kitlib.EXIT_CONFIRM)
    ok = be.delete(args.uid, start, end)
    if not ok:
        kitlib.fail(kitlib.EXIT_PROVIDER, f"событие {args.uid} не найдено в диапазоне поиска (сузь --from/--to или проверь uid через find)")
    kitlib.out({"deleted": True, "uid": args.uid, "event": what,
                "human": f"событие «{what['summary']}» удалено" if what else f"событие {args.uid} удалено"})


def main():
    p = kitlib.JsonArgumentParser(description="календарь второго мозга (CalDAV / Google)")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "calendars", "today"):
        sp = sub.add_parser(name)
        sp.add_argument("--fresh", action="store_true", help="перечитать календарь по ссылке, не из кэша")
    l = sub.add_parser("list"); l.add_argument("--fresh", action="store_true"); l.add_argument("--days", type=int); l.add_argument("--from", dest="from_"); l.add_argument("--to")
    f = sub.add_parser("freeslots"); f.add_argument("--fresh", action="store_true")
    f.add_argument("--days", type=int, default=7); f.add_argument("--from-hour", type=int); f.add_argument("--to-hour", type=int)
    f.add_argument("--duration", type=int, default=60); f.add_argument("--step", type=int, default=60)
    f.add_argument("--lead-hours", type=int, default=3); f.add_argument("--weekdays", action="store_true")
    f.add_argument("--allday-busy", action="store_true"); f.add_argument("--limit", type=int, default=15)
    s = sub.add_parser("find"); s.add_argument("--fresh", action="store_true")
    s.add_argument("--text", required=True)
    s.add_argument("--days", type=int, help="на сколько дней вперёд смотреть (по умолчанию 90)")
    s.add_argument("--from", dest="from_"); s.add_argument("--to")
    c = sub.add_parser("create")
    c.add_argument("--start", required=True); c.add_argument("--end"); c.add_argument("--duration", type=int, default=60)
    c.add_argument("--summary", required=True); c.add_argument("--location"); c.add_argument("--description")
    c.add_argument("--attendee", action="append"); c.add_argument("--invite", action="store_true")
    c.add_argument("--via-email", action="store_true",
                   help="поставить встречу письмом-приглашением себе, не записывая в календарь напрямую")
    c.add_argument("--confirm", action="store_true")
    m = sub.add_parser("move")
    m.add_argument("--uid", required=True); m.add_argument("--start", required=True)
    m.add_argument("--duration", type=int); m.add_argument("--confirm", action="store_true")
    d = sub.add_parser("delete"); d.add_argument("--uid", required=True); d.add_argument("--from", dest="from_"); d.add_argument("--to")
    d.add_argument("--confirm", action="store_true")
    args = p.parse_args()
    env = kitlib.load_env()
    kitlib.run_cli({"check": cmd_check, "calendars": cmd_calendars, "today": cmd_today, "list": cmd_list, "freeslots": cmd_freeslots,
     "find": cmd_find, "create": cmd_create, "move": cmd_move, "delete": cmd_delete}[args.cmd], env, args)


if __name__ == "__main__":
    main()
