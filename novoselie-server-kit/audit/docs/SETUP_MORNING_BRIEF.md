<!-- CLAUDE: Это файл-автозапуск. При открытии — НЕМЕДЛЕННО выполни всё из раздела ВЫПОЛНИ. Без вопросов, без ожидания. -->
<!-- kit_version: 2.1 -->

# Автонастройка утреннего брифинга

> Перетащи этот файл в чат Claude Code — он сделает всё сам.
> Бот в Telegram не обязателен: без него брифинг приходит файлом в память и системным уведомлением.
>
> **Два режима (kit 2.1).** **С ботом** (связка `brain-link`: компьютер — мастерская, сервер — база) брифинг
> живёт **только на сервере**: его ставит `brain-link bot` таймером `brain-brief.timer`, а здесь мы лишь
> выключаем локальный, чтобы не приходило два. **Без бота** — всё как раньше: скрипт и расписание на компьютере.

---

## ВЫПОЛНИ НЕМЕДЛЕННО (без вопросов):

### Шаг 0. Какая система и где память

Прочитай `~/.claude/ikigai_env.json` (профиль компьютера, его пишет скилл `ikigai-preflight`). Файла нет —
запусти `bash ~/.claude/skills/ikigai-preflight/scripts/probe.sh`. Из профиля нужны два поля.

`workspace` — рабочая папка второго мозга (где лежит `CLAUDE.md`). **Папка памяти — `<workspace>/memory`.**

`os_branch`:

- `mac` — шаги ниже как есть, расписание через **launchd** (раздел «Шаг 4»).
- `windows` — команда Python `py -3` вместо `python3`, расписание через Планировщик заданий
  с «запуском при первой возможности» (раздел «Шаг 4W»). Человеку не показывай `crontab`, `chmod`, `~` и `which`.
- `linux` — это сервер, он не спит: расписание через cron (раздел «Шаг 4L»).

**Почему не cron на ноутбуке.** Cron запускает задачу, только если компьютер в эту минуту не спит.
Крышка закрыта в 08:00 — брифинг не придёт и не догонит. launchd на Mac и Планировщик Windows
с «запуском при первой возможности» выполняют пропущенный запуск, как только компьютер проснётся.

### Шаг 0.5. Режим: стоит ли связка brain-link с ботом

Утренний брифинг живёт в **одном** месте (`KIT_CONVENTIONS.md`, §8). Проверь, стоит ли связка:

| Что | Mac | Windows |
|---|---|---|
| Файл доступа связки | `~/.config/brain/server_access` | `%USERPROFILE%\.config\brain\server_access` |
| Состояние бота | `brain-link status` (скилл `brain-link`) | то же |

**Файл доступа есть и `brain-link status` показывает работающего бота → режим «с ботом».** Брифинг уже ставит
`brain-link bot` на сервере (`brain-brief.timer`), локальный скрипт не нужен. Сделай только это:

1. Найди локальное расписание брифинга (команды — в Шаге 1) и **выключи его, ничего не удаляя**:

   | Mac | Windows |
   |---|---|
   | `launchctl bootout gui/$(id -u)/com.ikigai.morning-brief` и переименуй plist в `com.ikigai.morning-brief.plist.disabled` | `schtasks /Change /TN "Ikigai morning-brief" /Disable` (и старую `IkigaiMorningBrief`, если есть) |

   Строку брифинга в cron на Mac, если она есть, убирай тем же безопасным способом, что в Шаге 4.
2. Скрипт `~/morning_brief.py` и `~/.config/morning-brief/env` не удаляй — пригодятся, если откажешься от бота.
3. Признак: в списке задач брифинга нет (Шаг 5, «Где стоит расписание») **и** следующим утром брифинг пришёл
   в Telegram **один раз**. Пришло два — где-то осталось локальное расписание, найди его по Шагу 1.
4. Отчёт человеку: «Брифинг приходит с сервера (`brain-brief.timer`), локальный выключен. Время брифинга
   и состав — на сервере, скажи, если нужно поменять».

Дальше этот файл **не выполняй**: Шаги 1–5 — только для режима **без бота** (связки нет или бот не ставили).
Человек хочет брифинг с компьютера при работающем боте — объясни, что придут два, и спроси, какой оставить.

### Шаг 1. Аудит

