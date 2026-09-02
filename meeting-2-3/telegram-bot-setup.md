# Telegram-бот с Claude: от нуля до рабочего бота

> Загрузи этот файл в VS Code → напиши **"Установи мне Telegram-бота по этому гайду"** → Claude создаст все файлы и установит зависимости автоматически. Ключи вставишь сам — они нигде не хранятся кроме твоего компьютера.

---

## Что получишь в итоге

Личный Telegram-бот, который:
- Отвечает на твои сообщения через Claude (знает твой Second Brain)
- Принимает фото, документы, голосовые — анализирует их
- Работает прямо на твоём компьютере (пока он включён)
- Потом переедет на сервер — тогда будет работать 24/7

---

## ЧАСТЬ 1. Делаешь ты (10 минут)

### Шаг 1. Создать бота в Telegram — BotFather

1. Открой Telegram на телефоне или компьютере
2. Найди бота **@BotFather** (официальный, синяя галочка)
3. Напиши `/newbot`
4. BotFather спросит **имя бота** — это публичное имя, как отображается в TG. Например: `Мой AI-ассистент`
5. Потом спросит **username** — это техническое имя, обязательно заканчивается на `bot`. Например: `myvanya_ai_bot`
6. Получишь сообщение с **токеном** — длинная строка вида:
   ```
   7123456789:AAFxyz-abcdefGHIJKLMNOPQRSTUVWXYZ
   ```
7. **Скопируй этот токен** — он тебе понадобится в шаге 3

> ⚠️ Токен = пароль от бота. Никому не давай, не публикуй в GitHub.

---

### Шаг 2. Получить токен подписки Claude (НЕ нужны ни карта, ни новый кошелёк)

У тебя уже есть подписка Claude (Pro/Max) — на ней работает весь курс. Бот будет тратить токены **из этой же подписки**, без отдельного API-ключа, без console.anthropic.com, без пополнения баланса.

Как это происходит (2 минуты, команду выполняет Claude — не ты):

1. Скажи Claude в VS Code: **«Выпусти мне токен подписки для бота»** — он сам выполнит команду `claude setup-token`
2. Откроется браузер → войди под своей подпиской Claude → нажми **Authorize**
3. Появится строка вида `sk-ant-oat01-...` — скопируй её и пришли Claude, он сам положит её в `.env`

Если хочешь вручную: открой терминал (Mac: Cmd+Space → набери «Терминал»; Windows: Пуск → набери «PowerShell») и выполни `claude setup-token` — дальше те же шаги 2–3.

> ⚠️ Токен = доступ к твоей подписке. Как и токен бота — никому не давай, не публикуй в GitHub.

**Два честных момента про подписку:**
- Бот ест общий лимит твоей подписки вместе с твоей работой в Claude Code. Для личного бота на Haiku это незаметно.
- Подписка — для личного использования. Гонять через неё продукт на чужих людей нельзя (для этого — платный API).

<details>
<summary>Запасной путь: если подписки нет (не рекомендуем — это платно за каждый вызов)</summary>

Можно работать через платный API-ключ: console.anthropic.com (нужен VPN в РФ) → API Keys → Create Key → Billing → пополнить от $5 (карты РФ не работают — «Плати по миру» @platipomiru_bot или зарубежная карта). Ключ кладётся в `.env` как `ANTHROPIC_API_KEY`. Но если подписка есть — этот путь не нужен, он только добавляет второй кошелёк и лишнюю головную боль.
</details>

---

### Шаг 3. Создать файл .env с ключами

Когда Claude создаст папку проекта, тебе нужно заполнить файл `.env`:

```
BOT_TOKEN=вставь_токен_от_BotFather
CLAUDE_CODE_OAUTH_TOKEN=вставь_токен_подписки_из_шага_2
BOT_NAME=Имя как ты называешь своего бота (например Вася)
OWNER_TELEGRAM_ID=твой_telegram_id
```

> Если идёшь запасным путём через платный API — вместо `CLAUDE_CODE_OAUTH_TOKEN` заполни `ANTHROPIC_API_KEY`. Бот сам поймёт, что доступно. Оба сразу заполнять не нужно.

**Как узнать свой Telegram ID:**
- Напиши боту **@userinfobot** в Telegram
- Он ответит твой числовой ID, например `123456789`

---

## ЧАСТЬ 2. Делает Claude (автоматически)

> Когда скажешь "Установи мне Telegram-бота по этому гайду" — Claude выполнит всё ниже сам.

