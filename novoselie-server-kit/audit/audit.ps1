# =============================================================================
#  AI-ПОТОК · АУДИТ-ПАК (Windows)
#  Проверяет, что уже собрано, и показывает, чего не хватает до цели (kit 2.1):
#  компьютер — мастерская, сервер — база. Правишь на компьютере, сервер держит
#  копию памяти и Telegram-бота 24/7, бот говорит из подписки.
#
#  Запуск:  powershell -ExecutionPolicy Bypass -File .\audit.ps1 [папка мозга]
#  Папку мозга скрипт находит сам: workspace из %USERPROFILE%\.claude\ikigai_env.json.
#  Ничего не ломает и не устанавливает. Только смотрит.
# =============================================================================
param([string]$BrainDir = "")

$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# PowerShell 5.1 по умолчанию шлёт в stdin внешних программ ASCII — кириллица в скриптах для сервера превратилась бы в «?»
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
$VERSION = "2.1"   # kit 2.0: блок 7 — точки 13–23 эталона; kit 2.1: файл доступа §8, блок 8 — связка brain-link
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Report     = Join-Path $ScriptDir "audit_report.md"
$PromptFile = Join-Path $ScriptDir "PROMPT_for_claude.txt"

# Файл доступа (KIT_CONVENTIONS §8): %USERPROFILE%\.config\brain\server_access; старый путь — запасной, с предупреждением
$AccessNew = Join-Path $HOME ".config\brain\server_access"
$AccessOld = Join-Path $HOME ".secrets\brain\server_access.txt"
$AccessLegacyPath = $false
$AccessFile = $env:BRAIN_ACCESS_FILE
if (-not $AccessFile) {
  if (Test-Path $AccessNew) { $AccessFile = $AccessNew }
  elseif (Test-Path $AccessOld) { $AccessFile = $AccessOld; $AccessLegacyPath = $true }
  else { $AccessFile = $AccessNew }
}
$CfgBrain = Join-Path $HOME ".config\brain"
$KnownHosts = Join-Path $CfgBrain "known_hosts"
$AdminKey = Join-Path $HOME ".ssh\id_ed25519"

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
  Manual "Собери папку мозга — это Модуль 1, шаг 1"
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
  $l = Select-String -Path $file -Pattern "^\s*(export\s+)?$name\s*=" -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $l) { return "" }
  return (($l.Line -split '=',2)[1]).Trim().Trim('"').Trim("'")
}