```bash
crontab -l 2>/dev/null | grep -i "brief\|morning\|утр" || echo "BRIEF_NOT_IN_CRON"
ls ~/Library/LaunchAgents/com.ikigai.morning-brief.plist 2>/dev/null || echo "BRIEF_NOT_IN_LAUNCHD"   # Mac
ls ~/morning_brief.py 2>/dev/null || echo "SCRIPT_NOT_FOUND"
grep -c "commitments" ~/morning_brief.py 2>/dev/null || echo "NO_COMMITMENTS_BLOCK"
grep -cE '^(BOT_TOKEN|TELEGRAM_TOKEN) *= *"[0-9]' ~/morning_brief.py 2>/dev/null || echo "NO_TOKEN_IN_CODE"
ls ~/.config/morning-brief/env 2>/dev/null || echo "NO_ENV_FILE"
# память: по профилю; поиск по диску — только запасной путь, без ~/.claude/
ls "<workspace>/memory/MEMORY.md" 2>/dev/null || find ~ -name "MEMORY.md" -not -path "$HOME/.claude/*" -not -path "*/node_modules/*" -not -path "*/.Trash/*" 2>/dev/null | head -3
find ~ -name "bot.env" -not -path "$HOME/.claude/*" -not -path "*/.Trash/*" 2>/dev/null | head -3
```

Windows — расписание проверяй так: `powershell -NoProfile -Command "Get-ScheduledTask | Where-Object TaskName -like '*orning*' | Select-Object TaskName, State"`.

**Логика по результатам:**

- Скрипт есть, в нём есть блок `commitments`, токена бота в коде нет (`NO_TOKEN_IN_CODE`), расписание стоит
  в launchd (Mac) / Планировщике со `StartWhenAvailable` (Windows) / cron (сервер Linux) → перейди к Проверке (Шаг 5).
- Скрипт есть, но старый (без блока `commitments` или с токеном в коде) → **обнови скрипт** (ниже), затем дальше по списку.
- **Mac, брифинг стоит в cron** → Шаг 4 (перенос на launchd). Строку из cron убираешь только после того,
  как launchd доставил брифинг.
- **Windows, задача без запуска после пропуска** (старое имя `IkigaiMorningBrief`) → Шаг 4W.
- Скрипта нет → Шаги 2–4.

**Как обновить старый скрипт.** Сохрани его рядом как `~/morning_brief.py.v1` (не удаляй) и запиши новый
целиком из Шага 3. Из старого переносятся только значения: `TZ_OFFSET`, путь к памяти (сверь с профилем —
должен быть `<workspace>/memory`) и токен бота с `OWNER_ID` — **не в код, а в файл `env`** (Шаг 2.2).
Если человек правил старый скрипт под себя и просит сохранить правки — заменяй по частям. Заменяемые части:

1. **строка импортов** → `import os, re, json, shutil, subprocess, sys` (без `re` пятничный блок падает,
   без `sys` и `shutil` — уведомление и вход через Связку ключей);
2. **блок настроек вверху**: строки `BOT_TOKEN = "…"` и `OWNER_ID = "…"` удалить из кода, вместо них —
   `ENV_FILE`, функция `load_env` и строки `CFG` / `BOT_TOKEN` / `OWNER_ID` / `DELIVERY` / `CLAUDE_BIN`;
   `MEMORY_BASE` → `<workspace>/memory`; строку `PYTHON_BIN` можно убрать — она больше не нужна;
3. функция **`_read`** — целиком (в старых версиях её нет или она без параметра `limit`);
4. функция **`collect_context`** — целиком;
5. функция **`collect_overdue_commitments`** — добавить;
6. функции **`subscription_token`**, **`via_cli`**, **`claude_generate`** — новая `claude_generate` целиком,
   две другие добавить (старая искала токен по неверному ключу и на Mac не находила его вовсе);
7. функции **`deliver_file`** и **`notify`** — добавить; **`main`** — целиком.

Функцию `tg_send` можно оставить старую.

---

### Шаг 2. Определи параметры

**2.1. Значения.**

| Переменная | Откуда взять |
|---|---|
| `MEMORY_PATH` | `<workspace>/memory` из профиля (Шаг 0). Профиля нет — найденный в Шаге 1 `MEMORY.md` вне `~/.claude/` (служебные копии Claude Code там не годятся); несколько — спроси человека, какая папка его |
| `TZ_OFFSET` | 3 (МСК), если не указан другой |
| `DELIVERY` | найден `bot.env` с токеном → `telegram`; не найден → `file` (брифинг файлом и уведомлением, без бота) |
| `BOT_TOKEN`, `OWNER_ID` | только для `telegram`: из найденного `bot.env` → поля `TIM_BOT_TOKEN` / `BOT_TOKEN` и `TIM_BOT_OWNER_USER_ID` / `OWNER_ID` |
| `CLAUDE_BIN` | путь к консольному Claude Code: Mac / Linux — `command -v claude`; Windows — `cygpath -w "$(command -v claude.exe \|\| command -v claude.cmd)"` 🧪 |

