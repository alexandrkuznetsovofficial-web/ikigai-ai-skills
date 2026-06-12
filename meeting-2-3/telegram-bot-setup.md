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

### Шаг 2. Получить API-ключ Anthropic (Claude)

Если у тебя уже есть API-ключ — пропусти этот шаг.

1. Открой **console.anthropic.com** (нужен VPN если ты в РФ)
2. Зарегистрируйся или войди (можно через Google)
3. Слева в меню → **"API Keys"**
4. Нажми **"Create Key"** → дай имя, например `telegram-bot`
5. Скопируй ключ — он начинается с `sk-ant-...`

> ⚠️ Ключ показывается только один раз при создании. Сохрани сразу.

#### Пополнить баланс токенов

1. В console.anthropic.com → слева **"Billing"**
2. **"Add credit"** → введи карту → пополни на нужную сумму
3. Минимум — $5. На первое время хватит надолго (простой бот тратит ~$0.01-0.05 в день)
4. Рекомендую включить **"Auto-recharge"** — автопополнение когда баланс падает ниже $2
5. В разделе **"Usage"** всегда видно сколько потратил и на что

> **Сколько стоит?** Claude Haiku (быстрый и дешёвый) — $0.25 за миллион токенов. 1 сообщение ≈ 500 токенов = $0.000125. При 100 сообщениях в день = ~$0.01/день.

---

### Шаг 3. Создать файл .env с ключами

Когда Claude создаст папку проекта, тебе нужно заполнить файл `.env`:

```
BOT_TOKEN=вставь_токен_от_BotFather
ANTHROPIC_API_KEY=вставь_ключ_от_Anthropic
BOT_NAME=Имя как ты называешь своего бота (например Вася)
OWNER_TELEGRAM_ID=твой_telegram_id
```

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
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
BOT_NAME = os.environ.get("BOT_NAME", "Ассистент")
OWNER_ID_STR = os.environ.get("OWNER_TELEGRAM_ID", "")

# Проверка что ключи заполнены
if BOT_TOKEN == "вставь_токен_от_BotFather":
    print("❌ Заполни BOT_TOKEN в файле .env")
    exit(1)
if ANTHROPIC_API_KEY.startswith("вставь"):
    print("❌ Заполни ANTHROPIC_API_KEY в файле .env")
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
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

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
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",   # быстрый и дешёвый
            max_tokens=1024,
            system=system_prompt,
            messages=dialog_history,
        )
        assistant_reply = response.content[0].text
        dialog_history.append({"role": "assistant", "content": assistant_reply})
        return assistant_reply
    except anthropic.APIError as e:
        log.error(f"Claude API error: {e}")
        return f"⚠️ Ошибка Claude API: {e}"


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
    bot.reply_to(message,
        f"✅ Бот работает\n"
        f"Модель: claude-haiku-4-5\n"
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
ANTHROPIC_API_KEY=sk-ant-...
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

| Модель | Когда использовать | Цена |
|--------|-------------------|------|
| `claude-haiku-4-5-20251001` | Быстро, дёшево, повседневные задачи | ~$0.01/день |
| `claude-sonnet-4-6` | Сложные задачи, анализ | ~$0.05/день |
| `claude-fable-5` | Максимум мощи (бесплатно до 22.06!) | после 22.06 — дорого |

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
| `insufficient_quota` | Закончились токены Anthropic | Пополни баланс на console.anthropic.com → Billing |
| `ModuleNotFoundError: telebot` | Не установлены зависимости | `pip install -r requirements.txt` |
| На Windows `py` не работает | Python не в PATH | При установке Python отметь "Add to PATH" |

---

## Безопасность — важно

- `.env` — никогда не выкладывай в GitHub. Ключ = деньги с твоего счёта.
- Строка `OWNER_TELEGRAM_ID` ограничивает бота только тобой — без неё любой может писать боту
- Если случайно запушил ключ в GitHub — немедленно удали его в console.anthropic.com и создай новый

---

*Создано для AI-Поток 2 · Икигай · Встреча 3 · 13.06.2026*
*Вопросы → @alexandr_ic*
