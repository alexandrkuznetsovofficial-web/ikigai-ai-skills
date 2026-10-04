---
name: memory-garden
description: Цифровой сад для памяти второго мозга — размечает заметки стадиями «росток / побег / вечнозелёная» и строит граф связей памяти одним HTML-файлом. Запускать фразами «посади сад», «размечай стадии», «разметь память стадиями», «построй граф памяти», «покажи граф», «покажи граф памяти», «поставь сад по пятницам», «/memory-garden». Сначала сухой прогон и отчёт, запись — только после «делай». Повторный запуск ничего не меняет.
kit_version: 2.0
---

# Цифровой сад: стадии заметок и граф памяти

Ты помогаешь человеку увидеть, **насколько созрела** его память, и показать её связи картинкой.
Скрипты делают всю механику без модели и без интернета; твоя задача — запустить их по шагам,
объяснить результат человеческим языком и ничего не записать без согласия.

## Идея за две минуты (рассказать человеку своими словами)

Цифровой сад — подход Майка Колфилда (Mike Caulfield, «The Garden and the Stream», 2015), его
подхватили в сообществе заметок, а Тиаго Форте в «Втором мозге» описал ту же мысль как
«прогрессивное суммирование»: заметка не рождается готовой, она дозревает, когда к ней возвращаются.

| Стадия | Поле в шапке | Что это |
|---|---|---|
| 🌱 росток | `stage: seed` | сырая мысль, пара строк, без структуры и связей |
| 🌿 побег | `stage: sprout` | к мысли возвращались: есть структура, ссылки, примеры |
| 🌳 вечнозелёная | `stage: evergreen` | лучшее текущее понимание, на него опираются: правила, справочники, индекс |

Зачем это нужно: (1) видно, где в памяти сырьё, а где опора; (2) пятничная дистилляция
(`/weekly-distill`) повышает стадии тех заметок, к которым возвращались, — сад растёт сам;
(3) граф показывает «острова» — заметки, ни с чем не связанные: их или связать, или в архив.

Стадия ≠ PARA. Метка `para:` отвечает «когда понадобится» (проект / зона / справочник / архив),
`stage:` — «насколько созрела». Это два независимых поля.

## Что лежит в скилле

```
~/.claude/skills/memory-garden/
├── SKILL.md
└── scripts/
    ├── garden_stage.py         разметка стадий (сухой прогон по умолчанию, --apply — запись)
    ├── build_memory_graph.py   граф → ~/.claude/graph/memory_graph.html
    ├── garden_weekly.py        оба шага одной командой — его зовёт расписание
    └── vendor/force-graph.min.js + LICENSE-force-graph.txt   библиотека графа, MIT, v1.43.5
```

Ставится папкой целиком из репозитория `ikigai-ai-skills` (в нём папка `memory-garden/`).
Без папки `scripts/` скилл не работает — проверь, что она есть, прежде чем начинать.
Python 3.8+, без внешних библиотек. Лицензия библиотеки графа — MIT (force-graph, © Vasco Asturiano),
текст лицензии лежит рядом с ней.

## Шаг А0. Профиль компьютера и папка памяти

Прочитай `~/.claude/ikigai_env.json`. Нет файла или он старше 30 дней — запусти
`bash ~/.claude/skills/ikigai-preflight/scripts/probe.sh`. Из профиля нужны `os_branch`,
`python_cmd` и `workspace` (рабочая папка, где лежит `CLAUDE.md`). Папка памяти — `<workspace>/memory`.
Профиля и пробника нет — определи систему сам (`uname` / наличие `py`) и спроси человека,
где его рабочая папка.

| Что | Mac | Windows (команды выполняет Claude через Git Bash) |
|---|---|---|
| Python | `python3` | `py -3`, иначе `python` |
| Папка скилла | `~/.claude/skills/memory-garden/scripts` | `~/.claude/skills/memory-garden/scripts` в Git Bash; человеку — `%USERPROFILE%\.claude\skills\memory-garden` |
| Граф | `~/.claude/graph/memory_graph.html` | `%USERPROFILE%\.claude\graph\memory_graph.html` |
| Открыть граф | `open ~/.claude/graph/memory_graph.html` | `start "" "%USERPROFILE%\.claude\graph\memory_graph.html"` через `cmd //c` |
| Расписание | launchd, `com.ikigai.memory-garden` | Планировщик заданий, задача `Ikigai memory-garden` |

Ниже `PY` — команда Python из таблицы, `S` — папка скриптов, `MEM` — `<workspace>/memory`.

## Шаг 1. Сухой прогон — «посади сад», «размечай стадии»

```bash
PY S/garden_stage.py --root "MEM" -v
```

Ничего не записывается. Покажи человеку итог коротко:

```
🌱 Сад — сухой прогон
Заметок: N (без sessions/ и секретных папок)
росток N · побег N · вечнозелёная N
Уже со стадией: N — их не трогаю
Чужое поле stage (например, стадия сделки): N — не трогаю
Без шапки: N — им можно дописать шапку (отдельное согласие)
Будет изменено: N файлов. Содержимое заметок не меняется — только две строки в шапке.
Делаем?
```

🛑 **Стоп. Ждёшь «делай» / «да».** Без ответа ничего не записываешь.

Правила разметки (детерминированные, по контракту памяти kit 2.0):
- `feedback_*`, `reference_*`, `playbook_*`, `MEMORY.md`, `PROJECTS.md`, `commitments.md` → вечнозелёная;
- всё в папках `drafts/` и `inbox/` → росток;
- короткая заметка без ссылок → росток;
- остальное → побег. Файлы в `archive/` получают стадию по своему происхождению.

Что скрипт не трогает никогда: заметки, где `stage:` уже стоит — даже внутри блока `metadata:`
(Claude иногда переносит поля туда); чужие значения `stage:`; папки `sessions/`, `secret*` на любом уровне,
`.secrets`, `.git`, `.obsidian` и файлы `secret*`; время изменения файлов (брифинг по нему находит «последние задачи»).
Файлы с BOM и окончаниями строк Windows сохраняются в том же виде. Запись атомарная: сначала временный
файл рядом, потом замена — оборванный прогон не оставит половину заметки.
Строка `---` в начале заметки, под которой нет ни одной строки вида `ключ:`, — это горизонтальная линия,
а не шапка: в неё ничего не вставляется.

## Шаг 2. Запись

```bash
PY S/garden_stage.py --root "MEM" --apply
```

Были заметки без шапки и человек согласился дописать им шапку — отдельной командой:

```bash
PY S/garden_stage.py --root "MEM" --apply --add-frontmatter
```

**Признак готовности:** повторный запуск `--apply` пишет «реально изменено файлов: 0».
Не ноль — покажи человеку, какие файлы меняются второй раз, и не запускай дальше: это ошибка, а не сад.

## Шаг 3. Граф — «построй граф памяти», «покажи граф»

```bash
PY S/build_memory_graph.py --root "MEM"
```

Показываешь на экране кому-то ещё (встреча, созвон) — добавь `--no-personal`, тогда папки
`personal/` и `private/` (на любом уровне) в граф не попадают даже именами файлов. Заметки и папки,
чьё имя начинается с `secret`, в граф не попадают никогда.

Граф кладётся **вне памяти**: `~/.claude/graph/` (Windows — `%USERPROFILE%\.claude\graph\`), рядом —
`memory_graph_stats.json` и копия библиотеки. Так имена личных заметок не уезжают в облако или на сервер
вместе с памятью. Интернет графу не нужен.

Открой граф человеку (команда из таблицы А0). **Признак готовности:** в браузере облако точек,
цвета по стадиям, при наведении виден путь заметки. Пустой экран с текстом «Не загрузилась библиотека» —
рядом с HTML нет `force-graph.min.js`: проверь, что в скилле есть `scripts/vendor/`, и пересобери.

Как читать человеку:
- **«связано N %»** — доля заметок хотя бы с одной связью. Ориентир эталона — от 50 %.
- **Острова** (точки без линий) — кандидаты связать с проектом или отправить в `archive/` на пятничной дистилляции.
- **Битые ссылки** — в `memory_graph_stats.json`, поле `top_broken`. Ссылки в файлах скрипт не переписывает:
  `[[имя_файла]]` и `[[name-из-шапки]]` оба рабочие, «-» и «_» считаются одинаковыми.
- Для аудита без записи файлов: `PY S/build_memory_graph.py --root "MEM" --stats` (только JSON в вывод).

## Шаг 4. Расписание — пятница 18:00, переживает сон компьютера

Спроси: «Поставить, чтобы сад размечался и граф пересобирался сам каждую пятницу в 18:00?»
Только после «да». Cron не используем: он пропускает запуск, если компьютер в это время спал.

### Mac — launchd

Подставь абсолютные пути (без `~`): `PY_ABS` = `command -v python3`, `HOME_ABS` = `$HOME`, `MEM`.

```bash
PY_ABS=$(command -v python3)
cat > ~/Library/LaunchAgents/com.ikigai.memory-garden.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ikigai.memory-garden</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PY_ABS}</string>
    <string>${HOME}/.claude/skills/memory-garden/scripts/garden_weekly.py</string>
    <string>--root</string>
    <string>MEM</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>${HOME}/.claude/graph/memory_garden.launchd.log</string>
  <key>StandardErrorPath</key><string>${HOME}/.claude/graph/memory_garden.launchd.log</string>