Если `bot.env` не найден — проверь в нестандартных местах:
```bash
find ~ -name "*.env" -not -path "$HOME/.claude/*" -not -path "*/.Trash/*" -not -path "*/node_modules/*" 2>/dev/null | xargs grep -l "TOKEN" 2>/dev/null | head -5
```
Совсем нет — не жди ответа: ставь `DELIVERY=file` и скажи человеку одной строкой: «Бота не нашёл — брифинг
будет приходить файлом `memory/brief_<дата>.md` и уведомлением. Появится бот — скажи, переключу».

**2.2. Секреты — не в коде.** Токен бота и `OWNER_ID` живут в отдельном файле, закрытом для других
пользователей компьютера: Mac / Linux — `~/.config/morning-brief/env`, Windows —
`%USERPROFILE%\.config\morning-brief\env`. Скрипт брифинга читает его сам. Токен в чат не выводи —
переноси скриптом:

```bash
mkdir -p ~/.config/morning-brief && chmod 700 ~/.config/morning-brief
SRC="<путь к найденному bot.env, для DELIVERY=file оставь пустым>"
TOK=""; OID=""
if [ -n "$SRC" ]; then
  TOK=$(grep -E '^(TIM_BOT_TOKEN|BOT_TOKEN)=' "$SRC" | head -1 | cut -d= -f2- | tr -d "\"' \r")
  OID=$(grep -E '^(TIM_BOT_OWNER_USER_ID|OWNER_ID)=' "$SRC" | head -1 | cut -d= -f2- | tr -d "\"' \r")
fi
( umask 077
  {
    echo "# утренний брифинг: секреты и способ доставки. Не в git, не в облако."
    echo "DELIVERY=$([ -n "$TOK" ] && [ -n "$OID" ] && echo telegram || echo file)"
    echo "BOT_TOKEN=$TOK"
    echo "OWNER_ID=$OID"
    echo "CLAUDE_BIN=<CLAUDE_BIN из таблицы>"
  } > ~/.config/morning-brief/env )
chmod 600 ~/.config/morning-brief/env
grep -c "=" ~/.config/morning-brief/env; grep "^DELIVERY=" ~/.config/morning-brief/env
```

На Windows те же команды выполняются в Git Bash (папка `~` там и есть `%USERPROFILE%`), `chmod` там ничего
не меняет — файл и так лежит в профиле пользователя, куда другие пользователи компьютера не заходят.
Признак: выведено число строк (5) и строка `DELIVERY=…`, токен на экране не показан.

---

### Шаг 3. Создай скрипт ~/morning_brief.py

Напиши файл `~/morning_brief.py`, подставив найденные значения (на Windows — `%USERPROFILE%\morning_brief.py`,
путь к памяти в виде `C:\Users\Имя\…\memory`):

