# win_askpass.ps1 — лаборатория: keys кладёт ключ по паролю через SSH_ASKPASS на настоящем Windows-ssh.
# Windows PowerShell 5.1. Файл в UTF-8 с BOM (CRLF даёт .gitattributes). Только для GitHub Actions.
# «Сервер участника» — локальный OpenSSH Server Windows на 127.0.0.1:22, локальный пользователь root с паролем.
# Проверяет: (A) встроенный C:\Windows\System32\OpenSSH\ssh.exe запускает askpass.cmd при SSH_ASKPASS_REQUIRE=force
# и получает пароль (в т.ч. временная папка с пробелом и кириллицей); (B) неверный пароль → отказ, одна попытка;
# (C) настоящий `brain_link.py keys`: неверный пароль → rc 2 password_rejected, верный → rc 0 key_installed=password,
# повторно → вход по ключу. Пароль не должен встречаться ни в одном выводе.
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Pass = 0; $Fail = 0
function OK($t){ $script:Pass++; Write-Host "PASS $t" }
function BAD($t){ $script:Fail++; Write-Host "FAIL $t" }
function WriteUtf8NoBom($path, $text) { [IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false))) }
function LastJson($lines) {
  $j = $null
  foreach ($l in @($lines)) { $s = "$l".Trim(); if ($s.StartsWith("{")) { try { $j = $s | ConvertFrom-Json } catch {} } }
  return $j
}

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = (Resolve-Path (Join-Path $Here "..\..")).Path
$Work = if ($env:WORK) { $env:WORK } else { Join-Path $env:RUNNER_TEMP "brain-lab" }
New-Item -ItemType Directory -Force -Path $Work | Out-Null
$Py = (Get-Command python -ErrorAction SilentlyContinue).Source
$env:PYTHONIOENCODING = "utf-8"
$SshExe = Join-Path $env:SystemRoot "System32\OpenSSH\ssh.exe"
Write-Host "python: $Py"
if (Test-Path $SshExe) { $ErrorActionPreference = "SilentlyContinue"; Write-Host ("ssh клиента: " + ((& $SshExe -V 2>&1 | ForEach-Object { "$_" }) -join " ")); $ErrorActionPreference = "Continue" } else { Write-Host "встроенного ssh.exe нет" }
Write-Host ("ОС: " + (Get-CimInstance Win32_OperatingSystem).Caption)

# ---------------------------------------------------------------- 1. OpenSSH Server
$svc = Get-Service sshd -ErrorAction SilentlyContinue
if (-not $svc) {
  Write-Host "sshd нет — Add-WindowsCapability OpenSSH.Server"
  try { Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 -ErrorAction Stop | Out-Null } catch { Write-Host "   Add-WindowsCapability: $_" }
  $svc = Get-Service sshd -ErrorAction SilentlyContinue
}
if (-not $svc) {
  Write-Host "запасной путь: Win32-OpenSSH zip с GitHub (только раннер)"
  try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $zip = Join-Path $Work "OpenSSH-Win64.zip"
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/PowerShell/Win32-OpenSSH/releases/latest/download/OpenSSH-Win64.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath "C:\Program Files" -Force
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Program Files\OpenSSH-Win64\install-sshd.ps1" | Out-Null
  } catch { Write-Host "   zip: $_" }
  $svc = Get-Service sshd -ErrorAction SilentlyContinue
}
if (-not $svc) { BAD "OpenSSH Server не поставился — дальше без сервера смысла нет"; Write-Host "win-askpass: $Pass PASS, $Fail FAIL"; exit 1 }
Start-Service sshd
Start-Sleep -Seconds 2
# образ раннера ограничивает вход (AllowGroups/AllowUsers) — для «сервера участника» снимаем, иначе root «invalid user»
$sshdCfg = "C:\ProgramData\ssh\sshd_config"
if (Test-Path $sshdCfg) {
  $lines = Get-Content $sshdCfg
  $lines | Where-Object { $_ -match '^\s*(AllowGroups|AllowUsers|DenyGroups|DenyUsers|PasswordAuthentication)\b' } | ForEach-Object { Write-Host "   sshd_config раннера: $_" }
  $lines = $lines | ForEach-Object { if ($_ -match '^\s*(AllowGroups|AllowUsers|DenyGroups|DenyUsers|PasswordAuthentication)\b') { "# lab: $_" } else { $_ } }
  Set-Content -Path $sshdCfg -Value $lines -Encoding ASCII
  Restart-Service sshd
  Start-Sleep -Seconds 2
}
Write-Host ("8dot3 C: " + ((fsutil 8dot3name query C: 2>&1 | Out-String) -replace "`r?`n", " "))
$sshdExe = (Get-CimInstance Win32_Service -Filter "Name='sshd'").PathName
Write-Host "sshd: $sshdExe"
$up = $false
for ($i=0; $i -lt 30; $i++) { if (Test-NetConnection 127.0.0.1 -Port 22 -InformationLevel Quiet -WarningAction SilentlyContinue) { $up = $true; break }; Start-Sleep 1 }
if ($up) { OK "sshd Windows слушает 127.0.0.1:22" } else { BAD "sshd не слушает 22"; Write-Host "win-askpass: $Pass PASS, $Fail FAIL"; exit 1 }