### Структура которую создаст Claude

```
~/telegram_bot/
├── .env                    ← твои ключи (НИКОГДА не в GitHub)
├── .env.example            ← шаблон без ключей (можно в GitHub)
├── .gitignore              ← защита от случайного коммита ключей
├── requirements.txt        ← зависимости
├── bot.py                  ← главный файл бота
├── memory/                 ← папка для памяти бота
│   └── profile.md          ← контекст о тебе (заполнишь сам)
└── logs/                   ← логи сообщений
```

### Файл requirements.txt

```
pyTelegramBotAPI==4.22.1
anthropic>=0.40.0
python-dotenv>=1.0.0
```

### Файл bot.py

```python
#!/usr/bin/env python3
"""
Telegram-бот с Claude — AI-ассистент для бизнеса.
Запуск: python bot.py (Mac/Linux) или py bot.py (Windows)
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv
import telebot
import anthropic

# Загружаем ключи из .env
load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
OAUTH_TOKEN = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()   # токен подписки (основной путь)
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()             # платный API (запасной путь)
BOT_NAME = os.environ.get("BOT_NAME", "Ассистент")
OWNER_ID_STR = os.environ.get("OWNER_TELEGRAM_ID", "")

# Проверка что ключи заполнены
if BOT_TOKEN == "вставь_токен_от_BotFather":
    print("❌ Заполни BOT_TOKEN в файле .env")
    exit(1)
if OAUTH_TOKEN.startswith("вставь"):
    OAUTH_TOKEN = ""
if not OAUTH_TOKEN and not API_KEY:
    print("❌ Заполни CLAUDE_CODE_OAUTH_TOKEN в файле .env (см. Шаг 2 гайда)")
    exit(1)

# Настройка
OWNER_ID = int(OWNER_ID_STR) if OWNER_ID_STR.strip().isdigit() else None
BOT_DIR = Path(__file__).parent
MEMORY_FILE = BOT_DIR / "memory" / "profile.md"
BOT_DIR.joinpath("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(BOT_DIR / "logs" / "bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)

# Клиент Claude: основной путь — подписка (OAuth-токен), запасной — платный API-ключ.
# ⚠️ Грабли: если в окружении есть И ANTHROPIC_API_KEY, И OAuth-токен — SDK шлёт оба,
# и запрос отклоняется («credit balance too low»). Поэтому на время создания
# подписочного клиента API-ключ временно убираем из окружения.
claude_sub = None
if OAUTH_TOKEN:
    _saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    claude_sub = anthropic.Anthropic(
        auth_token=OAUTH_TOKEN,
        default_headers={"anthropic-beta": "oauth-2025-04-20"},
    )
    if _saved:
        os.environ["ANTHROPIC_API_KEY"] = _saved

claude_api = anthropic.Anthropic(api_key=API_KEY) if API_KEY else None


def llm_call(**kwargs):
    """Вызов Claude: сначала подписка, при ошибке — платный API (если настроен)."""
    if claude_sub is not None:
        try:
            resp = claude_sub.messages.create(**kwargs)
            log.info("[AUTH] subscription")
            return resp
        except anthropic.APIError as e:
            log.warning(f"[AUTH] подписка не ответила ({e}), пробую API-ключ")
            if claude_api is None:
                raise
    if claude_api is None:
        raise RuntimeError("Нет ни рабочего токена подписки, ни API-ключа")
    resp = claude_api.messages.create(**kwargs)
    log.info("[AUTH] api-key (платный)")
    return resp

# История диалога (в памяти — сбрасывается при рестарте)
dialog_history: list[dict] = []
MAX_HISTORY = 20  # сколько сообщений помним


def load_profile() -> str:
    """Загружает контекст о владельце из memory/profile.md"""
    if MEMORY_FILE.exists():
        return MEMORY_FILE.read_text(encoding="utf-8")
    return ""


def ask_claude(user_message: str) -> str:
    """Отправляет сообщение в Claude и возвращает ответ."""
    global dialog_history

    profile = load_profile()
    system_prompt = f"""Ты личный AI-ассистент. Тебя зовут {BOT_NAME}.
Ты работаешь в Telegram и помогаешь владельцу с задачами бизнеса.
Отвечай кратко и по делу. Если нужно — задавай уточняющие вопросы.
Используй Markdown для форматирования когда это улучшает читаемость.

{"# Контекст о владельце:" + chr(10) + profile if profile else ""}
"""

    # Добавляем сообщение пользователя в историю
    dialog_history.append({"role": "user", "content": user_message})

    # Ограничиваем историю
    if len(dialog_history) > MAX_HISTORY * 2:
        dialog_history = dialog_history[-MAX_HISTORY * 2:]

    try:
        response = llm_call(
            model="claude-haiku-4-5-20251001",   # быстрый; через подписку работает стабильнее всего
            max_tokens=1024,
            system=system_prompt,
            messages=dialog_history,
        )
        assistant_reply = response.content[0].text
        dialog_history.append({"role": "assistant", "content": assistant_reply})
        return assistant_reply
    except Exception as e:
        log.error(f"Claude error: {e}")
        return (f"⚠️ Ошибка Claude: {e}\n\n"
                "Если это 401 — токен подписки протух: попроси Claude в VS Code "
                "выполнить `claude setup-token` заново и обновить .env")


def is_owner(user_id: int) -> bool:
    """Проверяет что сообщение от владельца. Если OWNER_ID не задан — разрешает всем."""
    if OWNER_ID is None:
        return True
    return user_id == OWNER_ID


# ============ HANDLERS ============

@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    if not is_owner(message.from_user.id):
        return  # молча игнорируем чужих
    bot.reply_to(message,
        f"Привет! Я {BOT_NAME}, твой AI-ассистент.\n\n"
        "Пиши мне что угодно — я отвечу через Claude.\n\n"
        "Команды:\n"
        "/clear — сбросить историю диалога\n"
        "/status — проверить что всё работает"
    )


@bot.message_handler(commands=["clear"])
def cmd_clear(message):
    if not is_owner(message.from_user.id):
        return
    global dialog_history
    dialog_history = []
    bot.reply_to(message, "✅ История сброшена. Начинаем с чистого листа.")


@bot.message_handler(commands=["status"])
def cmd_status(message):
    if not is_owner(message.from_user.id):
        return
    profile_status = "✅ загружен" if MEMORY_FILE.exists() else "⚠️ не найден (создай memory/profile.md)"
    auth_status = "подписка Claude" if claude_sub else "платный API-ключ"
    bot.reply_to(message,
        f"✅ Бот работает\n"
        f"Модель: claude-haiku-4-5\n"
        f"Доступ: {auth_status}\n"
        f"История: {len(dialog_history) // 2} сообщений\n"
        f"Профиль: {profile_status}"
    )


@bot.message_handler(content_types=["text"])
def handle_text(message):
    if not is_owner(message.from_user.id):
        return  # молча игнорируем чужих

    user_text = message.text.strip()
    log.info(f"[{message.from_user.username}] {user_text[:80]}")

    # Показываем что обрабатываем
    bot.send_chat_action(message.chat.id, "typing")

    reply = ask_claude(user_text)
    bot.reply_to(message, reply, parse_mode="Markdown")


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    if not is_owner(message.from_user.id):
        return
    caption = message.caption or "Что на этом фото? Опиши подробно."
    bot.send_chat_action(message.chat.id, "typing")
    reply = ask_claude(f"[Пользователь прислал фото с подписью: {caption}]")
    bot.reply_to(message, reply, parse_mode="Markdown")


@bot.message_handler(content_types=["document"])
def handle_document(message):
    if not is_owner(message.from_user.id):
        return
    filename = message.document.file_name or "файл"
    caption = message.caption or ""
    bot.send_chat_action(message.chat.id, "typing")
    reply = ask_claude(f"[Пользователь прислал документ: {filename}. {caption}]")
    bot.reply_to(message, reply, parse_mode="Markdown")


# ============ ЗАПУСК ============

if __name__ == "__main__":
    log.info(f"🤖 Бот {BOT_NAME} запущен. Жди сообщений...")
    print(f"✅ Бот запущен! Напиши ему в Telegram.")
    print(f"   Остановить: Ctrl+C")
    try:
        bot.infinity_polling(timeout=30, long_polling_timeout=30)
    except KeyboardInterrupt:
        log.info("Бот остановлен вручную.")
        print("\n👋 Бот остановлен.")
```

