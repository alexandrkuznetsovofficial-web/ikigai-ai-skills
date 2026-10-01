# =============================================================================
#  AI-ПОТОК · АУДИТ-ПАК (Windows)
#  Проверяет, что уже собрано, и показывает, чего не хватает до цели:
#  мозг живёт на сервере 24/7, Telegram-бот говорит с ним из подписки.
#
#  Запуск:  powershell -ExecutionPolicy Bypass -File .\audit.ps1 [папка мозга]
#  Папку мозга скрипт находит сам: workspace из %USERPROFILE%\.claude\ikigai_env.json.
#  Ничего не ломает и не устанавливает. Только смотрит.
# =============================================================================
param([string]$BrainDir = "")

$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$VERSION = "2.0"   # kit 2.0: добавлен блок 7 — точки 13–23 эталона второго мозга
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
# Порядок поиска: 1) workspace из профиля %USERPROFILE%\.claude\ikigai_env.json (пишет ikigai-preflight),
# 2) аргумент скрипта или переменная BRAIN_DIR, 3) текущая папка, если в ней CLAUDE.md и memory,
# 4) привычные места. Кандидат годится, если в нём есть CLAUDE.md или memory.
function IsBrain($p) { return ($p -and (Test-Path -LiteralPath $p -PathType Container) -and ((Test-Path -LiteralPath (Join-Path $p "CLAUDE.md")) -or (Test-Path -LiteralPath (Join-Path $p "memory")))) }
$brain = $null; $brainFrom = ""; $wsEnv = ""
$envJson = Join-Path $HOME ".claude\ikigai_env.json"
if (Test-Path $envJson) {
  try {
    $pj = [System.IO.File]::ReadAllText($envJson, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
    if ($pj.workspace_win) { $wsEnv = "" + $pj.workspace_win } elseif ($pj.workspace) { $wsEnv = "" + $pj.workspace }
    if ($wsEnv -match '^/([a-zA-Z])/(.*)$') { $wsEnv = $Matches[1] + ":\" + ($Matches[2] -replace '/','\') }
  } catch { $wsEnv = "" }
}
$brainArg = $BrainDir; if (-not $brainArg) { $brainArg = $env:BRAIN_DIR }
$cwd = (Get-Location).Path
if (IsBrain $wsEnv) { $brain = $wsEnv; $brainFrom = "профиль ikigai_env.json" }
elseif (IsBrain $brainArg) { $brain = $brainArg; $brainFrom = "указана при запуске" }
elseif ((Test-Path (Join-Path $cwd "CLAUDE.md")) -and (Test-Path (Join-Path $cwd "memory"))) { $brain = $cwd; $brainFrom = "текущая папка" }
else {
  foreach ($c in @((Join-Path $HOME "brain"), (Join-Path $HOME "second-brain"), (Join-Path $HOME "SecondBrain"), (Join-Path $HOME "Documents\brain"), (Join-Path $HOME "Documents\SecondBrain"), "C:\SecondBrain")) {
    if (IsBrain $c) { $brain = $c; $brainFrom = "нашёл в привычном месте"; break }
  }
}
if ($brain) { $brain = (Resolve-Path -LiteralPath $brain).Path.TrimEnd('\') }
# Мозг прямо в домашней папке — по ней не ходим вглубь: поиск ограничен 4 уровнями
$brainIsHome = ($brain -and ($brain.TrimEnd('\') -eq ((Resolve-Path $HOME).Path.TrimEnd('\'))))
if (-not $brain) {
  BAD "Папку второго мозга не нашёл (искал CLAUDE.md и memory)"
  if ($wsEnv) { INFO "В профиле ikigai_env.json записана папка, но в ней нет ни CLAUDE.md, ни memory" }
  INFO "Укажи папку явно: powershell -ExecutionPolicy Bypass -File .\audit.ps1 <папка мозга> — или запусти скилл ikigai-preflight, он запишет её в профиль"
  Manual "Собери папку мозга — это Модуль 1, урок 1"
} else {
  OK "Папка мозга: $brain ($brainFrom)"
  if ($brainIsHome) { INFO "Мозг лежит прямо в домашней папке — вглубь смотрю только на 4 уровня" }
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

# ------------------------------------------ 7. Второй мозг по эталону (13–23)
# Меряем без модели: файлы, поля, расписание. «Работает ли» — проверяет скилл
# second-brain-audit поведением. Счёт блока отдельный и не меняет ветку A/B/ГОТОВО.
# Точка, которой у человека нет смысла быть (расписание брифинга без брифинга-скрипта), —
# «не применимо» и в знаменатель не идёт: «X из N применимых».
H1 "7. Второй мозг по эталону (точки 13–23, kit 2.0)"
$script:PtYes=0; $script:PtPart=0; $script:PtNo=0; $script:PtNa=0; $script:PtRows=@(); $script:PtFix=@()
function PT($n, $v, $title, $detail, $fix) {
  $line = "$n · $title — $detail"
  if ($v -eq 'есть')             { $script:PtYes++;  Write-Host "  [OK]   $line" -ForegroundColor Green;  $script:Lines += "- 🟢 $line" }
  elseif ($v -eq 'частично')     { $script:PtPart++; Write-Host "  [!]    $line" -ForegroundColor Yellow; $script:Lines += "- 🟡 $line" }
  elseif ($v -eq 'не применимо') { $script:PtNa++;   Write-Host "  [-]    $line" -ForegroundColor DarkGray; $script:Lines += "- ⚪ $line" }
  else                           { $script:PtNo++;   Write-Host "  [X]    $line" -ForegroundColor Red;    $script:Lines += "- 🔴 $line" }
  $script:PtRows += "| $n | $title | $v | $detail |"
  if ($v -ne 'есть' -and $v -ne 'не применимо' -and $fix) { $script:PtFix += "точка ${n}: $fix" }
}
function ReadUtf8($p) { try { return [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8) } catch { return "" } }
# шапка файла (frontmatter): текст между первой строкой --- и следующей ---; нет шапки — $null
# (BOM снимает ReadAllText)
function FrontMatter($text) {
  if (-not $text) { return $null }
  $m = [regex]::Match($text, '^---[ \t]*\r?\n(?:([\s\S]*?)\r?\n)?[ \t]*---[ \t]*(\r?\n|$)')
  if ($m.Success) { return $m.Groups[1].Value } else { return $null }
}
$briefPy = Join-Path $HOME "morning_brief.py"

# --- скиллы набора: kit_version в шапке ИЛИ имя из списка скиллов репозитория ---
# Свои скиллы человека (не из набора) в точку 15 не идут.
$kitNames = @('ai-strategist','anthropic-academy','anti-slop-filter','auto-commit-backup','claude-autoflow','code-reviewer','content-researcher','copywriter-multiplatform','craft-to-skill','cto','deep-build','deep-focus','design-critique','devops','dossier-checker','dossier-maker','first-principles','founder-context-extractor','gpt-context-export','gtd-weekly','ikigai-graduation','ikigai-preflight','ikigai-provodnik','instagram-copywriter','kpt-psychologist','landing-architect','linkedin-copywriter','lms-builder','lms-constructor','lms-prototyper','mail-calendar-kit','memory-garden','memory-upgrade','model-switcher','morning-brief','one-thing-focus','orchestrator','oscar-hartmann','partnerships','personal-bot-upgrade','project-splitter','reels-content-factory','researcher','second-brain-architect','second-brain-audit','second-brain-os','secops','seo','team-architect','threads-copywriter','toc-analyzer','tone-of-voice-builder','triz-solver','website-builder','weekly-distill')
$skAll = 0; $skKit = 0; $skOwn = 0; $skNoHead = 0; $skNoRu = 0
$kitWith = 0; $kitWithout = 0; $kitVers = @(); $mbKit2 = $false; $skNames = @()
if (Test-Path $skills) {
  foreach ($d in (Get-ChildItem $skills -Directory)) {
    $f = Join-Path $d.FullName "SKILL.md"
    if (-not (Test-Path $f)) { continue }
    $skAll++
    $hdr = FrontMatter (ReadUtf8 $f)
    $nm = ""; $kv = ""
    if ($hdr) {
      $mn = [regex]::Match($hdr, '(?m)^\s*name:\s*(.+?)\s*$');        if ($mn.Success) { $nm = ($mn.Groups[1].Value -replace '["'']','').Trim() }
      $mv = [regex]::Match($hdr, '(?m)^\s*kit_version:\s*(.+?)\s*$'); if ($mv.Success) { $kv = ($mv.Groups[1].Value -replace '["''\s]','') }
    }
    $inKit = ($kitNames -contains $d.Name) -or ($nm -and ($kitNames -contains $nm))
    if (-not $kv -and -not $inKit) { $skOwn++; continue }
    $skKit++
    $skNames += $(if ($nm) { $nm } else { $d.Name })
    if ($kv) { $kitWith++; $kitVers += $kv } else { $kitWithout++ }
    if (($d.Name -eq 'morning-brief' -or $nm -eq 'morning-brief') -and $kv -match '^2') { $mbKit2 = $true }
    if (-not $hdr -or $hdr -notmatch '(?m)^\s*name:' -or $hdr -notmatch '(?m)^\s*description:') { $skNoHead++ }
    elseif ($hdr -notmatch '[Ѐ-ӿ]') { $skNoRu++ }
  }
}
$kitList = (($kitVers | Group-Object | Sort-Object Name | ForEach-Object { "$($_.Name) у $($_.Count)" }) -join ', ')
if ($kitWith -gt 0) { INFO "Версия набора (kit_version у скиллов набора): $kitList; без версии — $kitWithout; своих скиллов (не из набора) — $skOwn" }
elseif ($skKit -eq 0) { INFO "Версия набора: скиллов набора в ~/.claude/skills нет (своих скиллов — $skOwn)" }
else { INFO "Версия набора: ни у одного скилла набора нет kit_version — стоит набор до kit 2.0" }

if (-not $brain) {
  INFO "Папку мозга не нашёл — точки 13–23 мерить не на чем (см. блок 3)"
  foreach ($n in 13..23) { $script:PtRows += "| $n | — | не проверено | нет папки мозга |" }
} else {
  $mem = Join-Path $brain "memory"
  $cmd = Join-Path $brain "CLAUDE.md"
  $cmdText = ""; if (Test-Path $cmd) { $cmdText = ReadUtf8 $cmd }

  # Заметки сада — тот же знаменатель, что у garden_stage.py: без memory\sessions,
  # без папок secret* / .secret* / .secrets, .git, .obsidian, node_modules, .trash.
  $notes = @()
  if (Test-Path $mem) {
    $memFull = (Resolve-Path -LiteralPath $mem).Path.TrimEnd('\')
    $notes = @(Get-ChildItem $mem -Recurse -File -Filter *.md | Where-Object {
      $rel = $_.FullName.Substring($memFull.Length).TrimStart('\','/')
      $parts = @($rel -split '[\\/]')
      $dirs = @(); if ($parts.Count -gt 1) { $dirs = $parts[0..($parts.Count-2)] }
      $skip = ($dirs.Count -gt 0 -and $dirs[0] -eq 'sessions')
      foreach ($dp in $dirs) { if ($dp -in @('.git','.obsidian','.secrets','node_modules','.trash') -or $dp -like 'secret*' -or $dp -like '.secret*') { $skip = $true } }
      -not $skip })
  }
  $notesN = $notes.Count
  $texts = @{}
  foreach ($nf in $notes) { $texts[$nf.FullName] = ReadUtf8 $nf.FullName }

  # 13. Проекты отделены от ядра (мозг в домашней папке — не глубже 4 уровней)
  $rootMd = Join-Path $brain "CLAUDE.md"
  if ($brainIsHome) { $cands = @(Get-ChildItem $brain -Recurse -Depth 4 -File -Filter CLAUDE.md) } else { $cands = @(Get-ChildItem $brain -Recurse -File -Filter CLAUDE.md) }
  $nested = @($cands | Where-Object { $_.FullName -ne $rootMd -and $_.FullName -notmatch '[\\/](\.claude|node_modules|\.git)[\\/]' }).Count
  $hasProj = Test-Path (Join-Path $mem "PROJECTS.md")
  if ($hasProj -and $nested -eq 0) { PT 13 'есть' "Проекты отделены от ядра" "есть memory/PROJECTS.md, вложенных CLAUDE.md нет (тест «что ты знаешь обо мне» из папки проекта — в скилле)" }
  elseif ($hasProj -or $nested -eq 0) {
    $d13 = @(); if (-not $hasProj) { $d13 += "нет memory/PROJECTS.md" }
    if ($nested -gt 0) { $d13 += "вложенных CLAUDE.md внутри мозга: $nested — проект видит всё ядро" }
    PT 13 'частично' "Проекты отделены от ядра" ($d13 -join '; ') "memory-upgrade (черновик PROJECTS.md) и project-splitter (вынести проект из дерева мозга)"
  } else { PT 13 'нет' "Проекты отделены от ядра" "нет PROJECTS.md, вложенных CLAUDE.md внутри мозга: $nested" "memory-upgrade + project-splitter" }

  # 14. Бюджет ядра: цель ~12 000 знаков, норма до 20 000, больше 40 000 — красное
  if (Test-Path $cmd) {
    $c14 = $cmdText.Length; $t14 = [int]($c14 / 3)
    if ($c14 -le 12000)     { PT 14 'есть' "Бюджет ядра" "CLAUDE.md $c14 знаков ≈ $t14 токенов (цель ~12 000, норма до 20 000)" }
    elseif ($c14 -le 20000) { PT 14 'есть' "Бюджет ядра" "CLAUDE.md $c14 знаков ≈ $t14 токенов — в норме до 20 000, цель ~12 000 (можно ужать)" }
    elseif ($c14 -le 40000) { PT 14 'частично' "Бюджет ядра" "CLAUDE.md $c14 знаков ≈ $t14 токенов — тяжелее нормы 20 000 (цель ~12 000)" "расслоить CLAUDE.md: подробности в memory/, в ядре строка со ссылкой (weekly-distill подскажет)" }
    else                    { PT 14 'нет' "Бюджет ядра" "CLAUDE.md $c14 знаков ≈ $t14 токенов — больше 40 000, Claude Code сам предупреждает" "расслоить CLAUDE.md: подробности в memory/, в ядре строка со ссылкой" }
  } else { PT 14 'нет' "Бюджет ядра" "нет CLAUDE.md — ядра нет" "second-brain-architect / memory-upgrade" }

  # 15. Здоровье скиллов набора
  $skDup = (@($skNames | Group-Object | Where-Object { $_.Count -gt 1 } | ForEach-Object { $_.Name }) -join ' ')
  $skLocal = 0
  $lsk = Join-Path $brain ".claude\skills"
  if (Test-Path $lsk) { $skLocal = @(Get-ChildItem $lsk -Directory | Where-Object { Test-Path (Join-Path $_.FullName "SKILL.md") }).Count }
  $d15 = "скиллов набора $skKit (своих, не из набора, — $skOwn, их не оцениваю); без шапки $skNoHead; без русских триггеров $skNoRu; без kit_version $kitWithout"
  if ($skDup) { $d15 += "; одно имя у двух папок: $skDup" }
  if ($skLocal -gt 0) { $d15 += "; второе место установки в папке мозга ($skLocal шт.)" }
  $fix15Install = "поставить или обновить скиллы из пака (папка skills рядом со скриптом; в выпускном паке — папки скиллов в корне, порядок — в его README)"
  if ($skKit -eq 0) { PT 15 'нет' "Здоровье скиллов" "в ~/.claude/skills нет скиллов набора (своих — $skOwn)" $fix15Install }
  elseif ($skNoHead -eq 0 -and $skNoRu -eq 0 -and $skLocal -eq 0 -and -not $skDup -and $kitWithout -eq 0) { PT 15 'есть' "Здоровье скиллов" $d15 }
  else {
    $f15 = @()
    if ($kitWithout -gt 0) { $f15 += "$fix15Install — у $kitWithout скиллов набора нет kit_version, это версия до kit 2.0" }
    if ($skNoHead -gt 0 -or $skNoRu -gt 0 -or $skDup -or $skLocal -gt 0) { $f15 += "шапки, дубли и вторая установка: переустановить из пака в ~/.claude/skills (memory-upgrade покажет список и сохранит твои правки)" }
    PT 15 'частично' "Здоровье скиллов" $d15 ($f15 -join '; ')
  }

  # 16. Бэкап без личного в облаке
  # У папки мозга облака нет; локальный git хранит ВСЁ, включая personal/; в облако не
  # пускает pre-push-замок; .gitignore исключает только секреты и мусор. Отсутствие
  # memory/ в .gitignore — не ошибка.
  if ((Test-Path (Join-Path $brain ".git")) -and (Have git)) {
    $cloudRe = 'github\.com|gitlab\.|bitbucket\.org|codeberg\.org|gitee\.com|sr\.ht|dev\.azure\.com|visualstudio\.com|gitflic\.ru|gitverse\.ru|huggingface\.co'
    $rv = @(git -C $brain remote -v 2>$null)
    $cloud16 = @($rv | Where-Object { $_ -match $cloudRe } | ForEach-Object { ($_ -split '\s+')[0] } | Sort-Object -Unique)
    $all16 = @(git -C $brain remote 2>$null | Sort-Object -Unique)
    $other16 = @($all16 | Where-Object { $cloud16 -notcontains $_ }).Count
    if (($rv -join "`n") -match '://[^/\s]+:[^/@\s]+@') {
      WARN "В адресе git-репозитория зашит пароль или токен — адрес не показываю; смени его и убери из адреса"
    }
    $hp16 = "" + (git -C $brain rev-parse --git-path hooks 2>$null)
    if (-not $hp16) { $hp16 = Join-Path $brain ".git\hooks" } elseif (-not [System.IO.Path]::IsPathRooted($hp16)) { $hp16 = Join-Path $brain $hp16 }
    $pp16 = Join-Path $hp16 "pre-push"
    $lock16 = 0
    if (Test-Path $pp16) { if (Select-String -Path $pp16 -Pattern 'ikigai guard' -Quiet) { $lock16 = 1 } else { $lock16 = 2 } }
    $sec16 = @(git -C $brain ls-files -- .env '*.env' .secrets '*.session' 2>$null).Count
    $n16 = ""
    if ($other16 -gt 0) { $n16 += "; других адресов (свой сервер или диск, не облако): $other16" }
    if ($sec16 -gt 0) { $n16 += "; в git лежат секреты (.env / .secrets / *.session): $sec16 — их место в .gitignore" }
    if ($cloud16.Count -eq 0) {
      if ($sec16 -eq 0) { PT 16 'есть' "Бэкап без личного в облаке" "у мозга нет облачного адреса — локальный git хранит всё, включая personal/, и никуда не отправляет$n16" }
      else { PT 16 'частично' "Бэкап без личного в облаке" "облачного адреса нет$n16" "auto-commit-backup kit 2.0: .gitignore исключает секреты и мусор (.secrets/, .env, *.session, rag_db/, *.bak*)" }
    } else {
      $h16 = 0
      foreach ($r in $cloud16) { $h16 += @(git -C $brain log "--remotes=$r" --oneline -- memory/personal memory/private memory/sessions .secrets 2>$null).Count }
      if ($h16 -gt 0) { PT 16 'нет' "Бэкап без личного в облаке" "облачных адресов: $($cloud16.Count); в облачных ветках есть личное (memory/personal, private, sessions, .secrets): коммитов $h16$n16" "auto-commit-backup kit 2.0, шаг 1: убрать облачный адрес у папки мозга и поставить замок pre-push; что делать с уже отправленной историей — решаешь ты" }
      elseif ($lock16 -eq 1 -and $sec16 -eq 0) { PT 16 'есть' "Бэкап без личного в облаке" "облачных адресов: $($cloud16.Count); замок pre-push (ikigai guard) стоит, в облачных ветках личного нет (по последней синхронизации)$n16" }
      else {
        $w16 = "облачных адресов: $($cloud16.Count); в облачных ветках личного нет, но"
        if ($lock16 -eq 1) { $w16 += " замок стоит" } elseif ($lock16 -eq 2) { $w16 += " pre-push свой, без метки ikigai guard — проверь, что он не пускает memory/" } else { $w16 += " замка pre-push нет — следующая отправка может унести личное" }
        PT 16 'частично' "Бэкап без личного в облаке" "$w16$n16" "auto-commit-backup kit 2.0: убрать облачный адрес у папки мозга или поставить замок pre-push; .gitignore — только секреты и мусор"
      }
    }
  } else { PT 16 'нет' "Бэкап без личного в облаке" "мозг не под git — бэкапа нет" "auto-commit-backup kit 2.0 (локальный git по умолчанию)" }

  # 17. Специалисты вызываются
  $team17 = (@(Get-ChildItem $brain -Recurse -Depth 3 -File -Filter TEAM.md | Where-Object { $_.FullName -notmatch '[\\/]\.git[\\/]' }).Count -gt 0)
  if (-not $team17 -and (Test-Path $skills)) { $team17 = (@(Get-ChildItem $skills -Recurse -Depth 1 -File -Filter TEAM.md).Count -gt 0) }
  $hook17 = $false
  foreach ($sf in @((Join-Path $brain ".claude\settings.json"), (Join-Path $brain ".claude\settings.local.json"), (Join-Path $HOME ".claude\settings.json"))) {
    if ((Test-Path $sf) -and (Select-String -Path $sf -Pattern 'UserPromptSubmit' -Quiet)) { $hook17 = $true }
  }
  if ($team17 -and $hook17) { PT 17 'есть' "Специалисты вызываются" "TEAM.md и хук-диспетчер есть (вызывается ли скилл на деле — проверка фразами в скилле second-brain-audit)" }
  elseif ($team17) { PT 17 'частично' "Специалисты вызываются" "TEAM.md есть, хука-диспетчера нет" "orchestrator kit 2.0: TEAM.md с русскими триггерами + хук" }
  elseif ($hook17) { PT 17 'частично' "Специалисты вызываются" "хук есть, TEAM.md нет" "orchestrator kit 2.0: TEAM.md с русскими триггерами + хук" }
  else { PT 17 'нет' "Специалисты вызываются" "нет TEAM.md и хука — специалистов упоминают, а не вызывают" "orchestrator kit 2.0" }

  # 18. Сад: stage в шапке у ≥90% заметок (поле может быть с отступом внутри metadata:)
  if ($notesN -gt 0) {
    $st18 = @($notes | Where-Object { $fm = FrontMatter $texts[$_.FullName]; $fm -and $fm -match '(?m)^\s*stage:' }).Count
    $p18 = [int][math]::Floor($st18 * 100 / $notesN)
    if ($p18 -ge 90)    { PT 18 'есть' "Сад: стадии заметок" "stage: в шапке у $st18 из $notesN заметок ($p18%; без sessions и секретного)" }
    elseif ($st18 -gt 0) { PT 18 'частично' "Сад: стадии заметок" "stage: в шапке у $st18 из $notesN заметок ($p18%), норма ≥90%" "memory-garden (garden_stage.py) через memory-upgrade" }
    else                 { PT 18 'нет' "Сад: стадии заметок" "stage: в шапке нет ни у одной из $notesN заметок" "memory-garden (garden_stage.py) через memory-upgrade" }
  } else { PT 18 'нет' "Сад: стадии заметок" "в memory нет заметок" "собрать память (founder-context-extractor), потом memory-garden" }

  # 19. Граф: связано ≥50% (оценка; точно — build_memory_graph.py --stats)
  # Связь — [[имя]] / [[name-из-шапки]] или markdown-ссылка ](путь.md)
  $graph = Join-Path $HOME ".claude\graph\memory_graph.html"
  $l19 = 0; $p19 = 0
  $linkRe = '\[\[|\]\([^)]*\.md[)#]'
  if ($notesN -gt 0) {
    $targets = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($nf in $notes) {
      $tx = $texts[$nf.FullName]
      foreach ($mm in [regex]::Matches($tx, '\[\[([^\]|#]+)')) { [void]$targets.Add((($mm.Groups[1].Value -replace '\.md$','').Trim())) }
      foreach ($mm in [regex]::Matches($tx, '\]\(([^)]*?)\.md[)#]')) { [void]$targets.Add(((($mm.Groups[1].Value -split '[\\/]')[-1]).Trim())) }
    }
    foreach ($nf in $notes) {
      $tx = $texts[$nf.FullName]
      if ($tx -match $linkRe -or $targets.Contains($nf.BaseName)) { $l19++; continue }
      $nm = [regex]::Match($tx, '(?m)^\s*name:\s*(.+)$')
      if ($nm.Success -and $targets.Contains((($nm.Groups[1].Value -replace '["'']','').Trim()))) { $l19++ }
    }
    $p19 = [int][math]::Floor($l19 * 100 / $notesN)
  }
  $g19 = if (Test-Path $graph) { 'есть' } else { 'нет' }
  $d19 = "граф ~/.claude/graph/memory_graph.html: $g19; связано ≈$p19% заметок ($l19 из $notesN; ссылки [[…]] и ](….md); точно — build_memory_graph.py --stats)"
  if ($g19 -eq 'есть' -and $p19 -ge 50) { PT 19 'есть' "Граф связей" $d19 }
  elseif ($g19 -eq 'есть' -or $p19 -ge 50) { PT 19 'частично' "Граф связей" $d19 "memory-garden (build_memory_graph.py); связи добавляет weekly-distill" }
  else { PT 19 'нет' "Граф связей" $d19 "memory-garden (build_memory_graph.py) + weekly-distill" }

  # 20. Правило двойной ошибки
  $r20 = $cmdText -match '[Дд]войн.{0,40}ошибк'
  $f20 = @($notes | Where-Object { $_.Name -like 'feedback_*.md' }).Count
  if ($r20 -and $f20 -gt 0) { PT 20 'есть' "Правило двойной ошибки" "правило в CLAUDE.md есть, feedback-файлов: $f20" }
  elseif ($r20) { PT 20 'частично' "Правило двойной ошибки" "правило в CLAUDE.md есть, feedback-файлов нет" "memory-upgrade: раздел «Правило двойной ошибки» в CLAUDE.md" }
  elseif ($f20 -gt 0) { PT 20 'частично' "Правило двойной ошибки" "feedback-файлов $f20, а правила в CLAUDE.md нет" "memory-upgrade: раздел «Правило двойной ошибки» в CLAUDE.md" }
  else { PT 20 'нет' "Правило двойной ошибки" "ни правила, ни feedback-файлов — система не учится на поправках" "memory-upgrade: раздел «Правило двойной ошибки» в CLAUDE.md" }

  # 21. Журнал обещаний читается брифингом
  # Читатель — скрипт брифинга %USERPROFILE%\morning_brief.py (там должно быть слово commitments).
  # Скрипта нет (брифинг без бота) — читает сам скилл morning-brief kit 2.0, проверка скрипта не применима.
  $cf = Join-Path $mem "commitments.md"
  $c21 = Test-Path $cf
  $open21 = 0; if ($c21) { $open21 = [regex]::Matches((ReadUtf8 $cf), '\|\s*open\s*\|').Count }
  if (Test-Path $briefPy) {
    $b21 = [bool](Select-String -Path $briefPy -Pattern 'commitments' -Quiet)
    if ($c21 -and $b21) { PT 21 'есть' "Журнал обещаний" "memory/commitments.md есть (открытых: $open21), morning_brief.py его читает" }
    elseif ($c21) { PT 21 'частично' "Журнал обещаний" "memory/commitments.md есть, но morning_brief.py его не читает" "SETUP_MORNING_BRIEF kit 2.0, шаг 3: блок «Обещал — не закрыто» в скрипте брифинга" }
    elseif ($b21) { PT 21 'частично' "Журнал обещаний" "morning_brief.py умеет читать обещания, а файла memory/commitments.md нет" "memory-upgrade создаст memory/commitments.md" }
    else { PT 21 'нет' "Журнал обещаний" "нет memory/commitments.md, и morning_brief.py его не читает" "memory-upgrade + SETUP_MORNING_BRIEF kit 2.0" }
  } elseif ($mbKit2) {
    if ($c21) { PT 21 'есть' "Журнал обещаний" "memory/commitments.md есть (открытых: $open21); скрипта брифинга нет — журнал читает скилл morning-brief kit 2.0 (проверка скрипта не применима)" }
    else { PT 21 'нет' "Журнал обещаний" "нет memory/commitments.md (скрипта брифинга нет — это нормально, читает скилл morning-brief kit 2.0)" "memory-upgrade создаст memory/commitments.md" }
  } else {
    if ($c21) { PT 21 'частично' "Журнал обещаний" "memory/commitments.md есть, но читать его некому: нет ни morning_brief.py, ни скилла morning-brief kit 2.0" "поставить morning-brief kit 2.0 из пака" }
    else { PT 21 'нет' "Журнал обещаний" "нет memory/commitments.md и брифинга kit 2.0" "memory-upgrade + morning-brief kit 2.0" }
  }

  # 22. Distill живой (не старше 14 дней)
  $dd = Join-Path $mem "distill"
  $dfiles = @(); if (Test-Path $dd) { $dfiles = @(Get-ChildItem $dd -File -Filter *.md) }
  if ($dfiles.Count -gt 0) {
    $edge = (Get-Date).Date.AddDays(-14)
    $last22 = ($dfiles | ForEach-Object { if ($_.Name -match '(\d{4}-\d{2}-\d{2})') { $Matches[1] } } | Sort-Object | Select-Object -Last 1)
    $fresh22 = $false
    if ($last22) { try { $fresh22 = ([datetime]::ParseExact($last22, 'yyyy-MM-dd', $null) -ge $edge) } catch {} }
    if (-not $fresh22) { $fresh22 = [bool]($dfiles | Where-Object { $_.LastWriteTime -ge $edge } | Select-Object -First 1) }
    $show22 = if ($last22) { $last22 } else { 'дата не видна' }
    if ($fresh22) { PT 22 'есть' "Дистилляция живая" "последняя: $show22 (норма — не старше 14 дней)" }
    else { PT 22 'частично' "Дистилляция живая" "последняя: $show22 — старше 14 дней" "weekly-distill по пятницам (gtd-weekly вызывает его в конце обзора)" }
  } else { PT 22 'нет' "Дистилляция живая" "нет memory/distill/ с файлами" "weekly-distill" }

  # 23. Расписание переживает сон: задача брифинга в Планировщике со StartWhenAvailable.
  # Ищем только задачи брифинга: новую «Ikigai morning-brief» и старую «IkigaiMorningBrief».
  # Нет ни morning_brief.py, ни задачи брифинга — брифинг вызывают словами: не применимо.
  $brief = @()
  if (Have Get-ScheduledTask) {
    $brief = @(Get-ScheduledTask -TaskName 'Ikigai*' -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -eq 'Ikigai morning-brief' -or $_.TaskName -eq 'IkigaiMorningBrief' })
  }
  $newT = @($brief | Where-Object { $_.TaskName -eq 'Ikigai morning-brief' })
  $oldT = @($brief | Where-Object { $_.TaskName -eq 'IkigaiMorningBrief' })
  $newSwa = @($newT | Where-Object { $_.Settings.StartWhenAvailable })
  if ($newSwa.Count -gt 0 -and $oldT.Count -eq 0) { PT 23 'есть' "Расписание переживает сон" "брифинг в Планировщике: Ikigai morning-brief, StartWhenAvailable включён" }
  elseif ($newSwa.Count -gt 0) { PT 23 'частично' "Расписание переживает сон" "Ikigai morning-brief стоит правильно, но осталась старая задача IkigaiMorningBrief — брифинг придёт дважды" "SETUP_MORNING_BRIEF kit 2.0, шаг 4W: удалить старую задачу IkigaiMorningBrief" }
  elseif ($newT.Count -gt 0) { PT 23 'частично' "Расписание переживает сон" "задача Ikigai morning-brief есть, но без StartWhenAvailable — пропущенный запуск не догонит" "SETUP_MORNING_BRIEF kit 2.0, шаг 4W: включить «Запускать при первой возможности»" }
  elseif ($oldT.Count -gt 0) {
    $oldSwa = @($oldT | Where-Object { $_.Settings.StartWhenAvailable }).Count -gt 0
    $w23 = if ($oldSwa) { "стоит старая задача IkigaiMorningBrief (kit 1.x)" } else { "стоит старая задача IkigaiMorningBrief без StartWhenAvailable — пропущенный запуск не догонит" }
    PT 23 'частично' "Расписание переживает сон" $w23 "перенеси по SETUP_MORNING_BRIEF kit 2.0, шаг 4W: задача Ikigai morning-brief, старую удалить"
  }
  elseif (Test-Path $briefPy) { PT 23 'нет' "Расписание переживает сон" "morning_brief.py есть, а в Планировщике задачи брифинга нет — утром брифинг не придёт" "SETUP_MORNING_BRIEF kit 2.0, шаг 4W (Планировщик заданий)" }
  else { PT 23 'не применимо' "Расписание переживает сон" "брифинг не настроен как скрипт (нет morning_brief.py и задачи в Планировщике) — будить нечего" }
}

$ptAppl = $script:PtYes + $script:PtPart + $script:PtNo
$ptSum = "Эталон 13–23: есть $($script:PtYes) · частично $($script:PtPart) · нет $($script:PtNo) · не применимо $($script:PtNa) → $($script:PtYes) из $ptAppl применимых"
Write-Host ""
if ($brain) { Write-Host "  $ptSum"; $script:Lines += "" ; $script:Lines += $ptSum }
else { Write-Host "  Эталон 13–23: не проверено — нет папки мозга"; $script:Lines += "Эталон 13–23: не проверено — нет папки мозга" }
INFO "Работает ли это на деле (тест из папки проекта, вызов скиллов фразами) — проверяет скилл second-brain-audit"
if (($script:PtPart + $script:PtNo) -gt 0) { INFO "Почти всё это закрывает один скилл memory-upgrade — он покажет план и без «делай» ничего не меняет" }

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
if ($brain) { Write-Host ("ЭТАЛОН 13–23   OK есть $($script:PtYes)   ! частично $($script:PtPart)   X нет $($script:PtNo)   - не применимо $($script:PtNa)   → $($script:PtYes) из $ptAppl применимых") -ForegroundColor White }
else { Write-Host "ЭТАЛОН 13–23   не проверено — нет папки мозга" -ForegroundColor White }
Write-Host "==============================================================" -ForegroundColor Cyan

$script:Lines += "`n## Итог`n"
$script:Lines += "- Зелёных: $($script:OkN) · жёлтых: $($script:WarnN) · красных: $($script:FailN)"
$script:Lines += "- Готовность: ~$pct%"
$script:Lines += "- Ветка: **$branch** — $branchTxt"
$script:Lines += ("- Мозг на сервере думает: " + $(if($EngineOk){"да"}else{"нет"}))
$script:Lines += ("- Бот соединён и пишет тебе: " + $(if($BridgeOk){"да"}else{"нет"}))
$script:Lines += "- Второй мозг по эталону (13–23): есть $($script:PtYes) · частично $($script:PtPart) · нет $($script:PtNo) · не применимо $($script:PtNa) → **$($script:PtYes) из $ptAppl применимых**"
$script:Lines += "`n### Точки 13–23 эталона (kit 2.0)`n"
$script:Lines += "| № | Точка | Вердикт | Что видно |"
$script:Lines += "|---|---|---|---|"
$script:Lines += $script:PtRows
if ($kitWith -gt 0) { $script:Lines += "`nВерсия набора: $kitList; без версии — $kitWithout" } elseif ($skKit -eq 0) { $script:Lines += "`nВерсия набора: скиллов набора нет" } else { $script:Lines += "`nВерсия набора: kit_version нет ни у одного скилла набора — набор до kit 2.0" }

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
if ($script:PtFix.Count -gt 0) {
  $p += "ОТДЕЛЬНО — МОЙ ВТОРОЙ МОЗГ ПО ЭТАЛОНУ (точки 13–23, kit 2.0)."
  $p += "Запусти скилл second-brain-audit: он сверит меня со свежим эталоном и предложит план."
  $p += "Что нашёл аудит:"
  $i=1; foreach ($t in $script:PtFix) { $p += "$i. $t"; $i++ }
  $p += "Почти всё это ставит скилл memory-upgrade из того же репозитория. Применять — только"
  $p += "после моего «делай», ничего не удалять, сначала снимок."
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