```python
#!/usr/bin/env python3
"""Личный утренний брифинг — читает второй мозг и присылает: в Telegram-бота
или (без бота) файлом memory/brief_<дата>.md плюс системным уведомлением."""
import os, re, json, shutil, subprocess, sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

TZ_OFFSET   = ПОДСТАВИТЬ  # например 3 для МСК
MEMORY_BASE = Path(r"ПОДСТАВИТЬ")  # <workspace>/memory
MODEL       = "claude-haiku-4-5-20251001"

# Секреты и способ доставки — не в коде, а в файле env (chmod 600)
ENV_FILE = Path.home() / ".config" / "morning-brief" / "env"


def load_env(path=ENV_FILE):
    cfg = {}
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip("\"'")
    except FileNotFoundError:
        pass
    return cfg


CFG        = load_env()
BOT_TOKEN  = CFG.get("BOT_TOKEN", "")
OWNER_ID   = CFG.get("OWNER_ID", "")
DELIVERY   = CFG.get("DELIVERY") or ("telegram" if BOT_TOKEN and OWNER_ID else "file")
CLAUDE_BIN = CFG.get("CLAUDE_BIN") or "claude"

TZ = timezone(timedelta(hours=TZ_OFFSET))


def _read(path, limit=None):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        return text[:limit] if limit else text
    except Exception:
        return None


def collect_context():
    parts = []
    f = MEMORY_BASE / "MEMORY.md"
    if f.exists():
        parts.append("=== MEMORY.md ===\n" + (_read(f, 2500) or ""))
    # Фокус: memory/ACTIVE.md — единственное место; старый ACTIVE.md в корне — запасной путь
    for af in (MEMORY_BASE / "ACTIVE.md", MEMORY_BASE.parent / "ACTIVE.md"):
        if af.exists():
            parts.append("=== ACTIVE.md ===\n" + (_read(af, 2500) or ""))
            break
    tasks_dir = MEMORY_BASE / "tasks"
    if tasks_dir.exists():
        for tf in sorted(tasks_dir.glob("task_*.md"), reverse=True)[:3]:
            parts.append(f"=== {tf.name} ===\n" + (_read(tf, 700) or ""))

    # Просроченные обещания из memory/commitments.md — новый блок не должен ронять брифинг
    try:
        overdue = collect_overdue_commitments(MEMORY_BASE / "commitments.md")
        if overdue:
            parts.insert(0, overdue)
    except Exception as e:
        print(f"  WARN commitments: {e}")

    # Пятница — напомнить про дистилляцию недели и сколько дней с прошлой
    try:
        if datetime.now(TZ).weekday() == 4:
            dates = []
            for df in (MEMORY_BASE / "distill").glob("distill_*.md"):
                m = re.search(r"\d{4}-\d{2}-\d{2}", df.stem)
                if m:
                    try:
                        dates.append(datetime.strptime(m.group(0), "%Y-%m-%d").date())
                    except ValueError:
                        pass
            ago = f"{(datetime.now(TZ).date() - max(dates)).days} дн. назад" if dates else "ни разу"
            parts.insert(0, "=== ПЯТНИЦА: DISTILL ===\nОдной строкой в конце брифинга: «Сегодня пятничная "
                            f"дистилляция — скажи /weekly-distill. Прошлая: {ago}».")
    except Exception as e:
        print(f"  WARN distill: {e}")

    return "\n\n".join(parts) or "Второй мозг пуст."


def collect_overdue_commitments(path):
    """Строки журнала со статусом open и сроком проверки <= сегодня → блок для брифинга."""
    text = _read(path)
    if not text:
        return ""
    today = datetime.now(TZ).date()
    items = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        # колонки: дата | обязательство | проверить | статус | источник — считаем С КОНЦА строки,
        # чтобы «|» внутри текста обязательства не сдвигал колонки
        if len(cells) < 5 or cells[-2].lower() != "open":
            continue
        try:
            made = datetime.strptime(cells[0], "%Y-%m-%d").date()
            check = datetime.strptime(cells[-3], "%Y-%m-%d").date()
        except ValueError:
            continue
        what = " | ".join(cells[1:-3])
        if check <= today:
            items.append((made, f"- {(today - made).days} дн. назад: {what} (проверка была {check:%d.%m})"))
    if not items:
        return ""
    items.sort()
    return ("=== ПРОСРОЧЕННЫЕ ОБЕЩАНИЯ ===\n"
            "Назови это в брифинге прямо, отдельным блоком «🪞 Обещал — не закрыто», формулой "
            "«N дней назад ты решил X — не сделано». Без смягчения и без упрёка, максимум 3 самых старых, "
            "и спроси: делаем, переносим или снимаем осознанно.\n" + "\n".join(i for _, i in items[:3]))


def subscription_token():
    """Токен подписки Claude Code: поле claudeAiOauth.accessToken.
    Linux / Windows — файл ~/.claude/.credentials.json; Mac — Связка ключей, запись «Claude Code-credentials»."""
    def pick(raw):
        try:
            o = json.loads(raw).get("claudeAiOauth") or {}
            return o.get("accessToken") if isinstance(o, dict) else None
        except Exception:
            return None
    try:
        t = pick((Path.home() / ".claude" / ".credentials.json").read_text(encoding="utf-8"))
        if t:
            return t, "credentials.json"
    except Exception:
        pass
    if sys.platform == "darwin":
        try:
            raw = subprocess.run(["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                                 capture_output=True, text=True, timeout=15).stdout.strip()
            t = pick(raw)
            if t:
                return t, "Связка ключей"
        except Exception:
            pass
    return None, None


def via_cli(prompt):
    """Запасной путь под той же подпиской: консольный Claude Code (`claude -p`).
    Ключ ANTHROPIC_API_KEY из окружения убираем, иначе он уйдёт на платный ключ."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    try:
        r = subprocess.run([CLAUDE_BIN, "-p", "--model", "haiku"], input=prompt, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=240, env=env)
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out:
            return out
        print(f"  claude -p код {r.returncode}: {(r.stderr or '')[:150]}")
    except Exception as e:
        print(f"  claude -p err: {e}")
    return None


def claude_generate(context):
    import urllib.request, urllib.error
    now = datetime.now(TZ)
    yesterday = (now - timedelta(days=1)).strftime("%d.%m.%Y")
    today = now.strftime("%d.%m.%Y")
    prompt = (
        f"Ты — личный AI-ассистент. Пишешь утренний брифинг владельцу.\n\n"
        f"Контекст из его второго мозга:\n{context[:4500]}\n\n"
        f"Задача:\n"
        f"1. Что планировалось вчера ({yesterday}) — найди задачи, намерения\n"
        f"2. Кратко: выполнено / осталось\n"
        f"3. Фокус на сегодня ({today}): 2-3 конкретных действия по целям\n"
        f"4. Дедлайны если есть\n"
        f"5. Если в контексте есть блок ПРОСРОЧЕННЫЕ ОБЕЩАНИЯ или ПЯТНИЦА — выполни его указание\n\n"
        f"Формат: plain text, до 12 строк, тёплый тон. "
        f"Начни с «Доброе утро!» и имени (возьми из MEMORY.md)."
    )
    body = json.dumps({"model": MODEL, "max_tokens": 700,
                       "messages": [{"role": "user", "content": prompt}]}).encode()

    def call_api(kind, headers):
        try:
            req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read())
            text = "".join(c.get("text", "") for c in d.get("content", []) if c.get("type") == "text").strip()
            if text:
                print(f"  Claude via {kind}: OK")
                return text
        except urllib.error.HTTPError as e:
            print(f"  Claude {kind} HTTP {e.code}: {e.read()[:100]}")
        except Exception as e:
            print(f"  Claude {kind} err: {e}")
        return None

    # 1) подписка: токен Claude Code
    token, where = subscription_token()
    if token:
        text = call_api("oauth (" + where + ")", {
            "Authorization": "Bearer " + token, "anthropic-beta": "oauth-2025-04-20",
            "anthropic-version": "2023-06-01", "content-type": "application/json"})
        if text:
            return text
    # 2) подписка: консольный Claude Code (сам обновит просроченный токен)
    text = via_cli(prompt)
    if text:
        print("  Claude via claude -p: OK")
        return text
    # 3) крайний запасной путь — платный ключ, только если он задан
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        text = call_api("api", {"x-api-key": api_key, "anthropic-version": "2023-06-01",
                                "content-type": "application/json"})
        if text:
            return text
    return "Не удалось сгенерировать брифинг — нет доступа к Claude (подписка / claude -p / API-ключ)."


def tg_send(text):
    import urllib.request
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    body = json.dumps({"chat_id": OWNER_ID, "text": text}).encode()
    try:
        req = urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:
        print(f"  TG error: {e}")
        return False


def deliver_file(text):
    """Без бота: брифинг кладётся в память — memory/brief_ГГГГ-ММ-ДД.md."""
    out = MEMORY_BASE / f"brief_{datetime.now(TZ):%Y-%m-%d}.md"
    out.write_text(f"# Утренний брифинг · {datetime.now(TZ):%d.%m.%Y}\n\n{text}\n", encoding="utf-8")
    return out


def notify(title, text):
    """Системное уведомление: Mac — Центр уведомлений, Windows — всплывающее окно у часов, Linux — notify-send."""
    text = text[:200]
    try:
        if sys.platform == "darwin":
            subprocess.run(["osascript", "-e", "on run argv",
                            "-e", "display notification (item 2 of argv) with title (item 1 of argv)",
                            "-e", "end run", title, text], timeout=15)
        elif os.name == "nt":
            ps = ("Add-Type -AssemblyName System.Windows.Forms, System.Drawing; "
                  "$n = New-Object System.Windows.Forms.NotifyIcon; "
                  "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
                  "$n.ShowBalloonTip(15000, $env:MB_TITLE, $env:MB_TEXT, 'Info'); Start-Sleep 15; $n.Dispose()")
            subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                           env=dict(os.environ, MB_TITLE=title, MB_TEXT=text), timeout=40)
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", title, text], timeout=15)
    except Exception as e:
        print(f"  WARN notify: {e}")


def main():
    now = datetime.now(TZ)
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] morning_brief START · доставка: {DELIVERY}")
    context = collect_context()
    print(f"  Context: {len(context)} chars")
    brief = claude_generate(context)
    if DELIVERY == "telegram":
        ok = tg_send(brief)
        print(f"  TG: {'OK' if ok else 'FAIL'}")
        if not ok:   # бот недоступен — брифинг не теряется
            print(f"  FILE: OK {deliver_file(brief)} (запасной путь)")
    else:
        path = deliver_file(brief)
        first = brief.splitlines()[0] if brief else ""
        notify("Утренний брифинг", f"Готов: {path.name}. {first}")
        print(f"  FILE: OK {path}")
    print(f"---\n{brief}")


if __name__ == "__main__":
    main()
```