# ---------------------------------------------------------------- 2. пользователь root с паролем (не администратор)
$chars = [char[]]'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
$rnd = -join (1..18 | ForEach-Object { $chars | Get-Random })
$Pw = "Lab%!^&@-Aa9" + $rnd
$Wrong = "Wrong%!-Aa9-nope-" + (Get-Random)
$sec = ConvertTo-SecureString $Pw -AsPlainText -Force
if (Get-LocalUser -Name root -ErrorAction SilentlyContinue) { Set-LocalUser -Name root -Password $sec }
else { New-LocalUser -Name root -Password $sec -PasswordNeverExpires -AccountNeverExpires -Description "brain-link lab" | Out-Null }
if (Get-LocalUser -Name root -ErrorAction SilentlyContinue) { OK "локальный пользователь root с паролем создан" } else { BAD "пользователь root не создан" }

$Cfg = Join-Path $Work "cfg-askpass"
New-Item -ItemType Directory -Force -Path $Cfg | Out-Null
$env:BRAIN_CONFIG_DIR = $Cfg
$Access = Join-Path $Cfg "server_access"
function SetAccess($pw) {
  $t = "SERVER_IP=127.0.0.1`r`nSERVER_USER=root`r`nSERVER_PORT=22`r`nUSER_ID=111111111`r`n"
  if ($pw) { $t += "PASSWORD=$pw`r`n" }
  WriteUtf8NoBom $Access $t
}
function NoLeak($text, $pw, $label) {
  if ("$text".Contains($pw)) { BAD "${label}: пароль в выводе" } else { OK "${label}: пароля в выводе нет" }
}

# ---------------------------------------------------------------- 3. (A/B) ssh.exe + askpass.cmd напрямую
# контроль: пароль локального root верный (Windows сама проверяет, без ssh)
try {
  Add-Type -AssemblyName System.DirectoryServices.AccountManagement
  $pc = New-Object System.DirectoryServices.AccountManagement.PrincipalContext('Machine')
  if ($pc.ValidateCredentials('root', $Pw)) { OK "контроль: пароль root верный (ValidateCredentials)" } else { BAD "контроль: ValidateCredentials отверг пароль root" }
} catch { Write-Host "   ValidateCredentials: $_" }
function SshdEvents() {
  try { Get-WinEvent -LogName 'OpenSSH/Operational' -MaxEvents 12 -ErrorAction Stop | Sort-Object TimeCreated | ForEach-Object { Write-Host ("   sshd-event: " + ("$($_.Message)" -replace "`r?`n", " ")) } }
  catch { Write-Host "   sshd-event: журнал недоступен ($_)" }
}
function Probe($label, $expect, [string[]]$extra) {
  $o = & $Py (Join-Path $Here "askpass_probe.py") --user root --port 22 --expect $expect @extra 2>&1
  $rc = $LASTEXITCODE; $o | ForEach-Object { Write-Host "   $_" }
  NoLeak ($o | Out-String) $Pw "$label (верный пароль в выводе)"
  return $rc
}
SetAccess $Pw
if ((Probe "helper" ok @('--helper-only')) -eq 0) { OK "askpass.cmd сам по себе отдаёт ровно пароль (длина и sha256 совпали)" } else { BAD "askpass.cmd отдаёт не то, что в PASSWORD" }
if ((Probe "probe" ok @()) -eq 0) { OK "ssh.exe 9.5 запустил askpass.cmd (REQUIRE=force, -F none) и вошёл по паролю" } else { BAD "ssh.exe + askpass.cmd: вход по паролю не прошёл"; SshdEvents }

