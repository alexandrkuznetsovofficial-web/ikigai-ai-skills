#!/usr/bin/env bash
# Установка окружения пака «Второй мозг ↔ почта и календарь».
# Создаёт отдельный venv ~/.venvs/mck и ставит зависимости. Повторный запуск безопасен.
# venv твоего бота не трогается: скрипты пака вызываются через ~/.venvs/mck/bin/python.
set -u

VENV="${MCK_VENV:-$HOME/.venvs/mck}"
DIR="$(cd "$(dirname "$0")" && pwd)"
REQ="$DIR/requirements.txt"

say() { printf '%s\n' "$*"; }

PY=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  say '{"ok": false, "human": "python3 не найден. На Mac: brew install python; на Ubuntu: sudo apt install -y python3 python3-venv"}'
  exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
  mkdir -p "$(dirname "$VENV")"
  if ! "$PY" -m venv "$VENV" 2>/tmp/mck_venv_err.txt; then
    if command -v apt-get >/dev/null 2>&1; then
      say "venv не создался, ставлю python3-venv (нужен sudo)…"
      sudo -n apt-get install -y python3-venv >/dev/null 2>&1 || true
      "$PY" -m venv "$VENV" || { say '{"ok": false, "human": "не удалось создать venv, см. /tmp/mck_venv_err.txt"}'; exit 1; }
    else
      say '{"ok": false, "human": "не удалось создать venv, см. /tmp/mck_venv_err.txt"}'
      exit 1
    fi
  fi
fi

# Папка доступов: 700, иначе на общем сервере соседний пользователь увидит состав файлов
mkdir -p "$HOME/.config/mail-calendar-kit" && chmod 700 "$HOME/.config/mail-calendar-kit"

"$VENV/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
if ! "$VENV/bin/python" -m pip install --quiet -r "$REQ" 2>/tmp/mck_pip_err.txt; then
  say '{"ok": false, "human": "pip не смог поставить зависимости, см. /tmp/mck_pip_err.txt (чаще всего нет интернета)"}'
  exit 1
fi

"$VENV/bin/python" - <<'EOF'
import json, sys
mods = {}
for m in ("caldav", "icalendar", "recurring_ical_events", "dotenv", "googleapiclient", "google_auth_oauthlib", "notion_client"):
    try:
        __import__(m); mods[m] = True
    except Exception:
        mods[m] = False
ok = all(mods[m] for m in ("caldav", "icalendar", "recurring_ical_events", "dotenv"))
print(json.dumps({"ok": ok, "python": sys.executable, "modules": mods,
                  "human": "окружение готово: " + sys.executable if ok else "часть модулей не встала, см. modules"},
                 ensure_ascii=False))
sys.exit(0 if ok else 1)
EOF
