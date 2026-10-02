# Конвенции китов Академии: Mac и Windows в одном скилле

> Для всех, кто пишет или правит скиллы в этом репозитории. Правила появились 17.09.2026 после обратной
> связи корпоративной команды: на Mac Модуль 0 прошли за полтора часа, на Windows — за восемнадцать. Причина
> не в видео, а в том, что скиллы написаны под один компьютер и не проверяют результат шага.

## 1. Профиль компьютера читается первым (правило А0)

Каждый скилл, который выполняет команды, начинает с чтения `~/.claude/ikigai_env.json`. Файла нет или он
старше 30 дней — запустить пробник: `bash ~/.claude/skills/ikigai-preflight/scripts/probe.sh`.
Поле `os_branch` (`mac` / `windows` / `linux`) определяет колонку команд. Пробник лежит в `ikigai-preflight/`.

## 2. Две колонки там, где команды расходятся

Если шаг на Mac и на Windows выполняется по-разному, в скилле стоит таблица из двух колонок, а не одна
маковская команда с припиской «на Windows аналогично». Эталон — `mail-calendar-kit/SKILL.md`, раздел А0.

| Что | Mac | Windows (Claude Code выполняет команды через Git Bash) |
|---|---|---|
| Домашняя папка | `~` | `~` внутри Git Bash, `%USERPROFILE%` в тексте для человека |
| Python | `python3` | `py -3`, иначе `python` |
| Окружение пака | `~/.venvs/<kit>/bin/python` | `%USERPROFILE%\.venvs\<kit>\Scripts\python.exe` |
| Открыть файл человеку | `open -a "Visual Studio Code" <путь>` | `code <путь>`, иначе `notepad <путь>` |
| Расписание | launchd (`~/Library/LaunchAgents/*.plist`) | Планировщик задач (`schtasks`) |
| Права на файл с секретами | `chmod 600` | не нужно, файл в личной папке пользователя |
| Установка git | `xcode-select --install` | `winget install --id Git.Git -e --source winget` |

На Windows человеку **не показывают** команды с `chmod`, `bash`, `~`, `brew`, `launchctl`, `open -a`.
Он не программист: чужая команда с ошибкой означает для него «я сломался».

## 3. После каждого шага — проверка с признаком

Шаг заканчивается не словом «готово», а признаком, который человек видит сам: «если на экране X — шаг
сделан; если нет — вот следующий ход». Признаки, проверенные на живых учениках: Claude подключён к VS Code —
чат в панели с оранжевым логотипом ответил (не «расширение установлено» и не «Enabled»); Handy работает —
русский текст появился после диктовки; папка памяти открыта — её имя в заголовке окна VS Code.

## 3а. Что сейчас 🧪 (обновлять по факту прогона)

| Путь | Статус на 17.09.2026 |
|---|---|
| `ikigai-preflight` на Mac | ✅ пройден руками |
| `ikigai-preflight` на Windows | 🧪 прогнан в эмуляции Git Bash и парсером PowerShell, на живой Windows не проверялся |
| `auto-commit-backup`, `SETUP_MORNING_BRIEF`, `second-brain-os` — ветки Windows | 🧪 по документации |
| `mail-calendar-kit` — ветка Windows | 🧪 по документации |

Пока стоит 🧪 — предупреждай человека до начала: «твой случай мы ещё не проходили живьём, идём медленнее
и после каждого шага сверяемся». Прошли живьём — меняй метку здесь и в карточке на полке.

## 4. Честные метки готовности

В README и в карточке на полке указано, какие пути пройдены руками, а какие написаны по документации (🧪).
Не обещать Windows, пока путь не пройден на Windows. Метки: «Mac», «Mac или Windows», «Windows 🧪 не проверено».

## 5. Файлы и архивы

Имена файлов и папок — только латиница, цифры, `_` и `-`. Архивы для студентов собираются на сервере
(`python3 -m zipfile`), не в Finder: иначе кириллица в именах превращается в кракозябры на Windows.

## 6. Что пробник кладёт в профиль

`os_branch`, `os_version`, `arch`, `home`, `claude_cli`, `claude_signed_in`, `vscode`, `vscode_ext_claude`,
`git`, `node`, `python_cmd`, `python`, `handy`, `handy_model`, `workspace`, `workspace_has_claude_md`,
`workspace_latin`, `skills_dir`, `skills_count`, `ffmpeg`, `whisper_cli`, `brew`, `checked_at`.
Секретов в профиле нет и быть не должно.