Где брифинг без бота: файл `memory/brief_<дата>.md` в папке памяти (его видно в VS Code и в Obsidian, его
подхватывает автобэкап) и уведомление на экране. Утром можно сказать Claude «покажи сегодняшний брифинг».

---

### Шаг 4. Пропиши расписание — Mac (`os_branch` = `mac`): launchd

Брифинг в 08:00 по часам компьютера. Если в 08:00 Mac спал, launchd выполнит запуск при пробуждении.
Пути в plist — только абсолютные, без `~`. `PATH` в plist нужен запасному пути `claude -p`: фоновая задача
не видит папок, где установлены `claude` и `node`.

```bash
PY_ABS=$(command -v python3)
CL_DIR=$(dirname "$(command -v claude 2>/dev/null || echo /usr/local/bin/claude)")
NODE_DIR=$(dirname "$(command -v node 2>/dev/null || echo /usr/local/bin/node)")
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.ikigai.morning-brief.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ikigai.morning-brief</string>
  <key>ProgramArguments</key>
  <array><string>${PY_ABS}</string><string>${HOME}/morning_brief.py</string></array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>${CL_DIR}:${NODE_DIR}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>${HOME}/morning_brief.log</string>
  <key>StandardErrorPath</key><string>${HOME}/morning_brief.log</string>
</dict>
</plist>
EOF
plutil -lint ~/Library/LaunchAgents/com.ikigai.morning-brief.plist
launchctl bootout gui/$(id -u)/com.ikigai.morning-brief 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ikigai.morning-brief.plist
launchctl kickstart gui/$(id -u)/com.ikigai.morning-brief      # пробный запуск сейчас
```