$oldTemp = $env:TEMP; $oldTmp = $env:TMP
$variants = @(
  @{ name = "TEMP с пробелом"; dir = (Join-Path $Work "Temp With Space"); extra = @() },
  @{ name = "TEMP с кириллицей и пробелом"; dir = (Join-Path $env:LOCALAPPDATA "Анна Ли\Temp"); extra = @() },
  @{ name = "TEMP с кириллицей + короткое имя 8.3 в SSH_ASKPASS (диск C:)"; dir = (Join-Path $env:LOCALAPPDATA "Анна Ли\Temp"); extra = @('--shortpath') }
)
foreach ($v in $variants) {
  New-Item -ItemType Directory -Force -Path $v.dir | Out-Null
  $env:TEMP = $v.dir; $env:TMP = $v.dir
  if ((Probe $v.name ok $v.extra) -eq 0) { OK "askpass.cmd: $($v.name) — работает" } else { BAD "askpass.cmd: $($v.name) — не сработал" }
  $env:TEMP = $oldTemp; $env:TMP = $oldTmp
}

SetAccess $Wrong
$o = & $Py (Join-Path $Here "askpass_probe.py") --user root --port 22 --expect rejected 2>&1
$rc = $LASTEXITCODE; $o | ForEach-Object { Write-Host "   $_" }
if ($rc -eq 0) { OK "неверный пароль через askpass.cmd → отказ (Permission denied)" } else { BAD "неверный пароль: не тот результат" }
NoLeak ($o | Out-String) $Wrong "probe неверный"