</dict>
</plist>
EOF
mkdir -p ~/.claude/graph
plutil -lint ~/Library/LaunchAgents/com.ikigai.memory-garden.plist
launchctl bootout gui/$(id -u)/com.ikigai.memory-garden 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ikigai.memory-garden.plist
launchctl kickstart gui/$(id -u)/com.ikigai.memory-garden     # пробный запуск прямо сейчас
```

Если компьютер спал в пятницу в 18:00, launchd выполнит задачу при пробуждении.

**Признак готовности:** через полминуты `tail -5 ~/.claude/graph/memory_garden.log` показывает
свежую строку «=== дата ===» и «реально изменено файлов: 0». В логе `Operation not permitted` —
рабочая папка лежит в «Документах» или на «Рабочем столе», и macOS не пускает туда фоновую задачу.
Ход: Системные настройки → Конфиденциальность и безопасность → Полный доступ к диску → добавить
тот `python3`, путь к которому стоит в plist; затем снова `launchctl kickstart …`.

### Windows — Планировщик заданий

`schtasks` не умеет флаг «запускать при первой возможности после пропуска», поэтому задача ставится
через PowerShell. Из Git Bash `schtasks` и PowerShell с косыми чертами вызывать напрямую нельзя:
Git Bash превращает `/create` в путь. Пишешь файл и запускаешь его.

`MEM_WIN` — путь к памяти в виде Windows: `C:\Users\Имя\…\memory`. Получи его из Git Bash:
`MEM_WIN=$(cygpath -w "MEM")` и подставь в файл ниже значением (в файле не должно остаться слово `MEM_WIN`).

Создай файл `~/.claude/graph/install_memory_garden.ps1`:

```powershell
$py = (Get-Command py -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command python).Source; $pre = '' } else { $pre = '-3 ' }
$script = "$env:USERPROFILE\.claude\skills\memory-garden\scripts\garden_weekly.py"
$action = New-ScheduledTaskAction -Execute $py -Argument "$pre`"$script`" --root `"MEM_WIN`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 18:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "Ikigai memory-garden" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "Ikigai memory-garden"
Get-ScheduledTask -TaskName "Ikigai memory-garden" | Select-Object TaskName, State
(Get-ScheduledTask -TaskName "Ikigai memory-garden").Settings.StartWhenAvailable
```

🔴 **Сохрани файл в UTF-8 с BOM.** Windows PowerShell 5.1 читает `.ps1` без BOM в кодировке ANSI,
и путь с кириллицей (`C:\Users\Иван\…`) превращается в кракозябры — задача встанет на несуществующую
папку. Инструмент записи файлов пишет без BOM, поэтому после записи пересохрани файл:

```bash
powershell -NoProfile -Command '$p = "$env:USERPROFILE\.claude\graph\install_memory_garden.ps1"; $t = [IO.File]::ReadAllText($p); [IO.File]::WriteAllText($p, $t, (New-Object Text.UTF8Encoding $true))'
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME/.claude/graph/install_memory_garden.ps1"
```

**Признак готовности:** последняя строка вывода — `True` (запуск после пропуска включён), а в
`%USERPROFILE%\.claude\graph\memory_garden.log` появилась свежая запись. Человеку покажи только итог:
«Сад будет обновляться сам каждую пятницу в 18:00; если компьютер был выключен — при следующем включении».

Убрать расписание: Mac — `launchctl bootout gui/$(id -u)/com.ikigai.memory-garden` и удалить plist;
Windows — `Unregister-ScheduledTask -TaskName "Ikigai memory-garden" -Confirm:$false`.

## Статус проверки

| Путь | Статус |
|---|---|
| Скрипты на Mac (Python 3.9 и 3.14), фикстура 19 заметок: BOM, CRLF, `metadata:`, чужая стадия, `[[name-slug]]` | ✅ повторный `--apply` = 0 изменений, граф строится |
| launchd на Mac | 🧪 команды стандартные, на машине участника не проходили |
| Windows: скрипты и Планировщик | 🧪 по документации |

Пока стоит 🧪 — предупреди человека до начала: «твой случай мы ещё не проходили живьём, идём
медленнее и после каждого шага сверяемся».

## Правила

- Сухой прогон всегда первым. Запись — только после «делай».
- Ничего не удалять, ссылки не переписывать, чужие стадии не трогать.
- Граф и его статистика — только вне папки памяти. В облако и на сервер не отправлять.
- Повысить стадию вручную (росток → побег → вечнозелёная) — работа `/weekly-distill`: он ставит
  `stage_source: manual`, и авторазметка такую стадию больше не трогает.
