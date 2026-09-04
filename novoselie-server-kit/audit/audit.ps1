# =============================================================================
#  AI-ПОТОК · АУДИТ-ПАК (Windows)
#  Проверяет, что уже собрано, и показывает, чего не хватает до цели:
#  мозг живёт на сервере 24/7, Telegram-бот говорит с ним из подписки.
#
#  Запуск:  powershell -ExecutionPolicy Bypass -File .\audit.ps1
#  Ничего не ломает и не устанавливает. Только смотрит.
# =============================================================================

$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$VERSION = "1.0"
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Report     = Join-Path $ScriptDir "audit_report.md"
$PromptFile = Join-Path $ScriptDir "PROMPT_for_claude.txt"

$AccessFile = $env:BRAIN_ACCESS_FILE
if (-not $AccessFile) {
  $c1 = Join-Path $HOME ".secrets\brain\server_access.txt"
  $c2 = Join-Path $HOME ".config\brain\server_access"
  if (Test-Path $c1) { $AccessFile = $c1 } elseif (Test-Path $c2) { $AccessFile = $c2 } else { $AccessFile = $c1 }
}

$script:OkN=0; $script:WarnN=0; $script:FailN=0
$script:Lines=@(); $script:TodoManual=@(); $script:TodoAgent=@()

