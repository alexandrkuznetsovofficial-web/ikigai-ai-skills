# win_integration.ps1 — расписание brain-sync на Windows через настоящий schedule + install_task.ps1 (лаборатория).
# Windows PowerShell 5.1 (powershell.exe). Файл в UTF-8 с BOM и CRLF — иначе PS 5.1 читает кириллицу как cp1252.
# Транспорт local передаётся штатным хуком лаборатории: BRAIN_SYNC_TRANSPORT=local:<папка> перед schedule —
# brain_link.py передаёт его в install_task.ps1 (-Transport), задача сама зовёт brain_sync.py --transport.
# Задача Планировщика НЕ наследует окружение этого скрипта, поэтому профиль и служебные файлы — в штатных
# местах настоящего %USERPROFILE% раннера (раннер одноразовый); рабочая папка — путь с пробелом и кириллицей.
# Проверяет: рендер шаблона, schedule (Register -> Start -> sync_status.json), StartWhenAvailable/батарея/IgnoreNew,
# повторный Start, Unregister; probe.ps1 (ssh/ssh_keygen/python_version); audit.ps1 без сервера. Только для Actions.
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Pass = 0; $Fail = 0
function OK($t){ $script:Pass++; Write-Host "PASS $t" }
function BAD($t){ $script:Fail++; Write-Host "FAIL $t" }
function WriteUtf8NoBom($path, $text) { [IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false))) }

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = (Resolve-Path (Join-Path $Here "..\..")).Path
$Scripts = Join-Path $Repo "brain-link\scripts"
$Work = if ($env:WORK) { $env:WORK } else { Join-Path $env:RUNNER_TEMP "brain-lab" }
$UP = $env:USERPROFILE
# рабочая папка с пробелом и кириллицей (требование ТЗ)
$WS = Join-Path $Work "Мой мозг\SecondBrain"
$Srv = Join-Path $Work "server"
$Cfg = Join-Path $UP ".config\brain"
$Skills = Join-Path $UP ".claude\skills"
$EnvJson = Join-Path $UP ".claude\ikigai_env.json"
$Py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Py) { $Py = (Get-Command py -ErrorAction SilentlyContinue).Source }
Write-Host "python: $Py; USERPROFILE: $UP"
Remove-Item Env:BRAIN_CONFIG_DIR -ErrorAction SilentlyContinue
Remove-Item Env:BRAIN_IKIGAI_ENV -ErrorAction SilentlyContinue
foreach ($d in @("$WS\memory\inbox", "$WS\memory\dialogues", "$Srv\memory\inbox", "$Srv\memory\dialogues", $Cfg, "$Skills\brain-link")) {
  New-Item -ItemType Directory -Force -Path $d | Out-Null
}
WriteUtf8NoBom (Join-Path $WS "CLAUDE.md") "# CLAUDE`r`n"
WriteUtf8NoBom (Join-Path $WS "memory\MEMORY.md") ("# MEMORY win " + (Get-Date -Format o) + "`r`n")
WriteUtf8NoBom (Join-Path $Skills "brain-link\SKILL.md") "skill`r`n"
WriteUtf8NoBom $EnvJson (@{ workspace = $WS; workspace_win = $WS } | ConvertTo-Json -Compress)
$env:BRAIN_SYNC_TRANSPORT = "local:" + $Srv
$env:PYTHONIOENCODING = "utf-8"

function LastJson($lines) {
  $j = $null
  foreach ($l in @($lines)) { $s = "$l".Trim(); if ($s.StartsWith("{")) { try { $j = $s | ConvertFrom-Json } catch {} } }
  return $j
}

# 1. render_ps1 из модуля — настоящий шаблон читается, BOM + CRLF
& $Py -c "import sys; sys.path.insert(0, sys.argv[1]); import brain_link; b = brain_link.render_ps1(); assert b[:3] == b'\xef\xbb\xbf', 'no BOM'; assert b'\r\n' in b, 'no CRLF'; print('render_ps1 ok', len(b))" $Scripts
if ($LASTEXITCODE -eq 0) { OK "настоящий шаблон install_task.ps1 рендерится (BOM+CRLF)" } else { BAD "render_ps1 упал" }

# 2. init (local) настоящим brain_sync
$out = & $Py (Join-Path $Here "drive_link.py") '--' init --yes --root $WS --skills-dir $Skills --transport ("local:" + $Srv) 2>&1
$rc = $LASTEXITCODE
if ($rc -eq 0) { OK "init (local) прошёл" } else { BAD "init (local) не прошёл (rc=$rc)"; $out | Select-Object -Last 5 | ForEach-Object { Write-Host "   $_" } }
if (Test-Path (Join-Path $Srv "memory\MEMORY.md")) { OK "init выгрузил MEMORY.md в «сервер»" } else { BAD "MEMORY.md в «сервер» не доехал" }

# 3. schedule: НАСТОЯЩИЙ brain_link.py → render_ps1 → install_task.ps1 -Transport local:… → Register + Start
$TaskName = "Ikigai brain-sync"
schtasks /Query /TN $TaskName 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { schtasks /Delete /TN $TaskName /F | Out-Null }
$out = & $Py (Join-Path $Here "drive_link.py") '--' schedule --replace --wait 180 2>&1
$rc = $LASTEXITCODE
$j = LastJson $out
if ($j) { Write-Host ("   human: " + "$($j.human)".Substring(0, [Math]::Min(300, "$($j.human)".Length))); Write-Host "   lab_transport: $($j.lab_transport)"; Write-Host "   task_output: $($j.task_output)" }
else { $out | Select-Object -Last 8 | ForEach-Object { Write-Host "   $_" } }
if ($rc -eq 0) { OK "schedule: задача Планировщика встала, пробный синк прошёл" } else { BAD "schedule не прошёл (rc=$rc)" }

