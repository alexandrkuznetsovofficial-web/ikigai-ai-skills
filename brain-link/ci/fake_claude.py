#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fake_claude.py — заглушка `claude` для лаборатории brain-link (GitHub Actions, не для учеников).

Ставится на «сервер» лаборатории как /home/brain/.local/bin/claude (шаг `brain-link claude` видит, что
claude уже стоит, и только проверяет `--version`). Эмулирует `claude -p`: читает промпт из stdin, отвечает
строкой LAB-ANSWER и пишет в журнал, ЧТО ему передали — для проверок изоляции бота:
  argv целиком; имена переменных окружения; есть ли ANTHROPIC_API_KEY / BOT_TOKEN / похожее на токен
  Telegram; sha256 токена подписки (сам токен — никогда); cwd; длину промпта и есть ли в нём метка памяти.

Журнал (JSON Lines): $FAKE_CLAUDE_LOG, иначе <родитель CLAUDE_CONFIG_DIR>/fake_claude.jsonl
(у бота это ~/.local/state/brain-bot — единственное место, куда юнит пускает запись).

Особые промпты (проверка фильтра секретов в боте):
  LAB_LEAK_TOKEN    — печатает полученный токен подписки (бот обязан скрыть ответ: known-secret)
  LAB_LEAK_PATTERN  — печатает строку вида токена Telegram (бот обязан скрыть ответ: telegram-token)
Только стандартная библиотека.
"""
import hashlib
import json
import os
import re
import sys
import time

VERSION = "2.1.999 (Claude Code) [lab fake]"
MEMORY_MARKER = "LAB-MEMORY-MARKER-7f3a"
TG_LIKE = re.compile(r"\d{8,10}:[A-Za-z0-9_-]{35}")


def log_path():
    p = os.environ.get("FAKE_CLAUDE_LOG")
    if p:
        return p
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    if cfg:
        return os.path.join(os.path.dirname(cfg.rstrip("/")), "fake_claude.jsonl")
    return os.path.join(os.environ.get("HOME") or "/tmp", ".cache", "fake_claude.jsonl")


def opt(argv, name):
    """Значение флага --name (следующий аргумент) или None."""
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def main():
    argv = sys.argv[1:]
    if "--version" in argv or "-v" in argv:
        print(VERSION)
        return 0
    if "--help" in argv:
        print("Usage: claude [options] (lab fake). Options: -p, --tools, --allowedTools, --disallowedTools, "
              "--settings, --setting-sources, --model, --max-turns, --output-format, --strict-mcp-config")
        return 0
    if "-p" not in argv and "--print" not in argv:
        print("lab fake claude: только -p", file=sys.stderr)
        return 2
    prompt = sys.stdin.read()
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    env_values = "\n".join(v for k, v in os.environ.items() if k != "CLAUDE_CODE_OAUTH_TOKEN")
    tools = opt(argv, "--tools") or ""
    rec = {
        "ts": time.time(),
        "argv": argv,
        "env_keys": sorted(os.environ.keys()),
        "has_anthropic_api_key": "ANTHROPIC_API_KEY" in os.environ,
        "has_bot_token_var": any(k in os.environ for k in ("BOT_TOKEN", "TELEGRAM_BOT_TOKEN")),
        "env_has_tg_like_value": bool(TG_LIKE.search(env_values)),
        "oauth_present": bool(token),
        "oauth_prefix_ok": token.startswith("sk-ant-oat"),
        "oauth_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest() if token else None,
        "cwd": os.getcwd(),
        "home": os.environ.get("HOME"),
        "claude_config_dir": os.environ.get("CLAUDE_CONFIG_DIR"),
        "prompt_len": len(prompt),
        "prompt_has_memory_marker": MEMORY_MARKER in prompt,
        "mode": "web" if "WebFetch" in tools else ("files" if "Read" in tools else "?"),
        "model": opt(argv, "--model"),
    }
    try:
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as ex:
        print("lab fake claude: журнал не записан: %s" % type(ex).__name__, file=sys.stderr)
    if "LAB_LEAK_TOKEN" in prompt:
        print("вот токен: %s" % token)
    elif "LAB_LEAK_PATTERN" in prompt:
        print("вот строка: " + "1234567890" + ":" + "Q" * 35)
    else:
        print("LAB-ANSWER mode=%s model=%s" % (rec["mode"], rec["model"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