## 7. Контракт памяти (kit 2.0; 2.1 — + §8) — единый для всех скиллов

Все скиллы, которые читают или пишут память, опираются только на эти пути и поля. Скилл, которому
нужен новый файл, сначала дописывает его сюда. `tools/check_kit.py` сверяет тексты скиллов с этой картой.

**Рабочая папка** (`workspace` из профиля пробника) — папка, где лежит `CLAUDE.md`:

| Путь | Что | Пишет | Читает |
|---|---|---|---|
| `CLAUDE.md` | правила системы; содержит раздел «Правило двойной ошибки» | architect, memory-upgrade | все |
| `memory/MEMORY.md` | индекс памяти, раздел «Оперативное» | все (одна строка на задачу) | все |
| `memory/ACTIVE.md` | фокус: активные задачи. **Единственное место.** Если есть старый `ACTIVE.md` в корне — memory-upgrade ставит в нём строку-указатель, файл не двигает | architect, os, memory-upgrade, founder-context-extractor | morning-brief, orchestrator, audit |
| `memory/tasks/` | журналы задач `task_YYYY-MM-DD_slug.md` | os, все рабочие скиллы | morning-brief, weekly-distill |
| `memory/insights/`, `memory/personal/`, `memory/reasoning/` | инсайты · личное (никогда не в облако) · ход мыслей | os | по делу |
| `memory/archive/` | завершённое (архивировать, не удалять) | weekly-distill, gtd-weekly | audit |
| `memory/distill/distill_YYYY-MM-DD.md` | итог пятничной дистилляции | weekly-distill | morning-brief (пт), audit |
| `memory/brief_YYYY-MM-DD.md` | брифинг без Telegram-бота (файл + системное уведомление) | SETUP_MORNING_BRIEF (режим без бота) | человек, audit (точка 23) |
| `memory/commitments.md` | журнал обещаний: таблица `дата \| обязательство \| проверить \| статус \| источник`, статус `open` / `done` / `dropped`; `para: project`. Строки не удаляются и не переносятся в архив — меняется только статус | architect, memory-upgrade, weekly-distill, os | morning-brief, audit |
| `memory/PROJECTS.md` | проекты (PARA · Projects, `para: project`): таблица `проект \| цель \| срок \| статус \| где лежит`, статус `active` / `paused` / `done` / `dropped`. Сюда же — цели года из интервью (результат со сроком). Строки не удаляются | architect, memory-upgrade, founder-context-extractor, weekly-distill | morning-brief, audit |
| `memory/inbox/` | заметки из Telegram («запомни …»), см. §8 | бот (brain-link) | Claude на компьютере разбирает по папкам |
| `memory/dialogues/` | журнал диалогов с ботом по дням | бот (brain-link) | по делу |
| `memory/feedback_*.md` | правила из повторных правок (правило двойной ошибки) | os, orchestrator | все |
| `memory/feedback_double_error.md` | журнал правила двойной ошибки: шапка `name: feedback_double_error`, `para: area`; раздел `## Журнал` с таблицей `дата \| что поправили дважды \| правило \| файл` — os и orchestrator дописывают туда строку. Образец один — `templates/feedback_double_error.md` | architect, memory-upgrade | os, orchestrator |
| `memory/user_profile.md` | Master Prompt 1 000–2 000 слов (`para: area`, `stage: evergreen`) + факты о человеке по разделам: «Кто я», «Бизнес», «История решений», «Куда иду» | founder-context-extractor | CLAUDE.md (импорт), все |
| `memory/strategy/personal_strategy.md` | личная стратегия основателя. Файл один: следующий скилл **дополняет** его по разделам, не перезаписывает | homework-1/ai-strategist, orchestrator | ai-strategist, orchestrator, audit |
| `memory/reference_*.md`, `memory/playbook_*.md` | справочники и плейбуки (вечнозелёные) | weekly-distill, os | по делу |
| `memory/goals.md`, `memory/identity.md`, `memory/company.md`, `memory/history.md` | **наследие kit 1.x**. Есть у ученика — читаются как запасной путь (факты — после `user_profile.md`, цели — после `PROJECTS.md`); founder-context-extractor их больше не создаёт, факты пишет в `user_profile.md`, цели — в `PROJECTS.md` | — (новые не создаются) | morning-brief, extractor, os |
| `memory/areas/`, `memory/projects/`, `memory/resources/` | раскладка коуча-проводника папками (PARA папками). Не двигаем: метки `para:` ставятся поверх | coach | все |
| `memory/private/`, `memory/sessions/`, `memory/wiki/` | наследие / опция: private и sessions никогда не в облако; wiki — справочник `para: resource` | os | по делу |