# 4. поля задачи: StartWhenAvailable, работа от батареи, IgnoreNew, транспорт в аргументах
try {
  $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  if ($t.Settings.StartWhenAvailable) { OK "StartWhenAvailable=true" } else { BAD "StartWhenAvailable выключен" }
  if (-not $t.Settings.DisallowStartIfOnBatteries) { OK "запуск от батареи разрешён" } else { BAD "запуск от батареи запрещён" }
  if ("$($t.Settings.MultipleInstances)" -eq "IgnoreNew") { OK "MultipleInstances=IgnoreNew" } else { BAD "MultipleInstances=$($t.Settings.MultipleInstances)" }
  $args0 = "$($t.Actions[0].Arguments)"
  Write-Host "   action: $($t.Actions[0].Execute) $args0"
  if ($args0 -like "*--transport*local:*") { OK "в задаче транспорт local (--transport)" } else { BAD "в задаче нет --transport local" }
  if ("$($t.Actions[0].Execute)" -like "*pythonw.exe") { OK "задача идёт через pythonw.exe (без окна)" } else { BAD "задача не через pythonw.exe: $($t.Actions[0].Execute)" }
} catch { BAD "задача не зарегистрирована: $_" }

# 5. правка памяти → Start → ждём обновления sync_status.json до 3 минут
$statusFile = Join-Path $Cfg "sync_status.json"
WriteUtf8NoBom (Join-Path $WS "memory\MEMORY.md") ("# MEMORY win restart " + (Get-Date -Format o) + "`r`n")
$before = if (Test-Path $statusFile) { (Get-Item $statusFile).LastWriteTimeUtc.Ticks } else { 0 }
Start-Sleep -Seconds 1
Start-ScheduledTask -TaskName $TaskName
$updated = $false
for ($i=0; $i -lt 36; $i++) {
  if (Test-Path $statusFile) {
    $now = (Get-Item $statusFile).LastWriteTimeUtc.Ticks
    if ($now -gt $before) { $updated = $true; break }
  }
  Start-Sleep -Seconds 5
}
if ($updated) { OK "sync_status.json обновился после Start (≤3 мин)" } else { BAD "sync_status.json не обновился после Start" }
if (Test-Path $statusFile) {
  Start-Sleep -Seconds 2
  $st = Get-Content $statusFile -Raw -Encoding UTF8 | ConvertFrom-Json
  if (-not $st.consecutive_failures) { OK "синк по расписанию без ошибок" } else { BAD "синк падает: $($st.last_error)" }
} else { BAD "sync_status.json нет вовсе" }
$srvMem = Join-Path $Srv "memory\MEMORY.md"
if ((Test-Path $srvMem) -and ((Get-Content $srvMem -Raw -Encoding UTF8) -like "*restart*")) { OK "правка памяти доехала до «сервера» фоновым синком" }
else { BAD "правка памяти не доехала до «сервера» фоновым синком" }
try { $ti = Get-ScheduledTaskInfo -TaskName $TaskName; Write-Host "   LastTaskResult=$($ti.LastTaskResult) LastRunTime=$($ti.LastRunTime)" } catch {}
$syncLog = Join-Path $Cfg "logs\sync.log"
if (Test-Path $syncLog) { New-Item -ItemType Directory -Force -Path $Work | Out-Null; Copy-Item $syncLog (Join-Path $Work "win_sync.log") -Force; Get-Content $syncLog -Tail 3 -Encoding UTF8 | ForEach-Object { Write-Host "   log: $_" } }

# 6. Unregister
schtasks /Delete /TN $TaskName /F | Out-Null
schtasks /Query /TN $TaskName 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { OK "задача снята (Unregister)" } else { BAD "задача осталась после удаления" }

# 7. probe.ps1: ssh / ssh_keygen / python_version в ikigai_env.json
Push-Location $WS
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Repo "ikigai-preflight\scripts\probe.ps1") -Json | Out-Null
$probeRc = $LASTEXITCODE
Pop-Location
Write-Host "   probe.ps1 rc=$probeRc"
if (Test-Path $EnvJson) {
  $p = Get-Content $EnvJson -Raw -Encoding UTF8 | ConvertFrom-Json
  $miss = @(); foreach ($k in @('ssh','ssh_keygen','python_version')) { if ($null -eq $p.$k) { $miss += $k } }
  if ($miss.Count -eq 0) { OK "probe.ps1 записал ssh/ssh_keygen/python_version" } else { BAD "в профиле нет полей: $($miss -join ',')" }
} else { BAD "probe.ps1 не записал профиль" }

# 8. audit.ps1 без сервера — без исключений (PowerShell-исключение даёт rc≠0 и текст ошибки)
$auditOut = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Repo "novoselie-server-kit\audit\audit.ps1") $WS 2>&1
$auditRc = $LASTEXITCODE
$auditTxt = ($auditOut | Out-String)
Write-Host "   audit.ps1 rc=$auditRc"
if ($auditTxt -match 'ParserError|CategoryInfo|Exception') { BAD "audit.ps1 выбросил исключение"; $auditOut | Select-Object -Last 8 | ForEach-Object { Write-Host "   $_" } }
else { OK "audit.ps1 отработал без исключения (сервера нет)" }

Write-Host "----"
Write-Host "win-integration: $Pass PASS, $Fail FAIL"
if ($Fail -gt 0) { exit 1 } else { exit 0 }