if (Test-Path $AccessFile) {
  OK "Файл доступа найден: $AccessFile"
  if ($AccessLegacyPath) { WARN "Файл доступа лежит по старому пути — перенеси его в $AccessNew (brain-link detect скопирует сам)"; AgentDo "запусти brain-link detect: он перенесёт файл доступа на новый путь" }
  # новые ключи §8; старые IP / LOGIN / PORT — запасной вариант с предупреждением
  $oldKeys = @()
  $SrvIp   = ReadKey $AccessFile 'SERVER_IP'
  if (-not $SrvIp) { $SrvIp = ReadKey $AccessFile 'IP'; if ($SrvIp) { $oldKeys += 'IP→SERVER_IP' } }
  $u       = ReadKey $AccessFile 'SERVER_USER'
  if (-not $u) { $u = ReadKey $AccessFile 'LOGIN'; if ($u) { $oldKeys += 'LOGIN→SERVER_USER' } }
  if ($u) { $SrvUser = $u }
  $p       = ReadKey $AccessFile 'SERVER_PORT'
  if (-not $p) { $p = ReadKey $AccessFile 'PORT'; if ($p) { $oldKeys += 'PORT→SERVER_PORT' } }
  if ($p) { $SrvPort = $p }
  if ($oldKeys.Count -gt 0) { WARN ("В файле доступа старые ключи: " + ($oldKeys -join ', ') + " — переименуй (схема kit 2.1)"); AgentDo ("переименуй в файле доступа старые ключи: " + ($oldKeys -join ', ') + " (значения не показывай)") }
  if (ReadKey $AccessFile 'CLAUDE_TOKEN') { WARN "В файле доступа лежит CLAUDE_TOKEN — токен подписки там не хранится"; Manual "Удали строку CLAUDE_TOKEN из файла доступа; токен на сервер передаётся шагом brain-link put-token claude (ты запускаешь сама)" }
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
  Manual "Создай файл $AccessFile (шаблон рядом: server_access.example; ключи SERVER_IP, SERVER_USER, SERVER_PORT, BOT_TOKEN, USER_ID)"
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
# Ключ сервера — только закреплённый (brain-link keys кладёт его в .config\brain\known_hosts); новый ключ молча не принимаем
$SshArgs = @('-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=12','-p',$SrvPort)
if ((Test-Path $KnownHosts) -and (Get-Item $KnownHosts).Length -gt 0) {
  # путь в кавычках внутри значения: ssh делит значение -o по пробелам (C:\Users\Имя Фамилия\...).
  # Прямые слэши ssh понимает и на Windows. Windows PowerShell 5.1 (и pwsh до 7.3) не экранирует кавычки
  # внутри аргумента для внешней программы — экранируем сами (\"), иначе ssh получит обрезанный путь.
  $khOpt = 'UserKnownHostsFile="' + ($KnownHosts -replace '\\', '/') + '"'
  $legacyArgs = ($PSVersionTable.PSVersion.Major -lt 7) -or ($PSVersionTable.PSVersion.Major -eq 7 -and $PSVersionTable.PSVersion.Minor -lt 3) -or ((Get-Variable PSNativeCommandArgumentPassing -ValueOnly -ErrorAction SilentlyContinue) -eq 'Legacy')
  if ($legacyArgs) { $khOpt = $khOpt.Replace('"', '\"') }
  $SshArgs += @('-o', $khOpt)
}
if (Test-Path $AdminKey) { $SshArgs += @('-i',$AdminKey) }
# скрипт для сервера идёт в stdin; tr снимает CR, которые PowerShell добавляет к строкам
$RemoteBash = "tr -d '\r' | bash -s"

if (IsPlaceholder $SrvIp) {
  BAD "Сервера пока нет — это главный недостающий кусок"
  INFO "Без сервера мозг живёт только пока открыт ноутбук"
} else {
  # после brain-link lockdown root закрыт — тогда ходим под brain
  foreach ($cand in @($SrvUser, 'brain')) {
    $t = & ssh @SshArgs "$cand@$SrvIp" 'echo alive' 2>$null
    if ($t -match 'alive') { $SrvUser = $cand; $SrvOk = $true; break }
  }
  if ($SrvOk) {
    OK "Сервер отвечает, вход по ключу работает (пользователь $SrvUser)"
    if ((Test-Path $KnownHosts) -and (Get-Item $KnownHosts).Length -gt 0) { OK "Ключ сервера закреплён (.config\brain\known_hosts)" } else { WARN "Ключ сервера не закреплён в .config\brain\known_hosts — это делает brain-link keys" }
  } else {
    WARN "Сервер не пускает по ключу (или ключ сервера не закреплён)"
    INFO "Починить: шаг brain-link keys — он создаст ключи, закрепит ключ сервера и покажет одну команду"
    Manual "Скажи Claude Code: «Запусти brain-link, шаг keys» — и выполни одну команду, которую он покажет (пароль root вводишь сама)"
  }
}

$RemoteProbe = @'
. /etc/os-release 2>/dev/null
echo "OS=$PRETTY_NAME"
echo "RAM=$(free -m 2>/dev/null | awk '/Mem:/{print $2}')"
echo "CPU=$(nproc 2>/dev/null)"
echo "DISK=$(df -BG --output=size / 2>/dev/null | tail -1 | tr -dc 0-9)"
id brain >/dev/null 2>&1 && echo "BRAINUSER=yes" || echo "BRAINUSER=no"
if [ -x /home/brain/.local/bin/claude ] || command -v claude >/dev/null 2>&1; then echo "CLAUDE=yes"; else echo "CLAUDE=no"; fi
if [ "$(id -u)" = 0 ]; then
  if [ -s /etc/brain-bot/credentials/claude_token ]; then echo "OAUTH=yes"; echo "OAUTHPERM=$(stat -c '%a %U' /etc/brain-bot/credentials/claude_token)"; echo "OAUTHKIND=cred"
  else ENVF=$(grep -rlE "^CLAUDE_CODE_OAUTH_TOKEN=" /home/brain/.config/ 2>/dev/null | head -1)
    if [ -n "$ENVF" ]; then echo "OAUTH=yes"; echo "OAUTHPERM=$(stat -c '%a %U' "$ENVF")"; echo "OAUTHKIND=env"; else echo "OAUTH=no"; fi
  fi
else
  sudo -n brain-admin status 2>/dev/null | grep -q 'claude_token' && { echo "OAUTH=yes"; echo "OAUTHPERM=$(sudo -n brain-admin status 2>/dev/null | awk '/claude_token/{print $1, $2}' | head -1)"; echo "OAUTHKIND=cred"; } || echo "OAUTH=unknown"
fi
grep -sqE "ANTHROPIC_API_KEY" /etc/environment /home/brain/.profile /home/brain/.bashrc /home/brain/.bash_profile /etc/systemd/system/brain-*.service 2>/dev/null \
  || grep -rqsE "^ANTHROPIC_API_KEY=" /home/brain/.config/ 2>/dev/null && echo "APIKEY=yes" || echo "APIKEY=no"
( [ -f /home/brain/CLAUDE.md ] && echo "BRAINMD=yes" ) || echo "BRAINMD=no"
echo "MEMN=$(find /home/brain/memory -name "*.md" 2>/dev/null | wc -l)"
if systemctl list-unit-files brain-bot.service --no-legend 2>/dev/null | grep -q brain-bot; then U=brain-bot.service
else U=$(systemctl list-unit-files --no-pager --no-legend 2>/dev/null | awk '{print $1}' | grep -iE "bot|brain|bridge" | grep -vE '^brain-(brief|watch)' | head -1); fi
if [ -n "$U" ]; then
  echo "UNIT=$U"
  systemctl is-active  "$U" >/dev/null 2>&1 && echo "UNITACTIVE=yes"  || echo "UNITACTIVE=no"
  systemctl is-enabled "$U" >/dev/null 2>&1 && echo "UNITENABLED=yes" || echo "UNITENABLED=no"
  systemctl cat "$U" 2>/dev/null | grep -q "Restart=always" && echo "UNITRESTART=yes" || echo "UNITRESTART=no"
  echo "UNITUSER=$(systemctl show -p User --value "$U" 2>/dev/null)"
else echo "UNIT="; fi
[ -f /home/brain/.brain-sync/heartbeat ] && echo "HEARTBEAT=$(stat -c %Y /home/brain/.brain-sync/heartbeat)" || echo "HEARTBEAT="
crontab -l 2>/dev/null | grep -qE "backup|snapshot|rsync" && echo "BACKUP=yes" || echo "BACKUP=no"
echo "SKILLSN=$(find /home/brain/.claude/skills -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l)"
if systemctl show -p Environment --value brain-bot.service 2>/dev/null | tr ' ' '\n' | grep -qE '^OWNER_ID=[0-9]+$'; then echo "WHITELIST=yes"
else grep -rqE "^(ALLOWED_USERS|OWNER_USER_ID|TELEGRAM_OWNER)=" /home/brain/.config/ /home/brain/*/.env 2>/dev/null && echo "WHITELIST=yes" || echo "WHITELIST=no"; fi
ALLCRON=$( { crontab -l 2>/dev/null; sudo -n -u brain crontab -l 2>/dev/null; } )
echo "$ALLCRON" | grep -qE "git.*(commit|add)|auto.?commit" && echo "AUTOCOMMIT=yes" || echo "AUTOCOMMIT=no"
{ echo "$ALLCRON"; systemctl list-timers --no-pager 2>/dev/null; } | grep -qiE "brief|morning" && echo "BRIEF=yes" || echo "BRIEF=no"
[ -d /home/brain/.claude/skills/cto ] && echo "TEAMKIT=yes" || echo "TEAMKIT=no"
# ufw: только «ufw status» (от root или через brain-admin); systemctl is-active ufw врёт. Нет ufw (контейнерный VPS) — none.
if [ "$(id -u)" = 0 ]; then
  if ! command -v ufw >/dev/null 2>&1; then echo "UFW=none"
  else ufw status 2>/dev/null | grep -q "Status: active" && echo "UFW=yes" || echo "UFW=no"; fi
else
  BAS=$(sudo -n brain-admin status 2>/dev/null)
  if printf '%s\n' "$BAS" | grep -qiE '^(ufw[: ]+active|status: active)'; then echo "UFW=yes"
  elif printf '%s\n' "$BAS" | grep -qiE '^(ufw[: ]+(inactive|not active)|status: inactive)'; then echo "UFW=no"
  else echo "UFW=unknown"; fi
fi
echo "LK_NOW=$(date +%s)"
echo "LK_NTP=$(timedatectl show -p NTPSynchronized --value 2>/dev/null)"
echo "LK_PRIVATE=$(find /home/brain/memory /home/brain/.claude/skills -type d \( -name personal -o -name private -o -iname 'secret*' -o -name sessions -o -name .secrets \) 2>/dev/null | head -3 | tr '\n' ' ')"
echo "LK_F2B=$(systemctl is-active fail2ban 2>/dev/null)"
if [ "$(id -u)" = 0 ]; then
  echo "LK_PWAUTH=$(sshd -T 2>/dev/null | awk '$1=="passwordauthentication"{print $2}')"
  P=$(stat -c '%a %U' /etc/brain-bot/credentials/bot_token /etc/brain-bot/credentials/claude_token 2>/dev/null | sort -u | tr '\n' ';')
  echo "LK_CREDS=$P"
else
  [ -f /etc/ssh/sshd_config.d/00-brain.conf ] && echo "LK_PWAUTH=no" || echo "LK_PWAUTH=unknown"
  P=$(sudo -n brain-admin status 2>/dev/null | awk '/_token/{print $1, $2}' | sort -u | tr '\n' ';')
  echo "LK_CREDS=$P"
fi
[ -f /etc/ssh/sshd_config.d/00-brain.conf ] && echo "LK_LOCKDOWN=yes" || echo "LK_LOCKDOWN=no"
# RT-11: токены бота (исходные и выданные юниту в /run/credentials) от brain не читаются
if [ "$(id -u)" = 0 ]; then LKAS="runuser -u brain --"; else LKAS=""; fi
LKR=no
for f in /etc/brain-bot/credentials/claude_token /etc/brain-bot/credentials/bot_token \
         /run/credentials/brain-bot.service/claude_token /run/credentials/brain-bot.service/bot_token; do
  $LKAS cat "$f" >/dev/null 2>&1 && LKR=yes
done
echo "LK_CREDREAD=$LKR"
echo "LK_DISK=$(df --output=pcent /home 2>/dev/null | tail -1 | tr -dc 0-9)"
'@

function G($key){ ((($SrvInfo -split "`n" | Where-Object { $_ -match "^$key=" } | Select-Object -First 1) -replace "^$key=","") + "").Trim() }

if ($SrvOk) {
  $SrvInfo = ($RemoteProbe | & ssh @SshArgs "$SrvUser@$SrvIp" $RemoteBash 2>$null) -join "`n"

  $sOs=(G 'OS'); $sRam=(G 'RAM'); $sCpu=(G 'CPU'); $sDisk=(G 'DISK')
  if ($sOs -match '24\.04') { OK "ОС сервера: $sOs" } else { WARN "ОС сервера: $sOs — в ките Ubuntu 24.04 LTS" }
  if ((ToInt $sRam)  -ge 3500) { OK "Память: $sRam МБ" } else { WARN "Память: $sRam МБ — по схеме нужно 4 ГБ" }
  if ((ToInt $sCpu)  -ge 2)    { OK "Ядер: $sCpu" }      else { WARN "Ядер: $sCpu — по схеме нужно 2" }
  if ((ToInt $sDisk) -ge 40)   { OK "Диск: $sDisk ГБ" }  else { WARN "Диск: $sDisk ГБ — по схеме 50 ГБ" }

  if ((G 'BRAINUSER') -eq 'yes') { OK "Отдельный пользователь brain создан (мозг живёт не под root)" }
  else { BAD "Нет пользователя brain — сервер ещё не подготовлен"; AgentDo "запусти brain-link, шаг harden (модуль 02)" }

  if ((G 'CLAUDE') -eq 'yes') { OK "Claude Code установлен на сервере" }
  else { BAD "На сервере нет Claude Code — мозгу нечем думать"; AgentDo "запусти brain-link, шаг claude (официальный установщик под brain)" }

  if ((G 'OAUTH') -eq 'yes') {
    if ((G 'OAUTHKIND') -eq 'cred') { OK "Токен подписки на сервере есть (/etc/brain-bot/credentials, kit 2.1)" }
    else { OK "Токен подписки на сервере есть (env-файл старой модели)"; WARN "Токен лежит в env-файле в ~brain/.config — в kit 2.1 он живёт в /etc/brain-bot/credentials"; AgentDo "перенеси токен по-новому: brain-link put-token claude (я запущу сама), старый env-файл потом удали" }
    if ((G 'OAUTHPERM') -match '^(600|-rw-------) (root|brain)$') { OK "Права на файл с токеном 600 — правильно" } else { WARN ("Права на файл с токеном: " + (G 'OAUTHPERM') + " — должно быть 600"); AgentDo "поставь права 600 на файл с токеном подписки на сервере" }
  } elseif ((G 'OAUTH') -eq 'unknown') {
    INFO "Токен подписки отсюда не виден (вход под brain без brain-admin) — проверит brain-link verify"
  } else {
    BAD "На сервере нет токена подписки — бот не сможет думать"
    Manual "Запусти САМА в PowerShell: py -3 `"`$env:USERPROFILE\.claude\skills\brain-link\scripts\brain_link.py`" put-token claude — токен вводится скрыто и сразу уходит на сервер (в чат и в файл доступа не вставлять!)"
  }

  if ((G 'APIKEY') -eq 'no') { OK "API-ключа на сервере нет — работает из подписки" }
  else { BAD "На сервере есть ANTHROPIC_API_KEY — он ПЕРЕБИВАЕТ подписку, платежи пойдут по счётчику"; AgentDo "убери ANTHROPIC_API_KEY с сервера (проверь /etc/environment, профили brain и юниты brain-*) — токен подписки остаётся только в /etc/brain-bot/credentials" }

  if ((G 'BRAINMD') -eq 'yes') { OK "CLAUDE.md на сервере есть" } else { WARN "На сервере нет CLAUDE.md" }
  $sMem = ToInt (G 'MEMN'); $sHb = (G 'HEARTBEAT')
  if ($sMem -ge 5) { OK "Копия памяти на сервере: $sMem файлов" }
  elseif ($sMem -ge 1) { WARN "Копия памяти на сервере: всего $sMem файлов"; AgentDo "проверь синк: brain-link status, затем brain-link init (новый сервер) или adopt (старая модель)" }
  else { BAD "На сервере нет памяти — бот отвечает вслепую"; AgentDo "включи синк памяти: brain-link init (чистый сервер) или adopt (сервер по старой модели)" }

  $unit = (G 'UNIT')
  if ($unit) {
    OK "Сервис бота найден: $unit"
    if ((G 'UNITACTIVE')  -eq 'yes') { OK "  бот запущен прямо сейчас" } else { BAD "  бот НЕ запущен"; AgentDo "подними сервис бота и разберись, почему он упал" }
    if ((G 'UNITENABLED') -eq 'yes') { OK "  автозапуск после перезагрузки включён" } else { WARN "  автозапуск выключен"; AgentDo "включи автозапуск сервиса бота" }
    if ((G 'UNITRESTART') -eq 'yes') { OK "  сам поднимается после падения (Restart=always)" } else { WARN "  нет Restart=always"; AgentDo "добавь Restart=always в сервис бота" }
    if ($unit -ne 'brain-bot.service') { WARN "  это не стандартный brain-bot kit 2.1"; AgentDo "поставь стандартного бота: brain-link, шаг bot (старый будет выключен, не удалён)" }
  } else { BAD "Сервиса бота на сервере нет — бот ещё не собран"; AgentDo "запусти brain-link, шаг bot (модуль 03A)" }

  if ($sHb) { OK "Сервер — копия, главная версия и бэкап (локальный git) — на компьютере; синк отмечается на сервере" }
  elseif ((G 'BACKUP') -eq 'yes') { WARN "На сервере снапшоты старой модели — в kit 2.1 главная копия на компьютере"; AgentDo "переведи на связку: brain-link adopt (снапшоты на сервере будут выключены, не удалены)" }
  else { WARN "Синк с компьютера ещё не работал"; AgentDo "включи связку: brain-link init или adopt, затем schedule" }
  switch (G 'UFW') { 'yes' { OK "Файрвол включён" } 'unknown' { INFO "Файрвол отсюда не виден (вход под brain) — проверит блок 8" } 'none' { WARN "На сервере нет ufw (похоже на контейнерный VPS) — закрой порты в панели хостера (модуль 08)" } default { WARN "Файрвол выключен — его включает brain-link harden (модуль 05)" } }

  # --- сверка с definition of done ---
  $sSk = ToInt (G 'SKILLSN')
  if ($sSk -ge 5) { OK "Скиллы на сервере: $sSk — бот видит команду" }
  else { BAD "На сервере нет скиллов ($sSk) — бот видит память, но не умеет ей пользоваться"; AgentDo "скиллы едут синком из ~/.claude/skills в /home/brain/.claude/skills — проверь brain-link status" }

  if ((G 'WHITELIST') -eq 'yes') { OK "Белый список включён — бот отвечает только владельцу" }
  else { BAD "У бота НЕТ белого списка — любой посторонний тратит твою подписку"; AgentDo "поставь стандартного бота brain-link (шаг bot): он отвечает только по OWNER_ID из USER_ID" }

  # автокоммиты в kit 2.1 живут на компьютере (блок 3); на сервере — только старая модель
  if (-not $sHb) {
    if ((G 'AUTOCOMMIT') -eq 'yes') { OK "Автокоммиты мозга на сервере настроены (старая модель)" }
    else { INFO "Автокоммитов на сервере нет — в kit 2.1 история правок живёт в git на компьютере" }
  }

  if ((G 'BRIEF') -eq 'yes') { OK "Утренний брифинг стоит в расписании" }
  else { WARN "Утреннего брифинга нет — это заодно проверка, что связка cron + бот + память жива"; AgentDo "поставь утренний брифинг по расписанию (SETUP_MORNING_BRIEF)" }

  if ((G 'TEAMKIT') -eq 'yes') { OK "IT-команда на сервере есть (точка входа — cto)" }
  else { WARN "team-kit не установлен"; AgentDo "поставь team-kit на сервер, точка входа — cto" }
}

# ------------------------------------------------------------ 6. Живые проверки
H1 "6. Живые проверки"
$EngineOk = $false; $BridgeOk = $false

$EngineProbe = @'
CL=/usr/local/lib/brain-bot/claude/bin/claude
if [ "$(id -u)" != 0 ]; then echo "NOT_ROOT"; exit 0; fi
if [ -s /etc/brain-bot/credentials/claude_token ]; then
  # токен не в argv: файл открывает root как stdin, sh -c читает его в переменную и отдаёт claude окружением
  # kit 2.1 (RT-11b): настоящий токен получает ТОЛЬКО root-копия claude бота (root, sha256 из claude.sha256
  # сходится) и только от brainbot. claude владельца в /home/brain/.local/bin принадлежит brain: подменённая
  # обёртка забрала бы токен — ему токен не отдаём никогда.
  SUM=$(awk '{print $1; exit}' /usr/local/lib/brain-bot/claude.sha256 2>/dev/null)
  if [ ! -f "$CL" ] || [ -L "$CL" ] || [ "$(stat -c '%U' "$CL" 2>/dev/null)" != root ] || [ -z "$SUM" ] \
     || [ "$(sha256sum "$CL" 2>/dev/null | awk '{print $1}')" != "$SUM" ]; then echo "NO_BOT_CLAUDE"; exit 0; fi
  RU=brainbot; CCD=/var/lib/brain-bot/claude-config
  if ! id brainbot >/dev/null 2>&1 || [ ! -d "$CCD" ]; then echo "NO_BOT_CLAUDE"; exit 0; fi
  ST=/etc/brain-bot/claude_settings.json; [ -f "$ST" ] || ST=
  cd /tmp && runuser -u "$RU" -- env -i HOME=/home/brain LANG=C.UTF-8 PATH=/usr/local/lib/brain-bot/claude/bin:/usr/local/bin:/usr/bin:/bin \
    CLAUDE_CONFIG_DIR="$CCD" sh -c 'IFS= read -r CLAUDE_CODE_OAUTH_TOKEN; export CLAUDE_CODE_OAUTH_TOKEN
      if [ -n "$2" ]; then exec timeout 80 "$1" -p "Ответь ровно одним словом: живой" --settings "$2" </dev/null
      else exec timeout 80 "$1" -p "Ответь ровно одним словом: живой" </dev/null; fi' sh "$CL" "$ST" \
    < /etc/brain-bot/credentials/claude_token 2>&1 | tail -3
  exit 0
fi
ENVF=$(grep -rlE "^CLAUDE_CODE_OAUTH_TOKEN=" /home/brain/.config/ 2>/dev/null | head -1)
if [ -z "$ENVF" ]; then echo "NO_ENV_FILE"; exit 0; fi
sudo -u brain -i bash -lc "unset ANTHROPIC_API_KEY; set -a; . '$ENVF'; set +a; cd /home/brain 2>/dev/null; timeout 80 claude -p 'Ответь ровно одним словом: живой'" 2>&1 | tail -3
'@

if ($SrvOk -and (G 'CLAUDE') -eq 'yes') {
  Write-Host "  .      спрашиваю мозг на сервере (до 90 сек)..." -ForegroundColor DarkGray
  $ans = ($EngineProbe | & ssh @SshArgs "$SrvUser@$SrvIp" $RemoteBash 2>$null) -join "`n"
  if ($ans -match 'NOT_ROOT') { INFO "После lockdown вход root закрыт — мозг проверь из Telegram: напиши боту /status и любой вопрос" }
  elseif ($ans -match 'NO_BOT_CLAUDE') {
    WARN "У бота нет своей root-копии Claude Code (или контрольная сумма не сходится) — токен ей не отдаю"
    Manual "Поставь копию для бота: brain_link.py claude (или на сервере: sudo brain-admin update-claude)"
  }
  elseif ($ans -match 'жив') { OK "МОЗГ НА СЕРВЕРЕ ДУМАЕТ и отвечает из твоей подписки"; $EngineOk = $true }
  elseif ($ans -match 'credit|balance|login|auth|subscription|invalid') {
    BAD "Мозг на сервере не пускает по подписке — токен протух или не тот"
    Manual "Перевыпусти токен подписки: запусти САМА brain_link.py put-token claude"
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

# ------------------------------------------ 8. Связка компьютер ↔ сервер (kit 2.1)
# Отдельный счёт, как у блока 7: ветку A/B/ГОТОВО не меняет. Серверные точки — из того же
# ssh-запроса блока 5 (поля LK_*).
H1 "8. Связка компьютер ↔ сервер (kit 2.1)"
$script:LkYes=0; $script:LkPart=0; $script:LkNo=0; $script:LkRows=@(); $script:LkFix=@()
function LK($v, $title, $detail, $fix) {
  $line = "$title — $detail"
  if ($v -eq 'есть')         { $script:LkYes++;  Write-Host "  [OK]   $line" -ForegroundColor Green;  $script:Lines += "- 🟢 $line" }
  elseif ($v -eq 'частично') { $script:LkPart++; Write-Host "  [!]    $line" -ForegroundColor Yellow; $script:Lines += "- 🟡 $line" }
  else                       { $script:LkNo++;   Write-Host "  [X]    $line" -ForegroundColor Red;    $script:Lines += "- 🔴 $line" }
  $script:LkRows += "| $title | $v | $detail |"
  if ($v -ne 'есть' -and $fix) { $script:LkFix += "${title}: $fix" }
}

# 8.1 расписание синка
$lkTask = Get-ScheduledTask -TaskName 'Ikigai brain-sync' -ErrorAction SilentlyContinue
if ($lkTask) {
  if ($lkTask.Settings.StartWhenAvailable) { LK 'есть' "Расписание синка" "задача Планировщика «Ikigai brain-sync», StartWhenAvailable включён" }
  else { LK 'частично' "Расписание синка" "задача есть, но без StartWhenAvailable — пропуск после сна не догонит" "brain-link schedule --replace" }
} else { LK 'нет' "Расписание синка" "задачи «Ikigai brain-sync» нет" "brain-link schedule" }

# 8.2 синк свежий и 8.3 нет паузы
$stPath = Join-Path $CfgBrain "sync_status.json"
if (Test-Path $stPath) {
  $st = $null; try { $st = (ReadUtf8 $stPath) | ConvertFrom-Json } catch { $st = $null }
  $lastOk = 0.0; if ($st -and $st.last_success_epoch) { $lastOk = [double]$st.last_success_epoch }
  $fails = 0; if ($st -and $st.consecutive_failures) { $fails = [int]$st.consecutive_failures }
  $nowEpoch = [double][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  $age = [int]($nowEpoch - $lastOk)
  if ($lastOk -gt 0 -and $age -le 900 -and $fails -eq 0) { LK 'есть' "Синк свежий" ("последний успешный синк " + [int]($age/60) + " мин назад") }
  elseif ($lastOk -gt 0 -and $age -le 86400) { LK 'частично' "Синк свежий" ("последний успешный синк " + [int]($age/60) + " мин назад, ошибок подряд: $fails") "brain-link status — там причина; модуль 08" }
  else { LK 'нет' "Синк свежий" "успешного синка нет больше суток (ошибок подряд: $fails)" "brain-link status, затем модуль 08" }
} else { LK 'нет' "Синк свежий" "синк ещё ни разу не запускался" "brain-link init / adopt, затем schedule" }
if (Test-Path (Join-Path $CfgBrain "sync.pause")) { LK 'частично' "Синк не на паузе" "стоит пауза (sync.pause)" "brain-link resume, когда закончишь массовую правку" }
else { LK 'есть' "Синк не на паузе" "паузы нет" }

# 8.4 ключ сервера закреплён
if ((Test-Path $KnownHosts) -and (Get-Item $KnownHosts).Length -gt 0) { LK 'есть' "Ключ сервера закреплён" ".config\brain\known_hosts" }
else { LK 'нет' "Ключ сервера закреплён" "нет .config\brain\known_hosts — подмену сервера никто не заметит" "brain-link keys" }

# 8.5 нет пароля в скриптах и выключенной проверки ключа сервера (шаблон собран по частям,
# чтобы этот файл сам не попадал под поиск)
# и через «=», и через пробел (как в ~/.ssh/config), с кавычками и без
$patPass = 'ssh' + 'pass'; $patNoHost = 'StrictHostKeyChecking(\s*=\s*|\s+)["'']?' + 'no'
$lkPat = "$patPass|$patNoHost"
$lkFiles = @()
foreach ($f in @((Join-Path $HOME ".ssh\config"))) { if (Test-Path $f) { $lkFiles += Get-Item $f } }
$lkFiles += @(Get-ChildItem $CfgBrain -Filter *.ps1 -File -ErrorAction SilentlyContinue)
if ($brain) {
  $lkFiles += @(Get-ChildItem $brain -Recurse -Depth 4 -File -Include *.ps1,*.py,*.sh,*.bat,*.cmd -ErrorAction SilentlyContinue |
               Where-Object { $_.FullName -notmatch '\\(\.git|node_modules)\\' } | Select-Object -First 500)
}
$lkHits = @($lkFiles | Where-Object { Select-String -Path $_.FullName -Pattern $lkPat -Quiet -ErrorAction SilentlyContinue } | Select-Object -First 5 | ForEach-Object { $_.Name })
foreach ($t in @(Get-ScheduledTask -ErrorAction SilentlyContinue)) {
  foreach ($act in @($t.Actions)) { if (("" + $act.Execute + " " + $act.Arguments) -match $lkPat) { $lkHits += ("задача " + $t.TaskName) } }
}
if ($lkHits.Count -eq 0) { LK 'есть' "Вход без пароля в скриптах" "пароль через $patPass и выключенная проверка ключа сервера не найдены" }
else { LK 'нет' "Вход без пароля в скриптах" ("найдено в: " + ($lkHits -join ', ')) "заменить на вход по ключу и закреплённый known_hosts (brain-link keys); пароль из файлов убрать" }

# 8.6–8.15 — сервер
if ($SrvOk) {
  $lkPriv = (G 'LK_PRIVATE')
  if (-not $lkPriv) { LK 'есть' "Личного на сервере нет" "personal/ private/ secret/ sessions/ не найдены" }
  else { LK 'нет' "Личного на сервере нет" "найдено: $lkPriv" "забрать домой: brain-link adopt --pull-private; удалить на сервере: sudo brain-admin remove-private" }
  switch (G 'UFW') { 'yes' { LK 'есть' "Файрвол" "ufw active" } 'unknown' { LK 'частично' "Файрвол" "отсюда не видно (вход под brain)" "sudo brain-admin status" } 'none' { LK 'частично' "Файрвол" "ufw нет (контейнерный VPS?)" "файрвол в панели хостера, модуль 08" } default { LK 'нет' "Файрвол" "ufw выключен" "brain-link harden" } }
  if ((G 'LK_F2B') -eq 'active') { LK 'есть' "fail2ban" "active" } else { LK 'нет' "fail2ban" (G 'LK_F2B') "brain-link harden" }
  switch (G 'LK_PWAUTH') {
    'no'  { LK 'есть' "Вход только по ключам" "PasswordAuthentication no" }
    'yes' { if ((G 'LK_LOCKDOWN') -eq 'yes') { LK 'нет' "Вход только по ключам" "lockdown включён, а пароль всё ещё принимается" "модуль 08: проверить файлы в /etc/ssh/sshd_config.d" }
            else { LK 'частично' "Вход только по ключам" "пароль ещё принимается — до lockdown так и должно быть" "brain-link lockdown после зелёного verify" } }
    default { LK 'частично' "Вход только по ключам" "не смог проверить" "brain-link verify" }
  }
  # kit 2.1 (RT-11): бот — отдельный пользователь brainbot; под brain токены LoadCredential читает любой процесс brain
  if ((G 'UNIT') -eq 'brain-bot.service' -and (G 'UNITACTIVE') -eq 'yes' -and (G 'UNITUSER') -eq 'brainbot') { LK 'есть' "Бот под brainbot" "brain-bot active, User=brainbot" }
  elseif ((G 'UNIT') -eq 'brain-bot.service' -and (G 'UNITUSER') -eq 'brain') { LK 'нет' "Бот под brainbot" "brain-bot под brain (ранняя установка): его токены читает любой процесс brain" "brain-link bot до lockdown — переведёт на brainbot (после lockdown — VNC-консоль, root: brain-link bot)" }
  elseif ((G 'UNIT') -eq 'brain-bot.service') { LK 'нет' "Бот под brainbot" ("brain-bot: active=" + (G 'UNITACTIVE') + ", User=" + (G 'UNITUSER')) "brain-link bot" }
  else { LK 'нет' "Бот под brainbot" "стандартного brain-bot нет" "brain-link bot" }
  switch (G 'LK_CREDREAD') {
    'no'  { LK 'есть' "brain не читает токены бота" "/etc/brain-bot/credentials и /run/credentials/brain-bot.service закрыты для brain" }
    'yes' { LK 'нет' "brain не читает токены бота" "brain читает токен бота — RT-11" "brain-link bot до lockdown (бот уйдёт под brainbot)" }
    default { LK 'частично' "brain не читает токены бота" "не смог проверить" "brain-link verify, пункт (ж)" }
  }
  $lkCreds = @(((G 'LK_CREDS') -split ';') | Where-Object { $_.Trim() })
  if ($lkCreds.Count -eq 0) { LK 'нет' "Секреты бота 0600 root" "секретов в /etc/brain-bot/credentials нет (или не видно)" "brain-link put-token claude и put-token bot" }
  elseif (@($lkCreds | Where-Object { $_.Trim() -notmatch '^(600|-rw-------) root$' }).Count -gt 0) { LK 'нет' "Секреты бота 0600 root" ("права: " + ($lkCreds -join '; ')) "sudo brain-admin set-token … заново (ставит 0600 root)" }
  else { LK 'есть' "Секреты бота 0600 root" "оба токена 0600 root" }
  if ((G 'APIKEY') -eq 'no') { LK 'есть' "API-ключа нет" "ANTHROPIC_API_KEY на сервере не задан" } else { LK 'нет' "API-ключа нет" "ANTHROPIC_API_KEY найден" "убрать отовсюду (модуль 02, шаг 3)" }
  $lkSkew = [math]::Abs((ToInt (G 'LK_NOW')) - [DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
  if ((G 'LK_NTP') -eq 'yes' -and $lkSkew -lt 60) { LK 'есть' "Часы" "NTP синхронизирован, расхождение ~$lkSkew с" }
  else { LK 'нет' "Часы" ("NTPSynchronized=" + (G 'LK_NTP') + ", расхождение ~$lkSkew с") "на сервере: sudo brain-admin timesync-restart" }
  $lkDisk = ToInt (G 'LK_DISK')
  if ($lkDisk -lt 85) { LK 'есть' "Диск" "занято $lkDisk%" } else { LK 'нет' "Диск" "занято $lkDisk% (порог 85%)" "почистить ~/.cache на сервере, старые журналы: модуль 08" }
} else {
  LK 'нет' "Сервер по ключу" "нет входа по ключу — серверные проверки связки пропущены" "brain-link keys"
}
$lkAll = $script:LkYes + $script:LkPart + $script:LkNo
$lkSum = "Связка kit 2.1: есть $($script:LkYes) · частично $($script:LkPart) · нет $($script:LkNo) → $($script:LkYes) из $lkAll"
Write-Host ""; Write-Host "  $lkSum"; $script:Lines += ""; $script:Lines += $lkSum
INFO "Живьём (бот → inbox, правка → сервер, «красная команда») связку проверяет brain-link verify"

# ------------------------------------------------------------------- ВЕРДИКТ
$total = $script:OkN + $script:WarnN + $script:FailN
$pct = 0; if ($total -gt 0) { $pct = [int]($script:OkN * 100 / $total) }

if ((IsPlaceholder $SrvIp) -and -not $SrvOk) { $branch="A"; $branchTxt="Сервера пока нет. Твой путь: заказать VPS → brain-link (detect → … → lockdown)." }
elseif ($EngineOk -and $BridgeOk -and $script:FailN -eq 0) { $branch="ГОТОВО"; $branchTxt="Система собрана: мозг на сервере думает, бот с ним соединён." }
else { $branch="B"; $branchTxt="Сервер есть, но собран не до конца. Твой путь: закрыть красные пункты выше." }

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ("ИТОГ   OK $($script:OkN)   ! $($script:WarnN)   X $($script:FailN)      готовность ~$pct%") -ForegroundColor White
Write-Host ("ВЕТКА $branch — $branchTxt") -ForegroundColor White
if ($brain) { Write-Host ("ЭТАЛОН 13–23   OK есть $($script:PtYes)   ! частично $($script:PtPart)   X нет $($script:PtNo)   - не применимо $($script:PtNa)   → $($script:PtYes) из $ptAppl применимых") -ForegroundColor White }
else { Write-Host "ЭТАЛОН 13–23   не проверено — нет папки мозга" -ForegroundColor White }
Write-Host ("СВЯЗКА kit 2.1   OK $($script:LkYes)   ! $($script:LkPart)   X $($script:LkNo)   → $($script:LkYes) из $lkAll") -ForegroundColor White
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
$script:Lines += "- Связка компьютер ↔ сервер (kit 2.1): есть $($script:LkYes) · частично $($script:LkPart) · нет $($script:LkNo) → **$($script:LkYes) из $lkAll**"
$script:Lines += "`n### Связка kit 2.1`n"
$script:Lines += "| Точка | Вердикт | Что видно |"
$script:Lines += "|---|---|---|"
$script:Lines += $script:LkRows
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
$p += "Ты мой технический помощник. Я участница AI-Потока. Цель (kit 2.1): компьютер — мастерская,"
$p += "сервер — база. Память и скиллы правлю на компьютере, сервер держит их копию и моего"
$p += "Telegram-бота 24/7, бот думает из моей ПОДПИСКИ, а не по API-ключу. Ставит всё скилл brain-link."
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
if ($script:LkFix.Count -gt 0) {
  $p += "СВЯЗКА КОМПЬЮТЕР ↔ СЕРВЕР (kit 2.1) — чинит скилл brain-link, по шагам:"
  $i=1; foreach ($t in $script:LkFix) { $p += "$i. $t"; $i++ }
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
$p += "- Токены на сервер передаю я сама шагом brain-link put-token (скрытый ввод); на сервере они"
$p += "  живут в /etc/brain-bot/credentials (root, 600). Не в коде, не в git, не в чате, не в файле доступа."
$p += "- Личное (здоровье, семья, финансы) на сервер НЕ переносим."
$p += "- Команду brain-link put-token claude (внутри — claude setup-token) я выполняю САМА в своём"
$p += "  терминале — ты её не запускаешь"
$p += "  и её вывод не читаешь."
$p += "- Ничего необратимого без моего явного «да»."
$p += "- Инструкции бери из кита novoselie-server-kit в репозитории"
$p += "  https://github.com/alexandrkuznetsovofficial-web/ikigai-ai-skills"
$p += "  и скилла brain-link (detect → keys → harden → claude → put-token → init/adopt → schedule →"
$p += "  bot → verify → lockdown); модули: 02 — сервер и Claude, 03A — бот, 04 — кто чем владеет,"
$p += "  05 — безопасность, 06 — приёмка, 08 — если не взлетело."
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