**Признак:** через минуту пришёл брифинг (в Telegram или уведомлением + файлом), а `tail -5 ~/morning_brief.log`
содержит `TG: OK` или `FILE: OK`.
В логе `Operation not permitted` — память лежит в «Документах» или на «Рабочем столе», и macOS не пускает
туда фоновую задачу: Системные настройки → Конфиденциальность и безопасность → Полный доступ к диску →
добавить тот `python3`, путь к которому стоит в plist, и снова `launchctl kickstart …`.

🧪 **Вход по подписке на Mac — проверить на живом Mac.** Токен Claude Code на Mac лежит не в файле, а в
Связке ключей (запись `Claude Code-credentials`, внутри — JSON с `claudeAiOauth.accessToken`). При первом
фоновом запуске macOS может спросить «python3 хочет использовать связку ключей» — попроси человека нажать
**«Разрешить всегда»**. В логе `Claude via oauth (Связка ключей): OK` — путь работает. Нет — скрипт сам
перейдёт на `claude -p` (`Claude via claude -p: OK`); не сработало и это — `ANTHROPIC_API_KEY` в окружении
задачи как крайний платный вариант, только с согласия человека.

**Перенос со старого cron.** Только после того, как брифинг от launchd пришёл, убери строку брифинга из cron —
иначе брифинг будет приходить дважды. crontab правится ТОЛЬКО через файл со сверкой числа строк:
одна ошибка в команде обнуляет все задачи пользователя.

```bash
crontab -l > /tmp/cron_before_$$.txt 2>/dev/null || : ; BEFORE=$(wc -l < /tmp/cron_before_$$.txt)
grep -v "morning_brief" /tmp/cron_before_$$.txt > /tmp/cron_new_$$.txt
AFTER=$(wc -l < /tmp/cron_new_$$.txt)
[ "$AFTER" -eq $((BEFORE - 1)) ] && crontab /tmp/cron_new_$$.txt && echo "cron: строка брифинга убрана" \
  || echo "СТОП: ожидалась ровно одна строка брифинга, найдено $((BEFORE - AFTER)). Покажи человеку и спроси"
crontab -l | grep morning_brief || echo "в cron брифинга больше нет"
```