function H1($t){ Write-Host ""; Write-Host $t -ForegroundColor White; $script:Lines += "`n## $t`n" }
function OK($t){ $script:OkN++;   Write-Host "  [OK]   $t" -ForegroundColor Green;  $script:Lines += "- 🟢 $t" }
function WARN($t){ $script:WarnN++; Write-Host "  [!]    $t" -ForegroundColor Yellow; $script:Lines += "- 🟡 $t" }
function BAD($t){ $script:FailN++; Write-Host "  [X]    $t" -ForegroundColor Red;    $script:Lines += "- 🔴 $t" }
function INFO($t){ Write-Host "  .      $t" -ForegroundColor DarkGray; $script:Lines += "- · $t" }
function Manual($t){ $script:TodoManual += $t }
function AgentDo($t){ $script:TodoAgent += $t }
function Have($c){ return [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function ToInt($v){ $n = 0; if ([int]::TryParse(("" + $v).Trim(), [ref]$n)) { return $n } return 0 }

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "   AI-ПОТОК · АУДИТ-ПАК v$VERSION  (Windows)" -ForegroundColor Cyan
Write-Host "   Смотрим, что уже собрано и что осталось до финиша"        -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Ничего не устанавливаю и не меняю. Только смотрю."
Write-Host "Секреты (токены, пароли) на экран не выводятся — никогда."

# ---------------------------------------------------------------- 1. Компьютер
H1 "1. Твой компьютер"
$os = (Get-CimInstance Win32_OperatingSystem).Caption
OK "Система: $os"

if (Have node) {
  $nv = (node -v); $maj = ToInt ((($nv -replace '^v','') -split '\.')[0])
  if ($maj -ge 18) { OK "Node.js $nv" } else { WARN "Node.js $nv — старая версия, нужна 18 или новее"; AgentDo "обнови Node.js до версии 18+" }
} else { WARN "Node.js не найден (не обязателен, если Claude Code ставился своим установщиком)" }

if (Have git) { OK ("git " + ((git --version) -split ' ')[2]) } else { BAD "git не установлен — без него не будет истории и откатов"; Manual "Установи Git для Windows: https://git-scm.com/download/win" }
if (Have ssh) { OK "ssh-клиент есть (сможем зайти на сервер)" } else { BAD "ssh не найден"; Manual "Включи OpenSSH Client: Параметры → Приложения → Дополнительные компоненты" }
if (-not (Have curl)) { INFO "curl не найден — проверку бота сделаю средствами PowerShell" }
if ((Have code) -or (Test-Path "$env:LOCALAPPDATA\Programs\Microsoft VS Code\Code.exe")) { OK "VS Code установлен" } else { WARN "VS Code не найден"; Manual "Установи VS Code — в нём живёт Claude Code" }

# ------------------------------------------------------------- 2. Claude Code
H1 "2. Claude Code на компьютере"
$claudeLocal = $false
if (Have claude) { $cv = (claude --version 2>$null | Select-Object -First 1); OK "Claude Code установлен: $cv"; $claudeLocal = $true }
else { BAD "Claude Code не установлен на этом компьютере"; Manual "Установи Claude Code — инструкция в Модуле 0" }

if (Test-Path (Join-Path $HOME ".claude\.credentials.json")) { OK "Вход по подписке на месте" }
elseif ($claudeLocal) { WARN "Не вижу входа в Claude — открой терминал, набери claude и войди под своей подпиской"; Manual "Войди в Claude Code под своей подпиской (команда: claude)" }

if ($env:ANTHROPIC_API_KEY -or [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY","User")) {
  BAD "Найден API-ключ ANTHROPIC_API_KEY — это ОПЛАТА ПО СЧЁТЧИКУ, а не подписка"
  AgentDo "убери ANTHROPIC_API_KEY из переменных окружения: должна остаться только подписка"
} else { OK "API-ключа нет — работаешь из подписки, как и задумано" }

# ------------------------------------------------------------ 3. Папка мозга
H1 "3. Папка второго мозга"
$brain = $null
foreach ($c in @((Get-Location).Path, (Join-Path $HOME "brain"), (Join-Path $HOME "second-brain"), (Join-Path $HOME "Documents\brain"))) {
  if ((Test-Path (Join-Path $c "CLAUDE.md")) -or (Test-Path (Join-Path $c "memory"))) { $brain = $c; break }
}
if (-not $brain) {
  BAD "Папку второго мозга не нашёл (искал CLAUDE.md и memory)"
  INFO "Если она в другом месте — перейди в неё и запусти скрипт оттуда"
  Manual "Собери папку мозга — это Модуль 1, урок 1"
} else {
  OK "Папка мозга: $brain"
  if (Test-Path (Join-Path $brain "CLAUDE.md")) { OK "CLAUDE.md есть — система знает правила работы с тобой" } else { WARN "Нет CLAUDE.md"; AgentDo "создай CLAUDE.md в папке мозга" }
  if (Test-Path (Join-Path $brain "memory")) {
    $n = (Get-ChildItem (Join-Path $brain "memory") -Recurse -Filter *.md).Count
    if ($n -ge 5) { OK "Память: $n файлов — контекст собран" }
    elseif ($n -ge 1) { WARN "Память: всего $n файлов — контекста мало"; AgentDo "запусти сбор контекста (скилл founder-context-extractor)" }
    else { BAD "Папка memory пустая"; AgentDo "запусти скилл founder-context-extractor и собери контекст о себе" }
  } else { BAD "Нет папки memory — мозгу негде помнить"; AgentDo "создай memory и запусти founder-context-extractor" }
  if (Test-Path (Join-Path $brain ".git")) { OK ("Мозг под git, последнее сохранение: " + (git -C $brain log -1 --format=%cd --date=short)) }
  else { WARN "Мозг не под git — нет точек сохранения и отката"; AgentDo "заведи git в папке мозга и настрой авто-коммиты" }
}

$skills = Join-Path $HOME ".claude\skills"
if (Test-Path $skills) {
  $sn = (Get-ChildItem $skills -Directory).Count
  if ($sn -ge 10) { OK "Скиллы: $sn штук — команда на месте" }
  elseif ($sn -ge 1) { WARN "Скиллы: только $sn — пакет Модуля 1 поставлен не полностью"; AgentDo "доставь скиллы из репозитория ikigai-ai-skills" }
  else { BAD "Папка скиллов пустая"; AgentDo "поставь пакет скиллов Модуля 1" }
  foreach ($m in @("orchestrator","ikigai-provodnik")) {
    if (Test-Path (Join-Path $skills $m)) { OK "  скилл $m на месте" } else { WARN "  нет скилла $m" }
  }
  $teamMiss = @()
  foreach ($t in @("cto","secops","devops","code-reviewer","anthropic-academy","second-brain-audit")) {
    if (-not (Test-Path (Join-Path $skills $t))) { $teamMiss += $t }
  }
  if ($teamMiss.Count -eq 0) { OK "  IT-команда на месте: cto, secops, devops, code-reviewer, academy, brain-audit" }
  else { BAD ("  Нет технической команды: " + ($teamMiss -join ", ") + " — сервер будет собирать некому проверять")
         AgentDo "поставь технические скиллы из папки skills рядом с заданием в ~/.claude/skills/ (ЭТАП 0)" }
} else { BAD "Скиллы не установлены"; AgentDo "поставь пакет скиллов Модуля 1" }

# ------------------------------------------------------- 4. Заготовки к серверу
H1 "4. Заготовки к серверу"
$SrvIp=""; $SrvUser="root"; $SrvPort="22"; $HasBotToken=$false; $UserIdVal=""; $BotUsername=""

function IsPlaceholder($v){
  if ([string]::IsNullOrWhiteSpace($v)) { return $true }
  return ($v -match '^<' -or $v -match '>$' -or $v -in @('1.2.3.4','127.0.0.1','0.0.0.0','xxx','XXX'))
}
function ReadKey($file,$name){
  $l = Select-String -Path $file -Pattern "^\s*$name\s*=" -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $l) { return "" }
  return (($l.Line -split '=',2)[1]).Trim().Trim('"').Trim("'")
}

if (Test-Path $AccessFile) {
  OK "Файл доступа найден: $AccessFile"
  $SrvIp   = ReadKey $AccessFile 'SERVER_IP'
  $u       = ReadKey $AccessFile 'SERVER_USER';  if ($u) { $SrvUser = $u }
  $p       = ReadKey $AccessFile 'SERVER_PORT';  if ($p) { $SrvPort = $p }
  $bt      = ReadKey $AccessFile 'BOT_TOKEN'
  if ($bt -match '^\d+:') { $HasBotToken = $true }
  $UserIdVal = ReadKey $AccessFile 'USER_ID'
  if (-not $UserIdVal) { $UserIdVal = ReadKey $AccessFile 'OWNER_USER_ID' }

  if (IsPlaceholder $SrvIp) { BAD "IP сервера не вписан (или стоит заглушка)"; Manual "Впиши в $AccessFile строку SERVER_IP=<IP от FoxCloud>" }
  else { OK "IP сервера вписан" }
  if ($HasBotToken) { OK "Токен Telegram-бота вписан" } else { WARN "Токена бота нет в Файле доступа"; Manual "Создай бота у @BotFather и впиши BOT_TOKEN= в $AccessFile" }
  if ($UserIdVal -match '^\d+$') { OK "Твой user_id вписан ($UserIdVal)" } else { WARN "user_id не вписан"; Manual "Напиши @userinfobot, получи число, впиши USER_ID= в $AccessFile" }
} else {
  BAD "Файла доступа нет — заготовки к серверу не собраны"
  INFO "Это тот самый чек-лист из чата: сервер, бот, user_id"
  Manual "Создай файл $AccessFile (шаблон рядом: server_access.example)"
  Manual "Закажи VPS на ru.foxcloud.net, кодовое слово «Икигай», Нидерланды, Ubuntu 24.04, 2 vCPU / 4 GB / 50 GB"
  Manual "Создай бота у @BotFather → получи токен"
  Manual "Узнай свой user_id у @userinfobot"
}

if ($HasBotToken) {
  $bt = ReadKey $AccessFile 'BOT_TOKEN'
  try {
    $r = Invoke-RestMethod -Uri "https://api.telegram.org/bot$bt/getMe" -TimeoutSec 15
    if ($r.ok) { $BotUsername = $r.result.username; OK "Бот живой и отвечает Telegram: @$BotUsername" }
    else { BAD "Токен бота есть, но Telegram его не принял"; Manual "Перевыпусти токен у @BotFather (/mybots)" }
  } catch { BAD "Токен бота есть, но Telegram его не принял — токен неверный или бот удалён"; Manual "Перевыпусти токен у @BotFather (/mybots)" }
  Remove-Variable bt -ErrorAction SilentlyContinue
}

# ------------------------------------------------------------------ 5. Сервер
H1 "5. Сервер"
$SrvOk = $false; $SrvInfo = ""
$SshArgs = @('-o','BatchMode=yes','-o','StrictHostKeyChecking=accept-new','-o','ConnectTimeout=12','-p',$SrvPort)

if (IsPlaceholder $SrvIp) {
  BAD "Сервера пока нет — это главный недостающий кусок"
  INFO "Без сервера мозг живёт только пока открыт ноутбук"
} else {
  $t = & ssh @SshArgs "$SrvUser@$SrvIp" 'echo alive' 2>$null
  if ($t -match 'alive') { OK "Сервер отвечает, вход по ключу работает"; $SrvOk = $true }
  else {
    WARN "Сервер не пускает без пароля — не настроен вход по ключу"
    INFO "Починить: ssh-keygen -t ed25519   (один раз), потом скопировать ключ на сервер"
    Manual "Настрой вход по ключу на $SrvUser@$SrvIp (порт $SrvPort) и запусти аудит снова"
  }
}

$RemoteProbe = @'
. /etc/os-release 2>/dev/null
echo "OS=$PRETTY_NAME"
echo "RAM=$(free -m 2>/dev/null | awk '/Mem:/{print $2}')"
echo "CPU=$(nproc 2>/dev/null)"
echo "DISK=$(df -BG --output=size / 2>/dev/null | tail -1 | tr -dc 0-9)"
id brain >/dev/null 2>&1 && echo "BRAINUSER=yes" || echo "BRAINUSER=no"
if command -v claude >/dev/null 2>&1 || [ -x /home/brain/.local/bin/claude ]; then echo "CLAUDE=yes"; else echo "CLAUDE=no"; fi
ENVF=$(grep -rlE "^CLAUDE_CODE_OAUTH_TOKEN=" /home/brain/.config/ 2>/dev/null | head -1)
if [ -n "$ENVF" ]; then echo "OAUTH=yes"; echo "OAUTHPERM=$(stat -c %a "$ENVF" 2>/dev/null)"; else echo "OAUTH=no"; fi
grep -rqE "^ANTHROPIC_API_KEY=" /home/brain/.config/ /etc/environment 2>/dev/null && echo "APIKEY=yes" || echo "APIKEY=no"
[ -f /home/brain/CLAUDE.md ] && echo "BRAINMD=yes" || echo "BRAINMD=no"
echo "MEMN=$(find /home/brain/memory -name '*.md' 2>/dev/null | wc -l)"
U=$(systemctl list-unit-files --no-pager --no-legend 2>/dev/null | awk '{print $1}' | grep -iE 'bot|brain|bridge' | head -1)
if [ -n "$U" ]; then
  echo "UNIT=$U"
  systemctl is-active  "$U" >/dev/null 2>&1 && echo "UNITACTIVE=yes"  || echo "UNITACTIVE=no"
  systemctl is-enabled "$U" >/dev/null 2>&1 && echo "UNITENABLED=yes" || echo "UNITENABLED=no"
  systemctl cat "$U" 2>/dev/null | grep -q "Restart=always" && echo "UNITRESTART=yes" || echo "UNITRESTART=no"
else echo "UNIT="; fi
crontab -l 2>/dev/null | grep -qE "backup|snapshot|rsync" && echo "BACKUP=yes" || echo "BACKUP=no"
echo "SKILLSN=$(find /home/brain/.claude/skills -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l)"
grep -rqE "^(ALLOWED_USERS|OWNER_USER_ID|TELEGRAM_OWNER)=" /home/brain/.config/ /home/brain/*/.env 2>/dev/null && echo "WHITELIST=yes" || echo "WHITELIST=no"
ALLCRON=$( { crontab -l 2>/dev/null; sudo -u brain crontab -l 2>/dev/null; } )
echo "$ALLCRON" | grep -qE "git.*(commit|add)|auto.?commit" && echo "AUTOCOMMIT=yes" || echo "AUTOCOMMIT=no"
{ echo "$ALLCRON"; systemctl list-timers --no-pager 2>/dev/null; } | grep -qiE "brief|morning" && echo "BRIEF=yes" || echo "BRIEF=no"
[ -d /home/brain/.claude/skills/cto ] && echo "TEAMKIT=yes" || echo "TEAMKIT=no"
(command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active") && echo "UFW=yes" || echo "UFW=no"
'@

function G($key){ ($SrvInfo -split "`n" | Where-Object { $_ -match "^$key=" } | Select-Object -First 1) -replace "^$key=","" }

if ($SrvOk) {
  $SrvInfo = ($RemoteProbe | & ssh @SshArgs "$SrvUser@$SrvIp" 'bash -s' 2>$null) -join "`n"

  $sOs=(G 'OS'); $sRam=(G 'RAM'); $sCpu=(G 'CPU'); $sDisk=(G 'DISK')
  if ($sOs -match '24\.04') { OK "ОС сервера: $sOs" } else { WARN "ОС сервера: $sOs — в ките Ubuntu 24.04 LTS" }
  if ((ToInt $sRam)  -ge 3500) { OK "Память: $sRam МБ" } else { WARN "Память: $sRam МБ — по схеме нужно 4 ГБ" }
  if ((ToInt $sCpu)  -ge 2)    { OK "Ядер: $sCpu" }      else { WARN "Ядер: $sCpu — по схеме нужно 2" }
  if ((ToInt $sDisk) -ge 40)   { OK "Диск: $sDisk ГБ" }  else { WARN "Диск: $sDisk ГБ — по схеме 50 ГБ" }

  if ((G 'BRAINUSER') -eq 'yes') { OK "Отдельный пользователь brain создан (мозг живёт не под root)" }
  else { BAD "Нет пользователя brain — мозг ещё не переехал"; AgentDo "создай на сервере пользователя brain и перенеси мозг (модуль 02)" }

  if ((G 'CLAUDE') -eq 'yes') { OK "Claude Code установлен на сервере" }
  else { BAD "На сервере нет Claude Code — мозгу нечем думать"; AgentDo "поставь Claude Code на сервер" }

  if ((G 'OAUTH') -eq 'yes') {
    OK "Токен подписки на сервере есть (CLAUDE_CODE_OAUTH_TOKEN)"
    if ((G 'OAUTHPERM') -eq '600') { OK "Права на env-файл 600 — правильно" } else { WARN ("Права на env-файл " + (G 'OAUTHPERM') + ", должно быть 600"); AgentDo "поставь chmod 600 на env-файл с токеном" }
  } else {
    BAD "На сервере нет токена подписки — бот не сможет думать"
    Manual "Выполни У СЕБЯ в терминале: claude setup-token  → получишь строку sk-ant-oat..."
    Manual "Впиши её в $AccessFile строкой CLAUDE_TOKEN=... (в чат не вставлять!)"
    AgentDo "перенеси CLAUDE_TOKEN на сервер как CLAUDE_CODE_OAUTH_TOKEN, chmod 600"
  }

  if ((G 'APIKEY') -eq 'no') { OK "API-ключа на сервере нет — работает из подписки" }
  else { BAD "На сервере есть ANTHROPIC_API_KEY — он ПЕРЕБИВАЕТ подписку, платежи пойдут по счётчику"; AgentDo "убери ANTHROPIC_API_KEY с сервера (проверь и /etc/environment) — должен остаться только CLAUDE_CODE_OAUTH_TOKEN" }

  if ((G 'BRAINMD') -eq 'yes') { OK "CLAUDE.md на сервере есть" } else { WARN "На сервере нет CLAUDE.md" }
  $sMem = ToInt (G 'MEMN')
  if ($sMem -ge 5) { OK "Память на сервере: $sMem файлов — истина переехала" }
  elseif ($sMem -ge 1) { WARN "Память на сервере: $sMem файлов — переехало не всё"; AgentDo "долей память на сервер (модуль 02)" }
  else { BAD "На сервере нет памяти — мозг пустой"; AgentDo "перенеси память на сервер (модуль 02)" }

  $unit = (G 'UNIT')
  if ($unit) {
    OK "Сервис бота найден: $unit"
    if ((G 'UNITACTIVE')  -eq 'yes') { OK "  бот запущен прямо сейчас" } else { BAD "  бот НЕ запущен"; AgentDo "подними сервис бота и разберись, почему он упал" }
    if ((G 'UNITENABLED') -eq 'yes') { OK "  автозапуск после перезагрузки включён" } else { WARN "  автозапуск выключен"; AgentDo "включи автозапуск сервиса бота" }
    if ((G 'UNITRESTART') -eq 'yes') { OK "  сам поднимается после падения (Restart=always)" } else { WARN "  нет Restart=always"; AgentDo "добавь Restart=always в сервис бота" }
  } else { BAD "Сервиса бота на сервере нет — бот ещё не собран"; AgentDo "собери Telegram-бота на сервере под пользователем brain с systemd и Restart=always (модуль 03A)" }

  if ((G 'BACKUP') -eq 'yes') { OK "Бэкапы настроены" } else { WARN "Бэкапов не видно"; AgentDo "настрой бэкап: снапшоты на сервере + ночное зеркало на мой компьютер (модуль 04)" }
  if ((G 'UFW') -eq 'yes') { OK "Файрвол включён" } else { WARN "Файрвол выключен — займёмся после запуска (модуль 05)" }

  # --- сверка с definition of done ---
  $sSk = ToInt (G 'SKILLSN')
  if ($sSk -ge 5) { OK "Скиллы на сервере: $sSk — бот видит команду" }
  else { BAD "На сервере нет скиллов ($sSk) — бот видит память, но не умеет ей пользоваться"; AgentDo "перенеси ~/.claude/skills на сервер, в домашнюю папку пользователя мозга" }

  if ((G 'WHITELIST') -eq 'yes') { OK "Белый список включён — бот отвечает только владельцу" }
  else { BAD "У бота НЕТ белого списка — любой посторонний тратит твою подписку"; AgentDo "добавь проверку OWNER_USER_ID ДО вызова мозга — на текст, голосовые и фото" }

  if ((G 'AUTOCOMMIT') -eq 'yes') { OK "Автокоммиты мозга настроены" }
  else { WARN "Автокоммитов не видно — правки мозга нечем откатывать"; AgentDo "настрой автокоммиты второго мозга каждые 30 минут (auto-commit-backup)" }

  if ((G 'BRIEF') -eq 'yes') { OK "Утренний брифинг стоит в расписании" }
  else { WARN "Утреннего брифинга нет — это заодно проверка, что связка cron + бот + память жива"; AgentDo "поставь утренний брифинг по расписанию (SETUP_MORNING_BRIEF)" }

  if ((G 'TEAMKIT') -eq 'yes') { OK "IT-команда на сервере есть (точка входа — cto)" }
  else { WARN "team-kit не установлен"; AgentDo "поставь team-kit на сервер, точка входа — cto" }
}

# ------------------------------------------------------------ 6. Живые проверки
H1 "6. Живые проверки"
$EngineOk = $false; $BridgeOk = $false

$EngineProbe = @'
ENVF=$(grep -rlE "^CLAUDE_CODE_OAUTH_TOKEN=" /home/brain/.config/ 2>/dev/null | head -1)
if [ -z "$ENVF" ]; then echo "NO_ENV_FILE"; exit 0; fi
sudo -u brain -i bash -lc "unset ANTHROPIC_API_KEY; set -a; . '$ENVF'; set +a; cd /home/brain 2>/dev/null; timeout 80 claude -p 'Ответь ровно одним словом: живой'" 2>&1 | tail -3
'@

if ($SrvOk -and (G 'CLAUDE') -eq 'yes') {
  Write-Host "  .      спрашиваю мозг на сервере (до 90 сек)..." -ForegroundColor DarkGray
  $ans = ($EngineProbe | & ssh @SshArgs "$SrvUser@$SrvIp" 'bash -s' 2>$null) -join "`n"
  if ($ans -match 'жив') { OK "МОЗГ НА СЕРВЕРЕ ДУМАЕТ и отвечает из твоей подписки"; $EngineOk = $true }
  elseif ($ans -match 'credit|balance|login|auth|subscription|invalid') {
    BAD "Мозг на сервере не пускает по подписке — токен протух или не тот"
    AgentDo "перевыпусти токен подписки (claude setup-token) и положи на сервер заново"
  } else { WARN "Мозг на сервере не ответил внятно — смотри модуль 08 «Если не взлетело»" }
} else { INFO "Живую проверку мозга пропускаю — сервер или Claude Code на нём ещё не готовы" }

if ($BotUsername -and $UserIdVal -match '^\d+$') {
  Write-Host ""
  $a = Read-Host "  Отправить тебе в Telegram проверочное сообщение от @$BotUsername? [Y/n]"
  if ($a -match '^[Nn]') { INFO "Пропустил отправку" }
  else {
    $bt = ReadKey $AccessFile 'BOT_TOKEN'
    try {
      $r = Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$bt/sendMessage" -TimeoutSec 15 -Body @{
        chat_id = $UserIdVal
        text    = "Проверка связи от аудит-пака AI-Потока. Если ты видишь это сообщение — бот твой, токен верный, user_id верный."
      }
      if ($r.ok) { OK "Бот написал тебе в Telegram — проверь, сообщение должно быть уже там"; $BridgeOk = $true }
      else { BAD "Бот не смог тебе написать"; Manual "Открой @$BotUsername в Telegram и нажми Start, потом запусти аудит снова" }
    } catch {
      BAD "Бот не смог тебе написать — скорее всего ты ещё не нажала /start в чате с ним"
      Manual "Открой @$BotUsername в Telegram и нажми Start, потом запусти аудит снова"
    }
    Remove-Variable bt -ErrorAction SilentlyContinue
  }
} else { INFO "Проверку бота пропускаю — нужны токен бота и user_id" }

# ------------------------------------------------------------------- ВЕРДИКТ
$total = $script:OkN + $script:WarnN + $script:FailN
$pct = 0; if ($total -gt 0) { $pct = [int]($script:OkN * 100 / $total) }

if ((IsPlaceholder $SrvIp) -and -not $SrvOk) { $branch="A"; $branchTxt="Сервера пока нет. Твой путь: заказать VPS → перенести мозг → собрать бота." }
elseif ($EngineOk -and $BridgeOk -and $script:FailN -eq 0) { $branch="ГОТОВО"; $branchTxt="Система собрана: мозг на сервере думает, бот с ним соединён." }
else { $branch="B"; $branchTxt="Сервер есть, но собран не до конца. Твой путь: закрыть красные пункты выше." }

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ("ИТОГ   OK $($script:OkN)   ! $($script:WarnN)   X $($script:FailN)      готовность ~$pct%") -ForegroundColor White
Write-Host ("ВЕТКА $branch — $branchTxt") -ForegroundColor White
Write-Host "==============================================================" -ForegroundColor Cyan

$script:Lines += "`n## Итог`n"
$script:Lines += "- Зелёных: $($script:OkN) · жёлтых: $($script:WarnN) · красных: $($script:FailN)"
$script:Lines += "- Готовность: ~$pct%"
$script:Lines += "- Ветка: **$branch** — $branchTxt"
$script:Lines += ("- Мозг на сервере думает: " + $(if($EngineOk){"да"}else{"нет"}))
$script:Lines += ("- Бот соединён и пишет тебе: " + $(if($BridgeOk){"да"}else{"нет"}))

if ($script:TodoManual.Count -gt 0) {
  Write-Host ""; Write-Host "СДЕЛАТЬ РУКАМИ — это нельзя поручить агенту:" -ForegroundColor White
  $script:Lines += "`n### Сделать руками`n"
  $i=1; foreach ($t in $script:TodoManual) { Write-Host "  $i. $t"; $script:Lines += "$i. $t"; $i++ }
}
if ($script:TodoAgent.Count -gt 0) {
  Write-Host ""; Write-Host "СДЕЛАЕТ АГЕНТ — готовый текст лежит в PROMPT_for_claude.txt" -ForegroundColor White
  $script:Lines += "`n### Сделает агент`n"
  $i=1; foreach ($t in $script:TodoAgent) { Write-Host "  $i. $t"; $script:Lines += "$i. $t"; $i++ }
}

$p = @()
$p += "Ты мой технический помощник. Я участница AI-Потока. Цель: мой второй мозг живёт"
$p += "на моём сервере 24/7, а мой Telegram-бот разговаривает с ним из моей ПОДПИСКИ"
$p += "(переменная CLAUDE_CODE_OAUTH_TOKEN), а не по API-ключу."
$p += ""
$p += "Я прогнала аудит. Вот что он нашёл — отчёт целиком в файле:"
$p += $Report
$p += ""
$p += "МОЯ ВЕТКА: $branch — $branchTxt"
$p += ""
if ($script:TodoAgent.Count -gt 0) {
  $p += "ЗАКРОЙ ЭТИ ПУНКТЫ, по одному, после каждого — короткий отчёт мне:"
  $i=1; foreach ($t in $script:TodoAgent) { $p += "$i. $t"; $i++ }
  $p += ""
}
$p += "ПРАВИЛА (соблюдай неукоснительно):"
$p += "- Никогда не выводи в чат пароли и токены. Только путь к файлу и факт наличия."
$p += "- Секреты живут в env-файлах с правами 600. Не в коде, не в git, не в чате."
$p += "- Личное (здоровье, семья, финансы) на сервер НЕ переносим."
$p += "- Команду claude setup-token я выполняю САМА в своём терминале — ты её не запускаешь"
$p += "  и её вывод не читаешь."
$p += "- Ничего необратимого без моего явного «да»."
$p += "- Инструкции бери из кита novoselie-server-kit в репозитории"
$p += "  https://github.com/alexandrkuznetsovofficial-web/ikigai-ai-skills"
$p += "  (модуль 02 — переезд мозга, 03A — бот с нуля, 03 — подключение готового бота,"
$p += "   04 — бэкапы, 05 — безопасность, 06 — приёмка, 08 — если не взлетело)."
$p += ""
$p += "Сначала покажи мне план. Потом делай."
$p += "Когда закончишь — я снова запущу аудит, и он должен показать зелёным"
$p += "«МОЗГ НА СЕРВЕРЕ ДУМАЕТ» и «Бот написал тебе в Telegram»."
$p -join "`r`n" | Out-File -FilePath $PromptFile -Encoding UTF8

(@("# Аудит AI-Поток — " + (Get-Date -Format 'yyyy-MM-dd HH:mm')) + $script:Lines) -join "`r`n" | Out-File -FilePath $Report -Encoding UTF8

Write-Host ""
Write-Host "ЧТО ДЕЛАТЬ ПРЯМО СЕЙЧАС" -ForegroundColor White
Write-Host ""
Write-Host "  1. Если выше есть пункты «сделать руками» — сделай их, это 15-20 минут."
Write-Host "  2. Открой Claude Code в папке своего мозга."
Write-Host "  3. Скопируй туда текст из файла:"
Write-Host "     $PromptFile"
Write-Host "  4. Когда агент закончит — запусти аудит снова."
Write-Host ""
Write-Host "  Отчёт сохранён: $Report"
Write-Host "  Застряла больше 20 минут — пиши в чат Потока, не жди следующей встречи."
Write-Host ""