### Файл .env.example (безопасный шаблон для GitHub)

```
BOT_TOKEN=вставь_токен_от_BotFather
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
# ANTHROPIC_API_KEY=  ← только для запасного платного пути, обычно НЕ нужен
BOT_NAME=Вася
OWNER_TELEGRAM_ID=123456789
```

### Файл .gitignore

```
.env
*.session
logs/
__pycache__/
*.pyc
.DS_Store
```

### Файл memory/profile.md

```markdown
# Мой профиль

## Кто я
[Напиши о себе: имя, чем занимаешься, какой бизнес]

## Мои цели прямо сейчас
[Что сейчас важно решить]

## Как я работаю
[Твой стиль, предпочтения, как общаться с тобой]

## Ключевые люди в моей жизни
[Кто есть кто — чтобы бот понимал когда ты упоминаешь имена]

## Мои проекты
[Что сейчас в работе]
```

---

## ЧАСТЬ 3. Установка зависимостей и запуск

> Claude делает это через терминал автоматически. Но если нужно вручную:

### Mac / Linux

```bash
# Перейди в папку проекта
cd ~/telegram_bot

# Установи зависимости
pip3 install -r requirements.txt

# Запусти бота
python3 bot.py
```

### Windows

```powershell
# Перейди в папку проекта
cd C:\Users\ТвоёИмя\telegram_bot

# Установи зависимости
pip install -r requirements.txt

# Запусти бота
py bot.py
```