### Шаг 4L. Сервер Linux (`os_branch` = `linux`): cron

Если на этом сервере стоит связка `brain-link` с ботом — брифинг уже идёт таймером `brain-brief.timer`,
cron **не ставь** (иначе придёт два). Этот раздел — для сервера без `brain-link`.

Сервер не спит, поэтому cron здесь годится. Сервер обычно живёт в UTC: час запуска = (8 − TZ_OFFSET) mod 24.
На сервере нет экрана для уведомлений — без бота брифинг пишется только файлом в память.

```bash
PYTHON_BIN=$(which python3)
CRON_HOUR=ВЫЧИСЛИ  # (8 - TZ_OFFSET) % 24: МСК +3 → 5, Европа +2 → 6, UTC → 8

crontab -l > /tmp/cron_before_$$.txt 2>/dev/null || : ; BEFORE=$(wc -l < /tmp/cron_before_$$.txt)
grep -q "morning_brief" /tmp/cron_before_$$.txt && echo "УЖЕ СТОИТ — второй раз не добавляем, иначе брифинг придёт дважды" || {
  cp /tmp/cron_before_$$.txt /tmp/cron_new_$$.txt
  echo "0 ${CRON_HOUR} * * * ${PYTHON_BIN} \$HOME/morning_brief.py >> \$HOME/morning_brief.log 2>&1  # Утренний брифинг 08:00" >> /tmp/cron_new_$$.txt
  [ "$(wc -l < /tmp/cron_new_$$.txt)" -gt "$BEFORE" ] && crontab /tmp/cron_new_$$.txt || echo "СТОП: новый файл не больше старого, не ставим"
}
crontab -l | wc -l   # должно быть на 1 больше, чем BEFORE
```

### Шаг 4W. Пропиши расписание — Windows (`os_branch` = `windows`)

Расписание живёт в Планировщике заданий: задача `Ikigai morning-brief`, ежедневно в 08:00 по часам компьютера,
с флагом **StartWhenAvailable** — «запускать при первой возможности после пропуска». Без него спящий
в 08:00 ноутбук задачу просто пропустит. Командой `schtasks` этот флаг не ставится, поэтому — PowerShell.

🔴 Три вещи, на которых этот шаг ломается, если сделать наивно:
- **Путь бери из поля `home_win` профиля** (`C:\Users\Иван`), а не из `home` (`/c/Users/Иван`) — второй формат
  понимает только Git Bash. В файле ниже путь берётся из `$env:USERPROFILE`, это то же самое.
- **Из Git Bash не вызывай `schtasks` и сложный PowerShell одной строкой:** Git Bash переписывает аргументы
  со слешем и кавычки. Запиши команды в файл `.ps1` и запусти файл.
- **Файл `.ps1` — в UTF-8 с BOM.** Windows PowerShell 5.1 читает `.ps1` без BOM в кодировке ANSI, и путь
  с кириллицей (`C:\Users\Иван`) ломается. Инструмент записи файлов пишет без BOM — после записи пересохрани.

Создай файл `~/install_morning_brief.ps1`:

```powershell
$py = (Get-Command py -ErrorAction SilentlyContinue).Source
if ($py) { $arg = "-3 `"$env:USERPROFILE\morning_brief.py`"" } else { $py = (Get-Command python).Source; $arg = "`"$env:USERPROFILE\morning_brief.py`"" }
$action   = New-ScheduledTaskAction -Execute $py -Argument $arg -WorkingDirectory $env:USERPROFILE
$trigger  = New-ScheduledTaskTrigger -Daily -At 08:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "Ikigai morning-brief" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "Ikigai morning-brief"
(Get-ScheduledTask -TaskName "Ikigai morning-brief").Settings.StartWhenAvailable
```

Пересохрани с BOM и запусти:

```bash
powershell -NoProfile -Command '$p = "$env:USERPROFILE\install_morning_brief.ps1"; $t = [IO.File]::ReadAllText($p); [IO.File]::WriteAllText($p, $t, (New-Object Text.UTF8Encoding $true))'
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME/install_morning_brief.ps1"
```

**Признак:** последняя строка вывода — `True`, и через минуту пришёл брифинг (Telegram или уведомление у часов
+ файл `memory\brief_<дата>.md`).

Была старая задача `IkigaiMorningBrief` (ставилась прошлой версией этого файла) — после того как новая
доставила брифинг, удали старую, иначе брифинг придёт дважды:

```bash
powershell -NoProfile -Command 'Unregister-ScheduledTask -TaskName "IkigaiMorningBrief" -Confirm:$false'
```

---

### Шаг 5. Тест и отчёт

```bash
python3 ~/morning_brief.py      # Windows: py -3 ~/morning_brief.py
```

Убедись, что вывод содержит `TG: OK` (с ботом) или `FILE: OK <путь>` (без бота), и брифинг дошёл:
сообщение в Telegram или уведомление на экране и файл `memory/brief_<дата>.md`.

Где стоит расписание:

```bash
launchctl print gui/$(id -u)/com.ikigai.morning-brief | grep -E "state|last exit"     # Mac
powershell -NoProfile -Command 'Get-ScheduledTask -TaskName "Ikigai morning-brief" | Select-Object TaskName, State'   # Windows
crontab -l | grep morning_brief                                                       # сервер Linux
```

```bash
tail -5 ~/morning_brief.log 2>/dev/null
```

Признак готовности — не строка в списке задач, а **пришедший брифинг**: сообщение в Telegram или файл
сегодняшней датой с уведомлением.

**Проверка нового блока обещаний.** Если в `memory/commitments.md` есть строка со статусом `open` и датой
«проверить» сегодня или раньше — в брифинге должен быть блок «🪞 Обещал — не закрыто». Нет такой строки —
блок молча пропускается, это норма. В пятницу последняя строка брифинга — напоминание про `/weekly-distill`.

После успешного теста напиши пользователю итоговый отчёт в формате:

```
✅ Утренний брифинг настроен

Расписание: [launchd / Планировщик заданий / cron на сервере], 08:00 по твоему времени,
            пропущенный из-за сна запуск выполнится при пробуждении
Читает из: [MEMORY_PATH]
Доставка: [Telegram через [bot username] → tg uid [OWNER_ID] / файл memory/brief_<дата>.md + уведомление]
Вход в Claude: [подписка — файл / Связка ключей / claude -p / API-ключ]
Секреты: ~/.config/morning-brief/env (не в коде)

Пример брифинга:
[первые 3 строки сгенерированного текста]
```

---

## Если что-то пошло не так

| Симптом | Решение |
|---|---|
| `TG: FAIL` | Проверь `BOT_TOKEN` и `OWNER_ID` в `~/.config/morning-brief/env` (не в коде). Брифинг в этот день всё равно лёг файлом в `memory/` |
| `Claude HTTP 401` | Токен подписки протух — скрипт сам попробует `claude -p`. Не сработало и это: выполни `claude` один раз в терминале (обновит вход) или `claude setup-token`. Платный `ANTHROPIC_API_KEY` — только крайний запасной вариант |
| `claude -p err: … No such file` | В `env` неверный `CLAUDE_BIN`, или (Mac) в plist нет `PATH` к `claude` / `node` — Шаг 4 |
| Mac: в логе ничего про Связку ключей, окно «разрешить» не появлялось | 🧪 путь не проверен на живом Mac. Скрипт уйдёт на `claude -p` — это нормально |
| `Второй мозг пуст` | Проверь, что `MEMORY_BASE` = `<workspace>/memory` из профиля, а не копия в `~/.claude/` |
| Mac: брифинг не пришёл утром | `launchctl print gui/$(id -u)/com.ikigai.morning-brief` — задача загружена? В `~/morning_brief.log` нет `Operation not permitted`? (см. Шаг 4) |
| Windows: брифинг не пришёл утром | В свойствах задачи «Ikigai morning-brief» → «Параметры» стоит «Немедленно запускать задачу, если плановый запуск пропущен»? |
| Windows: путь с кракозябрами в задаче | `install_morning_brief.ps1` сохранён без BOM — пересохрани (Шаг 4W) и запусти снова |
| Брифинг приходит дважды | Осталось старое расписание: строка в cron (Mac) или задача `IkigaiMorningBrief` (Windows) — убери по Шагу 4 / 4W. Стоит бот `brain-link` — брифинг должен идти только с сервера: выключи локальный по Шагу 0.5 |
| cron на сервере не запускается | Добавь полный путь к python3: `which python3` |
| Нет блока «🪞 Обещал — не закрыто» | Нет `memory/commitments.md` или нет `open`-строк с прошедшей датой «проверить» — это норма |
