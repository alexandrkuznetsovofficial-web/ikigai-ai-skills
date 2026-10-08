# brain-link · лаборатория (GitHub Actions)

Автотесты связки brain-link вместо тестового VPS и Windows-машины. Запускается workflow
`.github/workflows/brain-link-lab.yml` (push в ветки `kit-*` и вручную). Ничего наружу не ходит,
секретов репозитория не использует, «сервер участника» эмулируется на самом раннере.

Это **тестовая оснастка**, не часть кита участника. В дистрибутив (`tools/build_dist.py`) папка `ci/`
не входит. Всё здесь — только стандартная библиотека Python 3.9+ / POSIX sh / Windows PowerShell 5.1.

## Что внутри

| Файл | Роль |
|---|---|
| `fake_claude.py` | заглушка `claude`: эмулирует `claude -p`, пишет полученные argv/env/cwd в журнал (сам токен — только sha256), по меткам в промпте проверяет фильтр секретов бота. На «сервер» ставится дважды: как `~/.local/bin/claude` владельца (бот её НЕ зовёт) и, в ELF-обёртке, как root-копия бота через `brain-admin update-claude`. |
| `make_lab_claude_installer.py` | собирает лабораторный «официальный установщик»: ELF-обёртку над `fake_claude.py` (cc) в раскладке `~/.local/share/claude/versions/<версия>` + симлинк `~/.local/bin/claude`. `server_e2e.sh` кладёт его root-файлом `/etc/brain-bot/lab-claude-installer.sh`, и `update-claude` проходит штатный путь (ELF, `--version`, sha256) без скачивания. На серверах участников этого файла нет. |
| `fake_telegram.py` | локальный Bot API на `127.0.0.1`: `getUpdates`/`sendMessage`/`getMe` + управление `/_ctl/update`, `/_ctl/sent`. Токен нигде не пишет, только его sha256. |
| `bot_scenario.py` | сценарий «владелец и чужой пишут боту»: молчание чужому и группе, режимы файлы/веб с полной проверкой argv и окружения, модель sonnet/opus, фильтр секретов, «запомни»→inbox, ни одного токена в исходящих. |
| `drive_link.py` | запускает `brain_link.py` с подменой внедряемых зависимостей: `--getpass-file` (put-token без терминала), `--sync-shim` (расписание через local-транспорт), `--lockdown-bad-key` (проверка автоотката lockdown). |
| `sync_shim.py` | запасной вариант: настоящий `brain_sync.main` с транспортом из `BRAIN_SYNC_TRANSPORT` или `~/.config/brain/ci_transport.txt`. Интеграционные сценарии его больше не используют — `schedule` сам передаёт транспорт (см. ниже). |
| `askpass_probe.py` / `win_askpass.ps1` | вход по паролю через `SSH_ASKPASS` (помощник `make_askpass`): probe зовёт ssh напрямую с askpass.cmd/askpass.sh, `win_askpass.ps1` поднимает локальный OpenSSH Server Windows с пользователем `root` по паролю и гоняет настоящий `keys` (неверный пароль → `password_rejected`, верный → `key_installed=password`, утечки пароля нет). Ubuntu-вариант — шаг 3 `server_e2e.sh`. |
| `smoke_json.py` | смоук «один JSON в UTF-8 и ожидаемый код», в т.ч. под `PYTHONIOENCODING=cp1251` и в фейковом HOME с пробелом и кириллицей. |
| `cmdline_watch.py` | сторож RT-12: токен не появляется в `/proc/*/cmdline` во время audit/verify (пишет только pid/comm/метку). |
| `hostile_tar.py` | враждебные архивы для RT-10 (симлинк, hardlink, `..`, абсолютный путь, вне зоны, >20 МБ, gzip-бомба, план-бомба) + честный контроль. |
| `server_e2e.sh` | поднимает sshd на `127.0.0.1:2222` и прогоняет шаги установщика по «серверу участника» на самом раннере. `SCENARIO=upgrade` (job `server-upgrade`, kit 2.3) — «старый» сервер: чужой `brain-bot.service` (мост claude-code-telegram, токен в `Environment=`, владелец в `.env`), `60-cloudimg-settings.conf` с паролем, память на сервере → detect видит старого бота, harden его не трогает, `put-token bot --yes` переносит токен на сервере, `bot --yes` кладёт копию юнита в `/var/backups/brain-link`, `adopt`, настоящий `lockdown` и `sshd -T` = no/no/no. После него root закрыт — RT-проверки в этом job не идут. |
| `security_checks.sh` | защитные регресс-проверки RT-6…RT-16: каждая утверждает, что защита сработала (отказ, нет записи, нет утечки). Цели — только временные приманки в `$RUNNER_TEMP`, НИКОГДА реальные системные пути. |
| `mac_integration.sh` / `win_integration.ps1` | расписание (launchd / Планировщик задач) настоящим `brain_link.py schedule` и настоящим `brain_sync.py`, транспорт local через `BRAIN_SYNC_TRANSPORT`. Фоновая задача не наследует окружение скрипта, поэтому служебные файлы — в штатных местах под (фейковым на Mac / настоящим одноразовым на Windows) домашним каталогом. `.ps1` здесь — UTF-8 с BOM (CRLF даёт `.gitattributes`). |

## Lab-only drop-in для бота (ослабление — только для лаборатории)

Юниты бота глушат localhost (`IPAddressDeny=localhost`), поэтому под настоящим systemd бот не достучится
до фейкового Telegram на `127.0.0.1`. В лаборатории `server_e2e.sh` кладёт **drop-in только для CI**:

```
# /etc/systemd/system/brain-bot.service.d/zz-lab.conf — ТОЛЬКО лаборатория, в прод не едет
[Service]
IPAddressAllow=127.0.0.1/32
Environment=TELEGRAM_API_BASE=http://127.0.0.1:<порт>
```

⚠️ Это осознанное ослабление сетевой изоляции (разрешён выход на localhost) и переключение адреса Bot API,
допустимое **только** на раннере GitHub Actions ради теста. В ките участника и на реальном сервере такого
drop-in нет: `brain-link bot` его не создаёт, кладёт его исключительно `server_e2e.sh`.

## Зависимости от кода других агентов (хуки тестируемости)

- **`BRAIN_SYNC_TRANSPORT`** — `schedule` пробрасывает транспорт в фоновую задачу (plist: EnvironmentVariables + `--transport`; Windows: `install_task.ps1 -Transport`).
- **`BRAIN_LAB_SKIP_UFW_ENABLE=1`** — `harden` пропускает `ufw --force enable`, но правила всё равно задаёт
  (проверяются через `ufw show added`), чтобы `ufw enable` не рвал сеть раннера.

## Чего лаборатория НЕ проверяет

Реального Claude и подписку (стоит заглушка), реальный Telegram (локальный фейк), реальный VNC-вход
провайдера и реальный провайдерский firewall. Эти уровни — ручная приёмка на живом сервере перед встречей.