> **Если pip не найден на Windows:** открой PowerShell от администратора, выполни:
> `python -m ensurepip --upgrade`

> **Если python не найден:** скачай Python с python.org → при установке обязательно отметь **"Add Python to PATH"**

---

## Как понять что бот работает

1. После запуска увидишь: `✅ Бот запущен! Напиши ему в Telegram.`
2. Открой Telegram → найди своего бота по username → напиши `/start`
3. Бот должен ответить приветствием

---

## Персонализация под свои задачи

После базовой установки попроси Claude (в VS Code):

**Бот-дневник** (пример Ольги):
> "Добавь в бота команду /diary — он спрашивает как прошёл день и записывает ответ в файл diary.md с датой"

**Бот-учёт задач** (пример Тимура):
> "Добавь команду /task — принимает описание задачи и добавляет в tasks.md с временной меткой"

**Бот для анализа переписок**:
> "Добавь обработку пересланных сообщений — принимает форвард и анализирует о чём просят"

**Бот с голосовыми** (продвинутый уровень):
> "Добавь обработку voice-сообщений через faster-whisper — транскрибирует и отвечает"

---

## Переключить модель Claude

В `bot.py` строка модели — меняй под задачу:

| Модель | Когда использовать | На подписке |
|--------|-------------------|-------------|
| `claude-haiku-4-5-20251001` | Быстро, повседневные задачи — **дефолт для бота** | ✅ работает стабильно |
| `claude-sonnet-4-6` | Сложные задачи, анализ | ⚠️ может отдавать 429 (лимит) — бот уйдёт на fallback |
| `claude-fable-5` | Максимум мощи | ⚠️ то же самое; для бота избыточно |

> Через подписку надёжнее всего работает Haiku — для личного ассистента его более чем достаточно. Дорогие модели оставь для работы в Claude Code.

---

## ⚠️ Гигиена системного промпта — читать до того, как бот «потолстеет»

> 🔴 **Дополнено в сентябре 2026.** Совета «меняющееся — вниз» оказалось **недостаточно**:
> если `system` уходит одним блоком, кэш ломается независимо от порядка строк. Рабочее решение —
> разрез на два блока — и способ это замерить лежат в [`upgrade-2026-09.md`](upgrade-2026-09.md).
> Раздел ниже оставлен как объяснение механики, он верный; неполон только вывод.


Пока бот новый, системный промпт — три строчки, и всё летает. Проблемы начинаются через месяц-другой, когда ты навесил на него память, список навыков, текущее время, календарь. Тогда бот начинает упираться в лимит (`429`) на ровном месте и отвечать медленнее — а причина не в том, что «много данных», а в **порядке блоков**.

**Что происходит.** Всё, что уходит в модель повторно и без изменений, кэшируется — второй раз за это платится сильно дешевле. Но кэш работает только «сверху вниз, до первого расхождения». Стоит поставить **в начало промпта что-то, что меняется каждую минуту** — текущее время, сегодняшний календарь, «сейчас 14:37» — и всё, что стоит ниже, кэшу уже недоступно: промпт каждый раз считается новым. Ваша память и ваши инструкции пересчитываются **на каждом сообщении**, по полной цене.

Внешне это никак не проявляется. Бот работает, отвечает — просто дороже и ближе к лимиту, чем должен. Обнаруживается обычно поздно: люди упираются в `429` и начинают **урезать память**, лечат симптом, а причина — одна строка не на своём месте.

**Три правила, чтобы этого не случилось:**