**Поля шапки** (frontmatter) у заметок памяти:
- `para: project | area | resource | archive` (+ `para_source: rule | manual`);
- `stage: seed | sprout | evergreen` (+ `stage_source: rule | manual`) — стадии цифрового сада.

Поля читаются **с отступом и без**: `^\s*поле:`. Claude при записи памяти может переносить поля
внутрь блока `metadata:`. Скрипт, который ищет только `^поле:`, ставит дубли. Чужие значения
поля `stage:` (не seed / sprout / evergreen) не трогать.

**Ссылки:** `[[имя_файла]]` и `[[name-из-шапки]]` — рабочие оба. Ссылки в файлах не переписывать.

**Вне рабочей папки:**
- скиллы — только `~/.claude/skills/<имя>/SKILL.md` (скрипты скилла — в его `scripts/`);
- карта команды — только `~/.claude/skills/<папка оркестратора>/TEAM.md`, **единственное место**. Специалисты-скиллы —
  в основной таблице, субагенты из `~/.claude/agents/*.md` — в разделе «Агенты» того же файла. Старый
  `memory/ai-team.md` — наследие: читается, новых не создаём (team-architect пишет план в `TEAM.md` или ссылку на него);
- главный агент (ассистент с именем, которое дал ученик) — `~/.claude/skills/<имя-латиницей>/SKILL.md`,
  собирается по **одному** шаблону `templates/main_agent.md`. Extractor, os и orchestrator своих шаблонов не держат —
  ссылаются на этот. Брифинг главный агент делегирует скиллу `morning-brief` и триггеров брифинга сам не держит;
- снимок перед миграцией memory-upgrade — `~/.claude/backups/`;
- отчёты выпускного чекапа — `~/.claude/audit/checkup_<дата>_before.md` (повтор за день — `_before_2.md`, не перезаписывается), `_after.md` и сохранённый эталон `_standard.md` (пишет second-brain-audit, читает ikigai-graduation для слайда «было → стало»);
- граф памяти — `~/.claude/graph/memory_graph.html`. Он лежит вне памяти, чтобы не уезжать в облако и на сервер вместе с именами личных файлов. Библиотека графа лежит рядом, без CDN.

**Расписание** (брифинг, пятничный сад) должно переживать сон компьютера:

| Система | Чем | Не годится |
|---|---|---|
| Mac | launchd, `~/Library/LaunchAgents/com.ikigai.<имя>.plist` | cron |
| Windows | Планировщик заданий, задача `Ikigai <имя>` с `StartWhenAvailable` | — |
| Сервер Linux | systemd timer с `Persistent=true` (cron допустим: сервер не спит) | — |

**Старт сессии в `CLAUDE.md`** — один якорь `## 🌅 Старт сессии` (ставит architect). Старый заголовок
`🌅 АВТОЗАПУСК СЕССИИ` (morning-brief 1.x) считается тем же блоком: нашёлся любой из двух — второй не дописывать.

**Бюджет ядра `CLAUDE.md`:** цель ≤ ~12 000 знаков, норма до 20 000. Больше — расслоить (регламент в отдельный файл,
в ядре триггер и ссылка), а не поднимать потолок.

**Бэкап и облако — одна формула для всех скиллов:**
- у папки мозга облака нет (нет `remote`); GitHub — только для кода и скиллов, в отдельной папке;
- локальный git хранит **всё**, включая `memory/personal/` и `sessions/` — иначе нет отката;
- в облако не пускает замок `pre-push` (скилл `auto-commit-backup`), даже если адрес когда-нибудь появится;
- `.gitignore` мозга исключает **только секреты и мусор**: `.secrets/`, `.env`, `*.session`, `rag_db/`, `brain-rag/`, `*.bak*`.
  `memory/personal/`, `memory/private/`, `sessions/` в `.gitignore` не пишутся.

Пароли и коды подтверждения у ученика модель не просит.

**Версии:** в шапке каждого скилла есть `kit_version: 2.0`. Аудит показывает версию, которая стоит у ученика.

## 8. Контракт связки «компьютер — мастерская, сервер — база» (kit 2.1)