# ---------------------------------------------------------------- 4. (C) настоящий keys
# удалённая команда keys — POSIX sh (mkdir -p ~/.ssh …): на «сервере» Windows оболочка — bash из Git for Windows
$GitBash = @("C:\Program Files\Git\bin\bash.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $GitBash) { BAD "нет Git bash для оболочки sshd"; Write-Host "win-askpass: $Pass PASS, $Fail FAIL"; exit 1 }
New-Item -Path "HKLM:\SOFTWARE\OpenSSH" -Force | Out-Null
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell -Value $GitBash -PropertyType String -Force | Out-Null
Restart-Service sshd
Start-Sleep -Seconds 2
$adminKey = Join-Path $env:USERPROFILE ".ssh\id_ed25519"
$rootAk = "C:\Users\root\.ssh\authorized_keys"
function AkCount() {
  if (-not (Test-Path $rootAk) -or -not (Test-Path "$adminKey.pub")) { return 0 }
  $k = (Get-Content "$adminKey.pub" -Raw).Trim()
  return @(Get-Content $rootAk | Where-Object { $_.Trim() -eq $k }).Count
}
function Keys($label) {
  $o = & $Py (Join-Path $Here "drive_link.py") '--' keys 2>&1
  $script:KeysRc = $LASTEXITCODE
  $script:KeysOut = ($o | Out-String)
  $script:KeysJ = LastJson $o
  if ($script:KeysJ) { Write-Host ("   [$label] rc=$($script:KeysRc) human: " + "$($script:KeysJ.human)".Substring(0, [Math]::Min(300, "$($script:KeysJ.human)".Length))); Write-Host "   key_install=$($script:KeysJ.key_install) key_installed=$($script:KeysJ.key_installed) host_key_check=$($script:KeysJ.host_key_check)" }
  else { Write-Host "   [$label] rc=$($script:KeysRc)"; $o | Select-Object -Last 10 | ForEach-Object { Write-Host "   $_" } }
}

SetAccess $Wrong
Keys "неверный"
if ($KeysRc -eq 2 -and $KeysJ.key_install -eq "password_rejected") { OK "keys: неверный пароль → rc 2, password_rejected" } else { BAD "keys с неверным паролем: rc=$KeysRc key_install=$($KeysJ.key_install)" }
if ((AkCount) -eq 0) { OK "неверный пароль: ключ на «сервер» не попал" } else { BAD "неверный пароль, а ключ лёг" }
NoLeak $KeysOut $Wrong "keys неверный"

SetAccess $Pw
Keys "верный"
if ($KeysRc -eq 0 -and $KeysJ.key_installed -eq "password") { OK "keys: верный пароль → rc 0, key_installed=password" } else { BAD "keys с верным паролем: rc=$KeysRc key_installed=$($KeysJ.key_installed) key_install=$($KeysJ.key_install)" }
if ($KeysRc -ne 0) { SshdEvents }
if (-not ((Get-Content $Access -Raw) -match '(?m)^PASSWORD=')) { OK "строка PASSWORD убрана из файла доступа" } else { BAD "строка PASSWORD осталась в файле доступа" }
if ((AkCount) -eq 1) { OK "admin-ключ в authorized_keys «сервера» ровно один раз" } else { BAD "admin-ключ в authorized_keys: $(AkCount) раз" }
NoLeak $KeysOut $Pw "keys верный"

Keys "повторно"
if ($KeysRc -eq 0 -and -not $KeysJ.key_installed) { OK "keys повторно: вход по ключу, без пароля" } else { BAD "keys повторно: rc=$KeysRc key_installed=$($KeysJ.key_installed)" }
if ((AkCount) -eq 1) { OK "повторный keys ключ не задвоил" } else { BAD "ключ задвоен: $(AkCount)" }

# keys при TEMP с кириллицей и пробелом («C:\Users\Анна Ли»): ключ снимаем с «сервера», пароль снова в файле доступа.
# Win32-OpenSSH не запускает помощник по не-ASCII пути — keys даёт ему короткое имя 8.3 (диск C: с 8.3).
# Ждём rc 0 key_installed=password; без обхода было бы askpass_failed (но не «пароль не подошёл»).
if (Test-Path $rootAk) { Set-Content -Path $rootAk -Value "" -Encoding ASCII }
SetAccess $Pw
$env:TEMP = (Join-Path $env:LOCALAPPDATA "Анна Ли\Temp"); $env:TMP = $env:TEMP
Keys "кириллица в TEMP"
$env:TEMP = $oldTemp; $env:TMP = $oldTmp
if ($KeysRc -eq 0 -and $KeysJ.key_installed -eq "password") { OK "keys при кириллице и пробеле в TEMP: rc 0, key_installed=password" }
elseif ($KeysJ.key_install -eq "askpass_failed") { BAD "keys при кириллице в TEMP: askpass_failed (обход 8.3 не сработал, но честно не «неверный пароль»)" }
else { BAD "keys при кириллице в TEMP: rc=$KeysRc key_install=$($KeysJ.key_install)" }
NoLeak $KeysOut $Pw "keys кириллица"

# журнал sshd (без пароля) — в артефакт
$sshdLog = "C:\ProgramData\ssh\logs\sshd.log"
if (Test-Path $sshdLog) { Copy-Item $sshdLog (Join-Path $Work "win_sshd.log") -Force }
Remove-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell -ErrorAction SilentlyContinue

Write-Host "----"
Write-Host "win-askpass: $Pass PASS, $Fail FAIL"
if ($Fail -gt 0) { exit 1 } else { exit 0 }