1. **Всё меняющееся — вниз.** Время, дата, «что сегодня в календаре» и любые свежие данные ставь **в конец промпта или прямо в сообщение пользователя**, а не в начало. Наверху — только стабильное: кто ты, как отвечаешь, память.
2. **Справочники не кладут в промпт — их дают инструментом.** Каталог навыков, список файлов, длинный справочник — это склад. В промпте он лежит мёртвым грузом и съедает место, а нужен раз в неделю. Правильно: бот **запрашивает** нужное, когда понадобилось.
3. **В память едет верхний слой, а не первые N символов.** Когда файл памяти перестанет влезать, соблазн — «обрезать до 8 000 символов». Это режет по **позиции в файле**, а не по нужности: половина важного просто не доедет. Правильно — расслоить: краткий индекс/актуальное едет всегда, детали и архив лежат рядом и достаются по запросу.

> **Промпт для VS Code (проверка своего бота):**
> «Покажи, как у моего бота собирается системный промпт: перечисли блоки по порядку и размер каждого в символах. Отдельно ответь: (1) есть ли в промпте что-то, что меняется каждую минуту — время, дата, календарь — и на каком оно месте; (2) сколько занимают справочники и списки, которые реально нужны редко; (3) какая доля промпта уходит на память. Если меняющееся стоит выше памяти — перенеси его вниз, покажи порядок до и после. Ничего другого не меняй.»

✅ **Получилось, если…** в начале промпта не осталось ничего, что меняется чаще, чем раз в сессию, а часы и календарь переехали вниз.

---

## Что будет дальше (следующие встречи)

### Блок 4 (30.06) — Перенос бота на сервер

Когда бот работает локально — он живёт пока открыт ноутбук. Для постоянной работы:
- Арендуем VPS (от 300 руб/мес — Timeweb, FirstVDS, или подобные)
- Загружаем бота туда
- Настраиваем автозапуск через systemd (Linux) или PM2 (Node-style)
- Бот работает 24/7 без участия твоего компьютера

### После переноса — подключение к Second Brain

- Бот читает твою память (memory/), как это сделано у Александра
- RAG по файлам — бот знает твои заметки, встречи, задачи
- Голосовые → транскрипция → сохранение в память

---

## Частые ошибки

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `KeyError: 'BOT_TOKEN'` | .env не создан или не заполнен | Проверь файл .env |
| `Unauthorized` | Токен бота неверный | Создай нового бота в BotFather |
| `Connection timeout` | Нет VPN / интернета | Включи VPN |
| `401 authentication_error` | Токен подписки протух | Попроси Claude выполнить `claude setup-token` заново и обновить .env |
| `credit balance too low` (при рабочей подписке) | В окружении одновременно и API-ключ, и токен подписки — SDK шлёт оба | Убери `ANTHROPIC_API_KEY` из .env, оставь только `CLAUDE_CODE_OAUTH_TOKEN` |
| `429 rate_limit` | Упёрся в лимит подписки (или модель дороже Haiku) | Подожди; проверь что в bot.py стоит Haiku |
| `429` стал прилетать регулярно, хотя раньше не было | В системный промпт добавили что-то меняющееся (время, календарь) — и промпт перестал кэшироваться целиком | См. раздел «Гигиена системного промпта»: меняющееся — вниз. **Не начинай с урезания памяти** — это лечение симптома |
| Бот отвечает «не могу, у меня нет доступа», хотя доступ есть | В системном промпте написано, чего он «не умеет», и это перевешивает реальный список инструментов | Убери из промпта самооговоры («ты не можешь…», «у тебя нет инструментов») и впиши явный список того, что у него ЕСТЬ |
| `ModuleNotFoundError: telebot` | Не установлены зависимости | `pip install -r requirements.txt` |
| На Windows `py` не работает | Python не в PATH | При установке Python отметь "Add to PATH" |

---

## Безопасность — важно

- `.env` — никогда не выкладывай в GitHub. Токен подписки = доступ к твоему аккаунту Claude, токен бота = управление ботом.
- Строка `OWNER_TELEGRAM_ID` ограничивает бота только тобой — без неё любой может писать боту и тратить твой лимит
- Если случайно запушил токен в GitHub — немедленно перевыпусти: токен подписки → `claude setup-token` заново (старый отзови в claude.ai → Settings), токен бота → /revoke в BotFather

---

*Создано для AI-Поток 2 · Икигай · Встреча 3 · 13.06.2026*
*Вопросы → @alexandr_ic*
