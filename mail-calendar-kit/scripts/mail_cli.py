#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mail_cli.py — почта второго мозга через IMAP/SMTP с паролем приложения.
Провайдеры: Яндекс, Gmail, Mail.ru, iCloud (пресеты) или любой другой (custom).

Команды:
  check                                   проверить вход по IMAP и SMTP
  folders                                 список папок
  unread [--folder INBOX] [--limit 20]    непрочитанные: uid, дата, от кого, тема
  search [--from X] [--subject X] [--text X] [--days 30 | --since 01.09.2026]
         [--folder INBOX | --all-folders] [--limit 20] [--unseen]
  read --uid U [--folder INBOX | --all-folders] [--max-chars 3000]
  send --to a@b.c [--cc ...] --subject S (--body "..." | --body-file F)
       [--attach FILE ...] [--reply-uid U] [--confirm]

Безопасность:
  * чтение никогда не меняет статус «прочитано» (BODY.PEEK);
  * send без --confirm показывает превью и выходит с кодом 3;
  * send при MCK_SEND_ALLOWED=0 запрещён (предохранитель включается на приёмке).

Вывод — один JSON с полем "human".
"""
import argparse
import base64
import email
import email.utils
import imaplib
import mimetypes
import re
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

_EN_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MAX_CANDIDATES = 300      # сколько писем максимум смотрим при поиске (новые в приоритете)

LOGIN_HINTS = {
    "yandex": "Яндекс: включи IMAP (Почта → Настройки → Почтовые программы), логин — полный адрес, пароль — пароль приложения типа «Почта», без пробелов",
    "gmail": "Gmail: нужна включённая двухэтапная аутентификация и «пароль приложения» (App password), не основной пароль",
    "mailru": "Mail.ru: включи «Доступ к почте по IMAP, POP и SMTP» (Настройки → Безопасность → Внешние сервисы) и создай «пароль для внешнего приложения»",
    "icloud": "iCloud: пароль — app-specific password с account.apple.com; IMAP-логин без домена ставится сам",
}


# ---------- вспомогательное ----------
def hdr(raw) -> str:
    if raw is None:
        return ""
    try:
        return str(make_header(decode_header(raw))).replace("\r", " ").replace("\n", " ").strip()
    except Exception:
        return str(raw)


def imap_utf7_decode(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "&":
            j = s.find("-", i + 1)
            if j == -1:
                j = len(s)
            chunk = s[i + 1:j]
            if chunk == "":
                out.append("&")
            else:
                b64 = chunk.replace(",", "/")
                b64 += "=" * (-len(b64) % 4)
                try:
                    out.append(base64.b64decode(b64).decode("utf-16-be"))
                except Exception:
                    out.append(s[i:j + 1])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def imap_utf7_encode(s: str) -> str:
    if all(0x20 <= ord(c) <= 0x7E for c in s):
        return s.replace("&", "&-")
    out, buf = [], []

    def flush():
        if buf:
            b = "".join(buf).encode("utf-16-be")
            out.append("&" + base64.b64encode(b).decode().rstrip("=").replace("/", ",") + "-")
            buf.clear()
    for c in s:
        if 0x20 <= ord(c) <= 0x7E:
            flush()
            out.append("&-" if c == "&" else c)
        else:
            buf.append(c)
    flush()
    return "".join(out)


def parse_date(raw) -> datetime | None:
    try:
        d = email.utils.parsedate_to_datetime(raw)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


def body_text(msg) -> tuple[str, list[str]]:
    """Текст письма (plain, иначе html без тегов) и имена вложений."""
    parts, attachments = [], []
    if msg.is_multipart():
        for p in msg.walk():
            fn = p.get_filename()
            if fn:
                attachments.append(hdr(fn))
                continue
            if p.get_content_type() == "text/plain":
                try:
                    parts.append(p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace"))
                except Exception:
                    pass
        if not parts:
            for p in msg.walk():
                if p.get_content_type() == "text/html":
                    try:
                        h = p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace")
                        h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
                        h = re.sub(r"(?s)<[^>]+>", "\n", h)
                        parts.append(email.utils.unquote(h))
                    except Exception:
                        pass
    else:
        try:
            parts.append(msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace"))
        except Exception:
            pass
    t = "\n".join(parts)
    t = re.sub(r"&nbsp;", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip(), attachments


# ---------- IMAP ----------
def imap_connect(cfg: dict) -> imaplib.IMAP4_SSL:
    try:
        M = imaplib.IMAP4_SSL(cfg["imap_host"], int(cfg["imap_port"]))
    except Exception as ex:
        kitlib.fail(kitlib.EXIT_PROVIDER, f"не могу соединиться с {cfg['imap_host']}:{cfg['imap_port']} ({ex}) — проверь интернет")
    try:
        M.login(cfg["imap_user"], cfg["password"])
    except imaplib.IMAP4.error as ex:
        hint = LOGIN_HINTS.get(cfg["provider"], "проверь логин и пароль приложения")
        kitlib.fail(kitlib.EXIT_AUTH, f"IMAP не пустил ({str(ex)[:120]}). {hint}")
    return M


def select_folder(M, folder: str, readonly=True, quiet=False, raw=False):
    """raw=True — имя пришло из списка папок сервера и уже в его кодировке; перекодировать нельзя,
    иначе вложенные папки с кириллицей (INBOX/Клиенты) тихо выпадут из поиска."""
    name = folder if raw else imap_utf7_encode(folder)
    typ, _ = M.select(f'"{name}"', readonly=readonly)
    if typ != "OK":
        if quiet:
            raise RuntimeError(f"folder {folder} not selectable")
        kitlib.fail(kitlib.EXIT_PROVIDER, f"папка «{folder}» не открылась — посмотри список командой folders")


def uid_search(M, criteria: list[str], literal: str | None = None) -> list[str]:
    try:
        if literal is not None:
            M.literal = literal.encode("utf-8")
            typ, data = M.uid("SEARCH", "CHARSET", "UTF-8", *criteria)
        else:
            typ, data = M.uid("SEARCH", *criteria) if criteria else M.uid("SEARCH", "ALL")
    except Exception as ex:
        raise RuntimeError(str(ex))
    if typ != "OK":
        raise RuntimeError(f"SEARCH {typ}")
    return data[0].decode().split() if data and data[0] else []


def fetch_headers(M, uids: list[str]) -> list[dict]:
    if not uids:
        return []
    typ, data = M.uid("FETCH", ",".join(uids),
                      "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])")
    if typ != "OK":
        return []
    items = []
    for part in data:
        if not isinstance(part, tuple) or len(part) < 2:
            continue
        meta = part[0].decode(errors="ignore")
        m = re.search(r"UID (\d+)", meta)
        if not m:
            continue
        msg = email.message_from_bytes(part[1])
        d = parse_date(msg.get("Date"))
        items.append({
            "uid": m.group(1),
            "date": d.isoformat(timespec="minutes") if d else None,
            "_dt": d,
            "from": hdr(msg.get("From")),
            "to": hdr(msg.get("To")),
            "subject": hdr(msg.get("Subject")),
            "message_id": (msg.get("Message-ID") or "").strip(),
            "unread": "\\Seen" not in meta,
        })
    items.sort(key=lambda x: x["_dt"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items


def humanize(items: list[dict], tz) -> list[dict]:
    out = []
    for it in items:
        d = it.pop("_dt", None)
        it["when"] = kitlib.fmt_dt(d, tz) if d else "?"
        out.append(it)
    return out


# ---------- команды ----------
def cmd_check(env, args):
    cfg = kitlib.resolve_mail(env)
    M = imap_connect(cfg)
    typ, data = M.select("INBOX", readonly=True)
    total = int(data[0]) if typ == "OK" and data and data[0] else None
    try:
        M.logout()
    except Exception:
        pass
    smtp_ok, smtp_err = True, None
    try:
        srv = smtp_connect(cfg)
        srv.quit()
    except Exception as ex:
        smtp_ok, smtp_err = False, str(ex)[:160]
    res = {"provider": cfg["provider"], "user": cfg["user"], "imap": f"{cfg['imap_host']}:{cfg['imap_port']}",
           "smtp": f"{cfg['smtp_host']}:{cfg['smtp_port']} ({cfg['smtp_mode']})",
           "inbox_total": total, "imap_ok": True, "smtp_ok": smtp_ok, "smtp_error": smtp_err,
           "send_allowed": kitlib.send_allowed(env)}
    # Чтение — блокирующая проверка, отправка — нет: бывает, что сеть режет исходящую почту,
    # и это не повод останавливать вечер. Поэтому при живом IMAP код выхода 0.
    if smtp_ok:
        res["human"] = f"почта {cfg['user']} подключена: во Входящих {total} писем; отправка тоже работает"
    else:
        res["send_blocked_reason"] = smtp_err
        res["human"] = (f"почта {cfg['user']} читается: во Входящих {total} писем. "
                        f"А вот отправка сейчас недоступна ({smtp_err}). Чаще всего это сеть или "
                        f"провайдер интернета режет исходящую почту, а не пароль: пароль один и тот же. "
                        f"Чтение и календарь настраиваем дальше, отправку проверим из другой сети или с сервера.")
    kitlib.out(res, kitlib.EXIT_OK)


def list_selectable(M) -> list[str]:
    """Имена папок, в которых можно искать (без \\Noselect)."""
    typ, data = M.list()
    names = []
    for raw in data or []:
        if isinstance(raw, tuple):
            raw = raw[0]
        line = raw.decode(errors="ignore") if isinstance(raw, bytes) else str(raw)
        m = re.match(r'\((?P<flags>.*?)\)\s+"?(?P<delim>[^"\s]+|NIL)"?\s+(?P<name>.*)$', line)
        if not m or "\\Noselect" in m.group("flags"):
            continue
        name = m.group("name").strip()
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1]
        names.append(name)
    # INBOX первым, остальные по алфавиту
    names.sort(key=lambda n: (n.upper() != "INBOX", n.upper()))
    return names


def cmd_folders(env, args):
    cfg = kitlib.resolve_mail(env)
    M = imap_connect(cfg)
    typ, data = M.list()
    folders, delim = [], None
    for raw in data or []:
        if isinstance(raw, tuple):
            raw = raw[0]
        line = raw.decode(errors="ignore") if isinstance(raw, bytes) else str(raw)
        m = re.match(r'\((?P<flags>.*?)\)\s+"?(?P<delim>[^"\s]+|NIL)"?\s+(?P<name>.*)$', line)
        if not m:
            continue
        name = m.group("name").strip()
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1]
        delim = m.group("delim")
        folders.append({"name": imap_utf7_decode(name), "raw": name, "flags": m.group("flags")})
    M.logout()
    kitlib.out({"delimiter": delim, "folders": folders,
                "human": f"папок: {len(folders)} — " + ", ".join(f['name'] for f in folders[:12])})


def build_criteria(args) -> tuple[list[str], list[str]]:
    """Возвращает (ASCII-критерии, список UTF-8 критериев вида ['SUBJECT','текст'])."""
    crit, utf8 = [], []
    if getattr(args, "unseen", False):
        crit.append("UNSEEN")
    if getattr(args, "since", None):
        try:
            d = datetime.strptime(args.since, "%d.%m.%Y")
        except ValueError:
            kitlib.fail(kitlib.EXIT_CONFIG, f"не понял дату «{args.since}». Формат: 01.09.2026 (день.месяц.год)")
    elif getattr(args, "days", None):
        d = datetime.now() - timedelta(days=int(args.days))
    else:
        d = None
    if d is not None:
        crit += ["SINCE", f"{d.day:02d}-{_EN_MON[d.month - 1]}-{d.year}"]
    for key, val in (("FROM", getattr(args, "from_", None)), ("SUBJECT", getattr(args, "subject", None)),
                     ("TEXT", getattr(args, "text", None))):
        if not val:
            continue
        if val.isascii():
            crit += [key, '"' + val.replace('"', '') + '"']
        else:
            utf8.append([key, val])
    return crit, utf8


def do_search(M, args) -> tuple[list[str], str | None]:
    crit, utf8 = build_criteria(args)
    note = None
    uids = set(uid_search(M, crit or ["ALL"]))
    for key, val in utf8:
        try:
            uids &= set(uid_search(M, [key], literal=val))
        except Exception:
            # сервер не понял UTF-8 в поиске — отфильтруем по заголовкам на нашей стороне
            note = (f"сервер не ищет по кириллице: смотрю сам, но только по отправителю и теме "
                    f"последних {MAX_CANDIDATES} писем — если нужного нет, сузь период")
            cand = sorted(uids, key=int, reverse=True)[:MAX_CANDIDATES]
            hs = fetch_headers(M, cand)
            v = val.lower()
            keep = set()
            for h in hs:
                field = {"FROM": h["from"], "SUBJECT": h["subject"], "TEXT": h["subject"] + " " + h["from"]}[key]
                if v in field.lower():
                    keep.add(h["uid"])
            uids = keep
    return sorted(uids, key=int, reverse=True), note


def cmd_unread(env, args):
    cfg = kitlib.resolve_mail(env)
    tz = kitlib.get_tz(env)
    M = imap_connect(cfg)
    select_folder(M, args.folder)
    uids = uid_search(M, ["UNSEEN"])
    uids = sorted(uids, key=int, reverse=True)
    items = humanize(fetch_headers(M, uids[:args.limit]), tz)
    M.logout()
    kitlib.out({"folder": args.folder, "unread_total": len(uids), "shown": len(items), "messages": items,
                "human": f"непрочитанных в «{args.folder}»: {len(uids)}" + (f", показываю {len(items)}" if items else "")})


def cmd_search(env, args):
    cfg = kitlib.resolve_mail(env)
    tz = kitlib.get_tz(env)
    if not any([args.from_, args.subject, args.text, args.since, args.days, args.unseen]):
        args.days = 30
    M = imap_connect(cfg)
    folders = list_selectable(M) if args.all_folders else [args.folder]
    items, total, note, hit_folders = [], 0, None, []
    for folder in folders:
        try:
            select_folder(M, folder, quiet=args.all_folders, raw=args.all_folders)
        except SystemExit:
            raise
        except Exception:
            continue
        try:
            uids, n = do_search(M, args)
        except RuntimeError as ex:
            if not args.all_folders:
                M.logout()
                kitlib.fail(kitlib.EXIT_PROVIDER, f"поиск не удался: {ex}")
            continue
        note = note or n
        if not uids:
            continue
        total += len(uids)
        hit_folders.append({"folder": imap_utf7_decode(folder), "count": len(uids)})
        for it in fetch_headers(M, uids[:args.limit]):
            it["folder"] = imap_utf7_decode(folder)
            items.append(it)
    M.logout()
    items.sort(key=lambda x: x["_dt"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    items = humanize(items[:args.limit], tz)
    res = {"searched": "все папки" if args.all_folders else args.folder,
           "found_total": total, "shown": len(items), "folders": hit_folders, "messages": items}
    if note:
        res["note"] = note
    res["human"] = f"найдено писем: {total}" + \
        (f" (папки: {', '.join(h['folder'] + ' — ' + str(h['count']) for h in hit_folders)})" if len(hit_folders) > 1 else "") + \
        (f", показываю {len(items)} последних" if items else "")
    if total == 0 and not args.all_folders:
        res["human"] += ". Письмо могло уехать в другую папку по правилам сортировки — повтори с --all-folders"
    kitlib.out(res)


def cmd_read(env, args):
    if not str(args.uid).strip().isdigit():
        kitlib.fail(kitlib.EXIT_CONFIG, f"номер письма должен быть числом, а не «{args.uid}» — возьми uid из поиска")
    cfg = kitlib.resolve_mail(env)
    tz = kitlib.get_tz(env)
    M = imap_connect(cfg)
    folders = list_selectable(M) if args.all_folders else [args.folder]
    msg, found_in = None, None
    for folder in folders:
        try:
            select_folder(M, folder, quiet=args.all_folders, raw=args.all_folders)
        except SystemExit:
            raise
        except Exception:
            continue
        typ, data = M.uid("FETCH", str(args.uid), "(BODY.PEEK[])")
        if typ == "OK" and data and isinstance(data[0], tuple):
            msg = email.message_from_bytes(data[0][1])
            found_in = imap_utf7_decode(folder)
            break
    M.logout()
    if msg is None:
        where = "ни в одной папке" if args.all_folders else f"в папке «{args.folder}»"
        hint = "" if args.all_folders else " — если письмо нашлось поиском с --all-folders, передай сюда --folder с тем же именем или повтори с --all-folders"
        kitlib.fail(kitlib.EXIT_PROVIDER, f"письма с uid {args.uid} нет {where}{hint}")
    text, attachments = body_text(msg)
    d = parse_date(msg.get("Date"))
    full_len = len(text)
    if full_len > args.max_chars:
        text = text[:args.max_chars] + f"\n…[обрезано, всего {full_len} символов; --max-chars чтобы увидеть больше]"
    res = {"uid": str(args.uid), "folder": found_in or args.folder,
           "date": d.isoformat(timespec="minutes") if d else None, "when": kitlib.fmt_dt(d, tz) if d else "?",
           "from": hdr(msg.get("From")), "to": hdr(msg.get("To")), "cc": hdr(msg.get("Cc")),
           "subject": hdr(msg.get("Subject")), "message_id": (msg.get("Message-ID") or "").strip(),
           "attachments": attachments, "text": text, "text_length": full_len}
    res["human"] = f"письмо от {res['from']} · {res['when']} · «{res['subject']}» · {full_len} символов" + \
                   (f" · вложений: {len(attachments)}" if attachments else "")
    kitlib.out(res)


# ---------- SMTP ----------
def smtp_connect(cfg: dict):
    if cfg["smtp_mode"] == "starttls":
        srv = smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=30)
        srv.ehlo()
        srv.starttls()
        srv.ehlo()
    else:
        srv = smtplib.SMTP_SSL(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=30)
    srv.login(cfg["smtp_user"], cfg["password"])
    return srv


def cmd_send(env, args):
    cfg = kitlib.resolve_mail(env)
    tz = kitlib.get_tz(env)
    if args.body_file:
        bf = Path(args.body_file).expanduser()
        if not bf.exists():
            kitlib.fail(kitlib.EXIT_CONFIG, f"нет файла с текстом письма: {bf}")
        try:
            body = bf.read_text(encoding="utf-8")
        except Exception as ex:
            kitlib.fail(kitlib.EXIT_CONFIG, f"не смог прочитать {bf}: {str(ex)[:120]}")
    else:
        body = args.body or ""
    if not body.strip():
        kitlib.fail(kitlib.EXIT_CONFIG, "пустое письмо: дай --body или --body-file")
    to = [a.strip() for a in args.to.split(",") if a.strip()]
    cc = [a.strip() for a in (args.cc or "").split(",") if a.strip()]
    if len(to) + len(cc) > 5:
        kitlib.fail(kitlib.EXIT_CONFIRM,
                    f"получателей {len(to) + len(cc)} — это уже рассылка, а пак для личной переписки. "
                    f"Максимум 5 адресов за раз; если нужен охват, это другой инструмент и другие правила.")
    bad = [a for a in to + cc if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", a)]
    if bad:
        kitlib.fail(kitlib.EXIT_CONFIG, f"это не похоже на адрес: {', '.join(bad)}. Адрес берётся только из слов владельца, не придумывается.")
    attach = [Path(a).expanduser() for a in (args.attach or [])]
    missing = [str(a) for a in attach if not a.exists()]
    if missing:
        kitlib.fail(kitlib.EXIT_CONFIG, f"нет файла для вложения: {', '.join(missing)}")

    subject = args.subject
    in_reply_to = None
    if args.reply_uid:
        M = imap_connect(cfg)
        select_folder(M, args.folder)
        typ, data = M.uid("FETCH", str(args.reply_uid), "(BODY.PEEK[HEADER.FIELDS (SUBJECT MESSAGE-ID)])")
        M.logout()
        if typ == "OK" and data and isinstance(data[0], tuple):
            orig = email.message_from_bytes(data[0][1])
            in_reply_to = (orig.get("Message-ID") or "").strip() or None
            if not subject:
                s = hdr(orig.get("Subject"))
                subject = s if s.lower().startswith("re:") else f"Re: {s}"
    if not subject:
        kitlib.fail(kitlib.EXIT_CONFIG, "нужна тема письма: --subject")

    preview = {"from": cfg["user"], "to": to, "cc": cc, "subject": subject,
               "body_preview": body[:400] + ("…" if len(body) > 400 else ""),
               "attachments": [a.name for a in attach], "reply_to_uid": args.reply_uid}
    if not kitlib.send_allowed(env):
        kitlib.out({"ok": False, "sent": False, "preview": preview,
                    "human": "отправка выключена предохранителем (MCK_SEND_ALLOWED=0). Включается в файле доступов на приёмке."},
                   kitlib.EXIT_CONFIRM)
    if not args.confirm:
        kitlib.out({"ok": False, "sent": False, "preview": preview,
                    "human": f"превью письма для {', '.join(to)}: «{subject}». Не отправлено: нужен --confirm после «да» владельца."},
                   kitlib.EXIT_CONFIRM)

    msg = EmailMessage()
    msg["From"] = email.utils.formataddr((cfg["from_name"], cfg["user"])) if cfg["from_name"] else cfg["user"]
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg["Date"] = email.utils.format_datetime(datetime.now(tz))
    msg["Message-ID"] = email.utils.make_msgid()
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    for a in attach:
        ctype, _ = mimetypes.guess_type(str(a))
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(a.read_bytes(), maintype=maintype, subtype=subtype, filename=a.name)
    try:
        srv = smtp_connect(cfg)
        srv.send_message(msg, from_addr=cfg["user"], to_addrs=to + cc)
        srv.quit()
    except smtplib.SMTPAuthenticationError as ex:
        kitlib.fail(kitlib.EXIT_AUTH, f"SMTP не пустил ({str(ex)[:120]}). {LOGIN_HINTS.get(cfg['provider'], '')}")
    except Exception as ex:
        kitlib.fail(kitlib.EXIT_PROVIDER, f"письмо не ушло: {str(ex)[:200]}")
    kitlib.out({"sent": True, "to": to, "cc": cc, "subject": subject, "message_id": msg["Message-ID"],
                "human": f"письмо «{subject}» отправлено: {', '.join(to)}"})


def main():
    p = kitlib.JsonArgumentParser(description="почта второго мозга (IMAP/SMTP)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("folders")
    u = sub.add_parser("unread"); u.add_argument("--folder", default="INBOX"); u.add_argument("--limit", type=int, default=20)
    s = sub.add_parser("search")
    s.add_argument("--from", dest="from_"); s.add_argument("--subject"); s.add_argument("--text")
    s.add_argument("--days", type=int); s.add_argument("--since", help="DD.MM.YYYY")
    s.add_argument("--folder", default="INBOX"); s.add_argument("--limit", type=int, default=20)
    s.add_argument("--unseen", action="store_true")
    s.add_argument("--all-folders", action="store_true", help="искать во всех папках, а не только во Входящих")
    r = sub.add_parser("read"); r.add_argument("--uid", required=True); r.add_argument("--folder", default="INBOX")
    r.add_argument("--all-folders", action="store_true", help="искать письмо по всем папкам, а не только во Входящих")
    r.add_argument("--max-chars", type=int, default=3000)
    d = sub.add_parser("send")
    d.add_argument("--to", required=True, help="адрес или несколько через запятую"); d.add_argument("--cc")
    d.add_argument("--subject"); d.add_argument("--body"); d.add_argument("--body-file")
    d.add_argument("--attach", action="append"); d.add_argument("--reply-uid"); d.add_argument("--folder", default="INBOX")
    d.add_argument("--confirm", action="store_true")
    args = p.parse_args()
    env = kitlib.load_env()
    kitlib.run_cli({"check": cmd_check, "folders": cmd_folders, "unread": cmd_unread, "search": cmd_search,
     "read": cmd_read, "send": cmd_send}[args.cmd], env, args)


if __name__ == "__main__":
    main()
