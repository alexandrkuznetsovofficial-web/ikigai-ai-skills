# 🛡 Авто-коммиты: страховка твоего второго мозга

> **Файл-установщик для Claude. Участник ничего не делает руками — просто загрузи этот файл в чат VS Code и напиши: «Настрой мне авто-коммиты по этому гайду».**

---

## Зачем это нужно (прочитай, это важно)

Сейчас у тебя **одна копия** твоего второго мозга — на одном ноутбуке, без истории версий. Это значит:

- Claude в эксперименте перезапишет файл — старая версия исчезнет навсегда
- Сломается / потеряется ноутбук — пропадёт всё: интервью о себе, контекст бизнеса, память, скиллы, бот
- Страшно экспериментировать, потому что «сломаю и не починю»

Этот скилл решает всё одной установкой: **каждые 30 минут компьютер сам делает снимок (commit) всех твоих рабочих папок**. Так работает система Александра — теперь будет и у тебя. Любую поломку можно откатить одной фразой: *«Откати последний коммит, верни рабочую версию»*.

---

## ИНСТРУКЦИЯ ДЛЯ CLAUDE

Ты — установщик системы автоматических коммитов. Выполни шаги по порядку. Работай сам, у пользователя спрашивай только то, что указано. Пользователь не использует терминал — все команды выполняешь ты.

### Шаг 0. Определи окружение

1. Определи ОС: macOS или Windows.
2. Проверь установлен ли git (`git --version`).
   - macOS: если нет — `xcode-select --install` (предупреди пользователя, что выскочит окно установки, надо нажать «Установить»).
   - Windows: если нет — установи через `winget install --id Git.Git -e --source winget`, затем перезапусти терминальную сессию.
3. Если git свежеустановлен — настрой имя:
   ```
   git config --global user.name "<имя пользователя>"
   git config --global user.email "<его email или username@local>"
   ```
   Имя возьми из контекста (CLAUDE.md, memory) или спроси.

### Шаг 1. Определи, какие папки бэкапим

1. Первая папка — **текущая рабочая папка** (workspace, где открыт Claude Code: там CLAUDE.md, memory/, скиллы).
2. Проверь, существует ли `~/telegram_bot` (Windows: `%USERPROFILE%\telegram_bot`) — если да, добавь её второй.
3. Покажи пользователю список и спроси: **«Бэкапим эти папки? Может, добавить ещё какую-то?»** Дождись ответа.

### Шаг 2. Подготовь каждую папку (КРИТИЧНО — безопасность)

Для каждой папки из списка:

1. Если git-репозиторий не инициализирован — `git init`.
2. **Обязательно** создай/дополни `.gitignore` — до первого коммита:
   ```
   .env
   *.env
   *.session
   __pycache__/
   logs/
   *.log
   node_modules/
   .DS_Store
   ```
3. **Скан на секреты** перед первым коммитом:
   ```
   grep -rl "sk-ant-api" . --exclude-dir=.git
   ```
   плюс поиск телеграм-токенов (паттерн `[0-9]{9,10}:AA`). Если найдены файлы с реальными ключами вне `.env` — покажи пользователю список и спроси, что с ними делать (перенести в .env / добавить в .gitignore). НЕ коммить, пока не решено.
4. Сделай первый коммит: `git add -A && git commit -m "initial backup"`.

### Шаг 3. Создай скрипт авто-коммита

**macOS** — файл `~/scripts/auto_commit_backup.sh`:

```bash
#!/bin/bash
# Авто-коммит рабочих папок каждые 30 минут
FOLDERS=(
  "<папка 1>"
  "<папка 2>"
)
LOG="$HOME/Library/Logs/auto_commit_backup.log"

for DIR in "${FOLDERS[@]}"; do
  [ -d "$DIR/.git" ] || continue
  cd "$DIR" || continue
  git add -A
  if ! git diff --cached --quiet; then
    git commit -m "auto-backup $(date '+%Y-%m-%d %H:%M')" >> "$LOG" 2>&1
    # push только если настроен remote
    if git remote get-url origin >/dev/null 2>&1; then
      git push origin HEAD >> "$LOG" 2>&1 || true
    fi
  fi
done
echo "[$(date '+%Y-%m-%d %H:%M:%S')] done" >> "$LOG"
```

