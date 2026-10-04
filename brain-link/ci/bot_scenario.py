#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bot_scenario.py — сценарий «владелец и чужой пишут боту» против фейкового Telegram (лаборатория brain-link).

  bot_scenario.py full --tg URL --owner ID --secrets DIR --claude-log FILE --brain-home DIR [--report FILE]
  bot_scenario.py say  --tg URL --owner ID "текст"          — одно сообщение от владельца (для verify)

Секреты читаются из файлов DIR/bot_token и DIR/claude_token и никогда не печатаются (сравниваются sha256).
Каждая проверка печатает PASS/FAIL; код выхода 1, если был хоть один FAIL. Только стандартная библиотека.
"""
import argparse
import glob
import hashlib
import json
import os
import sys
import time
import urllib.request

RESULTS = []
STRANGER = 424242001
GROUP_CHAT = -1001234567


def check(name, ok, detail=""):
    RESULTS.append({"name": name, "ok": bool(ok), "detail": detail})
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, (" — " + detail) if detail else ""), flush=True)
    return ok


def http(url, data=None, timeout=10):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class TG:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def sent(self):
        return http(self.base + "/_ctl/sent")

    def say(self, frm, text, chat=None):
        return http(self.base + "/_ctl/update", {"from": frm, "chat": chat if chat is not None else frm, "text": text})

    def exchange(self, frm, text, timeout=60, settle=1.5, chat=None):
        """Отправить и дождаться новых исходящих (бот может ответить несколькими кусками)."""
        before = len(self.sent()["sent"])
        self.say(frm, text, chat=chat)
        deadline = time.time() + timeout
        last_n, last_change = before, time.time()
        while time.time() < deadline:
            n = len(self.sent()["sent"])
            if n != last_n:
                last_n, last_change = n, time.time()
            if n > before and time.time() - last_change >= settle:
                break
            time.sleep(0.3)
        return self.sent()["sent"][before:]


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def read_secret(d, name):
    with open(os.path.join(d, name), encoding="utf-8") as f:
        return f.read().strip()


def claude_records(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    except OSError:
        return []


def wait_new_record(path, n_before, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        recs = claude_records(path)
        if len(recs) > n_before:
            return recs[-1]
        time.sleep(0.3)
    return None


# окружение дочернего claude по контракту бота (child_env); LC_CTYPE иногда добавляет сам Python (PEP 538),
# __CF_USER_TEXT_ENCODING — сама macOS (локальный прогон сценария), на сервере его нет
ALLOWED_CHILD_ENV = {"HOME", "PATH", "LANG", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "DISABLE_AUTOUPDATER",
                     "CLAUDE_CODE_DISABLE_CLAUDE_MDS", "CLAUDE_CODE_DISABLE_AUTO_MEMORY", "LC_CTYPE",
                     "__CF_USER_TEXT_ENCODING"}


def argval(argv, name):
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None


def check_isolation(tag, rec, mode, claude_sha, settings):
    if not check("%s: fake claude вызван" % tag, rec is not None):
        return
    argv = rec["argv"]
    check("%s: режим %s" % (tag, mode), rec["mode"] == mode, "получен %s" % rec["mode"])
    check("%s: -p и --settings %s" % (tag, settings), "-p" in argv and argval(argv, "--settings") == settings)
    check("%s: --setting-sources пустой" % tag, argval(argv, "--setting-sources") == "")
    check("%s: --strict-mcp-config и --max-turns" % tag, "--strict-mcp-config" in argv and "--max-turns" in argv)
    tools = argval(argv, "--tools")
    allowed = argval(argv, "--allowedTools") or ""
    disallowed = (argval(argv, "--disallowedTools") or "").split(",")
    if mode == "files":
        check("%s: --tools Read,Grep,Glob" % tag, tools == "Read,Grep,Glob", str(tools))
        check("%s: --allowedTools только путевые Read(//…)" % tag,
              bool(allowed) and all(x.startswith("Read(//") for x in allowed.split(",")), allowed[:120])
        check("%s: Bash/Write/Edit/WebFetch/WebSearch запрещены" % tag,
              all(t in disallowed for t in ("Bash", "Write", "Edit", "WebFetch", "WebSearch")))
        check("%s: память в промпте (метка из MEMORY.md)" % tag, rec["prompt_has_memory_marker"])
        check("%s: cwd = memory" % tag, rec["cwd"].rstrip("/").endswith("/memory"), rec["cwd"])
    else:
        check("%s: --tools WebFetch,WebSearch" % tag, tools == "WebFetch,WebSearch", str(tools))
        check("%s: Read/Grep/Glob/Bash/Write запрещены" % tag,
              all(t in disallowed for t in ("Read", "Grep", "Glob", "Bash", "Write")))
        check("%s: памяти в промпте НЕТ" % tag, not rec["prompt_has_memory_marker"])
        check("%s: cwd и HOME — пустые web-папки" % tag,
              rec["cwd"].endswith("web-cwd") and (rec["home"] or "").endswith("web-home"), rec["cwd"])
    check("%s: ANTHROPIC_API_KEY нет в окружении claude" % tag, not rec["has_anthropic_api_key"])
    check("%s: токена бота нет в окружении claude" % tag,
          not rec["has_bot_token_var"] and not rec["env_has_tg_like_value"])
    extra = sorted(set(rec["env_keys"]) - ALLOWED_CHILD_ENV)
    check("%s: окружение claude — только белый список" % tag, not extra, ("лишние: %s" % extra) if extra else "")
    check("%s: токен подписки = тот, что положил put-token" % tag,
          rec["oauth_present"] and rec["oauth_prefix_ok"] and rec["oauth_sha256"] == claude_sha)
    check("%s: CLAUDE_CONFIG_DIR — состояние бота /var/lib/brain-bot, не ~/.claude" % tag,
          (rec["claude_config_dir"] or "") == "/var/lib/brain-bot/claude-config", str(rec["claude_config_dir"]))
    # RT-11: claude бота работает под brainbot (группа brain) — память читает, токены brain не видны
    check("%s: claude запущен под brainbot, не brain" % tag, rec.get("user") == "brainbot", str(rec.get("user")))


def full(a):
    tg = TG(a.tg)
    owner = int(a.owner)
    bot_tok = read_secret(a.secrets, "bot_token")
    cl_tok = read_secret(a.secrets, "claude_token")
    log = a.claude_log

    # 0. бот ходит в фейковый Telegram с токеном из LoadCredential
    deadline = time.time() + 90
    while time.time() < deadline and not tg.sent()["methods"].get("getUpdates"):
        time.sleep(1)
    st = tg.sent()
    check("бот опрашивает getUpdates (TELEGRAM_API_BASE работает)", st["methods"].get("getUpdates", 0) > 0)
    check("токен бота в запросах = токен из put-token (по sha256)",
          sha(bot_tok) in st["token_sha256"] and len(st["token_sha256"]) == 1)

    # 1. чужой и группа — тишина
    out = tg.exchange(STRANGER, "привет, я чужой", timeout=12)
    check("чужому бот молчит", not out, "ответов: %d" % len(out))
    out = tg.exchange(owner, "/status", timeout=12, chat=GROUP_CHAT)
    check("сообщение владельца из группы игнорируется", not out, "ответов: %d" % len(out))

    # 2. /status
    out = tg.exchange(owner, "/status")
    check("/status отвечает", any("Статус" in m["text"] for m in out), "%d сообщений" % len(out))

    # 3. режим «файлы»
    n = len(claude_records(log))
    out = tg.exchange(owner, "что у меня в памяти? лабораторный вопрос")
    check("файлы: ответ от fake claude", any("LAB-ANSWER mode=files" in m["text"] for m in out),
          (out[0]["text"][:80] if out else "нет ответа"))
    check_isolation("файлы", wait_new_record(log, n), "files", sha(cl_tok), a.settings)

    # 4. режим «веб»
    n = len(claude_records(log))
    out = tg.exchange(owner, "посмотри https://example.com/lab-page")
    check("веб: ответ от fake claude", any("LAB-ANSWER mode=web" in m["text"] for m in out))
    check_isolation("веб", wait_new_record(log, n), "web", sha(cl_tok), a.settings)

    # 5. модель
    n = len(claude_records(log))
    tg.exchange(owner, "/deep лабораторный глубокий вопрос")
    rec = wait_new_record(log, n)
    check("/deep → --model opus", rec is not None and rec.get("model") == "opus", str(rec and rec.get("model")))
    n = len(claude_records(log))
    tg.exchange(owner, "обычный вопрос без deep")
    rec = wait_new_record(log, n)
    check("по умолчанию --model sonnet", rec is not None and rec.get("model") == "sonnet")

    # 6. фильтр секретов на выходе
    out = tg.exchange(owner, "LAB_LEAK_TOKEN покажи")
    check("утечка токена подписки из ответа модели скрыта", any("Ответ скрыт" in m["text"] for m in out))
    out = tg.exchange(owner, "LAB_LEAK_PATTERN покажи")
    check("строка-как-токен Telegram из ответа модели скрыта", any("Ответ скрыт" in m["text"] for m in out))

    # 7. «запомни» → inbox
    out = tg.exchange(owner, "запомни лабораторная заметка для inbox")
    check("«запомни» подтверждено", any("Записал" in m["text"] for m in out))
    found = []
    for p in glob.glob(os.path.join(a.brain_home, "memory", "inbox", "*_tg*.md")):
        try:
            with open(p, encoding="utf-8") as f:
                if "лабораторная заметка для inbox" in f.read():
                    found.append(os.path.basename(p))
        except OSError:
            pass
    check("заметка в memory/inbox на сервере", bool(found), ", ".join(found))

    # итог по всем исходящим
    st = tg.sent()
    texts = [m["text"] or "" for m in st["sent"]]
    check("ни в одном исходящем нет токенов", not any(bot_tok in t or cl_tok in t for t in texts))
    check("все исходящие — только владельцу", all(str(m["chat_id"]) == str(owner) for m in st["sent"]))
    check("вызовов claude ≤ 30 (лимит в час)", len(claude_records(log)) <= 30)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump({"results": RESULTS, "methods": st["methods"], "sent_count": len(st["sent"])}, f,
                      ensure_ascii=False, indent=1)
    bad = [r for r in RESULTS if not r["ok"]]
    print("ИТОГ сценария бота: %d PASS, %d FAIL" % (len(RESULTS) - len(bad), len(bad)), flush=True)
    return 1 if bad else 0


def say(a):
    out = TG(a.tg).exchange(int(a.owner), a.text, timeout=a.timeout)
    print(json.dumps({"replies": [m["text"][:200] for m in out]}, ensure_ascii=False))
    return 0 if out else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    f = sub.add_parser("full")
    f.add_argument("--tg", required=True)
    f.add_argument("--owner", required=True)
    f.add_argument("--secrets", required=True)
    f.add_argument("--claude-log", dest="claude_log", required=True)
    f.add_argument("--brain-home", dest="brain_home", default="/home/brain")
    f.add_argument("--settings", default="/etc/brain-bot/claude_settings.json")
    f.add_argument("--report")
    s = sub.add_parser("say")
    s.add_argument("--tg", required=True)
    s.add_argument("--owner", required=True)
    s.add_argument("--timeout", type=int, default=60)
    s.add_argument("text")
    a = ap.parse_args()
    if a.cmd == "full":
        return full(a)
    if a.cmd == "say":
        return say(a)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