Модель «как у Александра». **Компьютер** (Mac или Windows) — мастерская: Claude Code в VS Code видит
локальные файлы, здесь правится память и ставятся скиллы. **Сервер** (Ubuntu 24.04, вне РФ) — база:
бот в Telegram 24/7, утренний брифинг, реплика памяти. Связывает их `brain-sync` каждые 5 минут.
Старая модель «истина на сервере, компьютер — окно + ночное зеркало» снята; как с неё уйти — `brain-link adopt`.

**Зоны и владельцы.** У каждой зоны ровно один хозяин — так правки не теряются молча и удаления не воскресают.

| Зона | Хозяин | Направление | Если разошлось |
|---|---|---|---|
| `memory/**` (кроме двух зон ниже) и `~/.claude/skills/**` | компьютер | компьютер → сервер | версия сервера сохраняется на компьютере как `имя.conflict-server-ГГГГММДД-ЧЧММ.ext`, сервер перезаписывается, уведомление |
| `memory/inbox/` | бот | сервер → компьютер | имена уникальные (`ГГГГ-ММ-ДД_ЧЧММСС_tg.md`), конфликтов нет; забранное сервер переносит в `inbox/.synced/` (30 дней). На компьютере Claude разбирает inbox по папкам — это уже зона компьютера |
| `memory/dialogues/` | бот | сервер → компьютер | только дописывается; правка на компьютере → `.conflict-local` |

**Исключено в обе стороны:** `personal/ private/ secret*/ sessions/ .secrets/ .git/ .config/ node_modules/ .venv/ __pycache__/`,
файлы `.env *.env *.session *.bak* *.conflict-* .DS_Store`, любой файл больше 20 МБ. Список живёт в одном месте —
`brain-link/scripts/brainlib.py` (`EXCLUDES`); `tools/check_kit.py` сверяет его с этой таблицей.

**Правила синка.** Решения по sha содержимого, не по времени (сдвиг часов не портит данные; расхождение > 120 с —
предупреждение). Удаление на компьютере → файл на сервере уходит в `~/.brain-trash/ДАТА/` (30 дней).
Больше 25 удалений или больше 10 % зоны за прогон — стоп до `brain-sync run --allow-mass-delete`.
Пути приводятся к NFC. Права на сервере ставит сервер (brain, 0640/0750) — права компьютера не переносятся.
Синк идёт **не через git**, поэтому замок pre-push из `auto-commit-backup` ему не мешает.

**Служебные файлы — вне рабочей папки**, в `~/.config/brain/` (Windows `%USERPROFILE%\.config\brain\`):
`server_access` (файл доступа), `known_hosts` (ключ сервера закреплён, `StrictHostKeyChecking=yes`),
`sync_state.json`, `sync_status.json`, `sync.pause`, `sync.lock`, `logs/sync.log`.

**Файл доступа — одна схема на весь кит:** `SERVER_IP`, `SERVER_USER` (до установки — `root`), `SERVER_PORT` (22),
`BOT_TOKEN`, `USER_ID`, `PASSWORD` (временно, удаляется после `lockdown`). Токен подписки в файл **не пишется** —
ученик сам запускает `claude setup-token` и передаёт его на сервер через `brain-link put-token` (ввод скрыт).
Старые ключи `IP / LOGIN / PORT / CLAUDE_TOKEN` читаются как запасной вариант с предупреждением.

**Сервер.** Рабочая папка — `/home/brain` (`CLAUDE.md`, `memory/`, скиллы в `/home/brain/.claude/skills`).
Пользователь `brain` без пароля и без полного sudo; администрирование — `sudo brain-admin <команда>` (белый список).
Ключ синка `~/.ssh/brain_sync_ed25519` ограничен в `authorized_keys` командой `brain_sync_server.py`.
Секреты бота — `/etc/brain-bot/credentials/` (root 0600, `LoadCredential`), не в окружении и не в дереве `/home/brain`.
Транспорт к модели — только `claude -p`; `ANTHROPIC_API_KEY` не ставится нигде. Вход: только ключи (`lockdown`),
**без белого списка IP** (ученики на VPN). Аварийный вход — VNC-консоль провайдера.

**Расписания (§7):** `com.ikigai.brain-sync` (launchd, 300 с) / задача `Ikigai brain-sync` (каждые 5 мин,
`StartWhenAvailable`); на сервере `brain-bot.service`, `brain-brief.timer`, `brain-watch.timer`.
Утренний брифинг живёт в **одном** месте: есть бот — только на сервере.

**Перед массовой правкой памяти** (`memory-upgrade`, `garden_stage --apply`, `project-splitter`) — `brain-sync pause`,
после — `brain-sync resume` и `brain-sync run`.