Сделай исполняемым: `chmod +x ~/scripts/auto_commit_backup.sh`.

**Windows** — файл `%USERPROFILE%\scripts\auto_commit_backup.ps1`:

```powershell
# Авто-коммит рабочих папок каждые 30 минут
$folders = @(
  "<папка 1>",
  "<папка 2>"
)
$log = "$env:USERPROFILE\auto_commit_backup.log"

foreach ($dir in $folders) {
  if (-not (Test-Path "$dir\.git")) { continue }
  Set-Location $dir
  git add -A
  $changes = git diff --cached --name-only
  if ($changes) {
    git commit -m "auto-backup $(Get-Date -Format 'yyyy-MM-dd HH:mm')" *>> $log
    $remote = git remote get-url origin 2>$null
    if ($remote) { git push origin HEAD *>> $log }
  }
}
Add-Content $log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] done"
```

Подставь реальные пути папок из Шага 1 вместо `<папка 1>` / `<папка 2>`.

### Шаг 4. Поставь расписание — каждые 30 минут

**macOS** — LaunchAgent `~/Library/LaunchAgents/com.user.auto-commit-backup.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.user.auto-commit-backup</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/USERNAME/scripts/auto_commit_backup.sh</string>
  </array>
  <key>StartInterval</key>
  <integer>1800</integer>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
```

Подставь реальный USERNAME. Затем загрузи:
```
launchctl unload ~/Library/LaunchAgents/com.user.auto-commit-backup.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.user.auto-commit-backup.plist
```

**Windows** — задача в Планировщике:
```
schtasks /create /f /sc minute /mo 30 /tn "AutoCommitBackup" /tr "powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File %USERPROFILE%\scripts\auto_commit_backup.ps1"
```

### Шаг 5. Проверь, что работает

1. Запусти скрипт вручную один раз (bash / powershell).
2. Проверь `git log --oneline -3` в каждой папке — должен появиться коммит `auto-backup ...` (или «initial backup», если изменений с тех пор не было).
3. macOS: `launchctl list | grep auto-commit` — задача в списке.
   Windows: `schtasks /query /tn "AutoCommitBackup"` — задача существует.

### Шаг 6 (опционально, но советуем). Облачная копия — GitHub

Локальные коммиты защищают от «Claude перезаписал» и «сам сломал». От потери ноутбука защищает только облако. Спроси пользователя: **«Есть ли аккаунт GitHub? Хочешь, настроим отправку бэкапов в приватный облачный репозиторий?»**

Если да:
1. Проверь `gh --version`; если нет — установи (`brew install gh` / `winget install GitHub.cli`).
2. `gh auth login` — проведи пользователя по авторизации через браузер.
3. Для каждой папки: `gh repo create <имя-папки>-backup --private --source=. --remote=origin --push`.
4. **Трижды проверь, что репозиторий PRIVATE** (`gh repo view --json isPrivate`) и что `.env` в `.gitignore`.

Если нет аккаунта или не хочет — ок, локальных коммитов достаточно для старта. Напомни вернуться к этому шагу позже.

### Шаг 7. Финальный отчёт пользователю

Покажи коротко:
- ✅ Какие папки под защитой
- ✅ Расписание: каждые 30 минут
- ✅ Облако: подключено / пока нет
- 📖 Как откатиться: *«Скажи мне в любом чате: "Открой папку X, посмотри последний коммит — что изменилось? Откати к рабочей версии"»*
- 📖 Как проверить, что бэкапы идут: *«Покажи последние коммиты в папке X»*

---

## Частые вопросы

**Это заменяет ручные коммиты?** Для страховки — да. Но привычка говорить «сделай commit» после законченного куска работы остаётся полезной: такие коммиты имеют осмысленные описания, по ним легче откатываться.

**Сколько места это съест?** Git хранит только изменения. Текстовые файлы второго мозга — это мегабайты. Годы бэкапов < одного фильма.

**А если я работаю в момент коммита?** Ничего страшного: коммит просто зафиксирует текущее состояние. Конфликтов не будет — всё происходит локально на твоём компьютере.

**Безопасно ли это?** Скрипт никуда ничего не отправляет, пока ты сам не подключишь GitHub (Шаг 6). `.env` с ключами исключён из бэкапов через `.gitignore`.

---

*Скилл из библиотеки AI-Потока · Икигай · 2026*
