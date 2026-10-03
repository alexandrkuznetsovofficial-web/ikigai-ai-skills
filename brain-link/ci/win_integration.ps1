# win_integration.ps1 — расписание brain-sync на Windows через настоящий install_task.ps1 (лаборатория).
# Windows PowerShell 5.1 (powershell.exe). Транспорт — local (sync_shim.py), см. ci\README.md.
# Проверяет: рендер шаблона, Register -> Start -> ждём sync_status.json -> StartWhenAvailable/батарея/IgnoreNew
# -> Unregister; probe.ps1 (ssh/ssh_keygen/python_version в ikigai_env.json); audit.ps1 на фейковом HOME без сервера;
# путь с пробелом и кириллицей. Только для GitHub Actions.
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Pass = 0; $Fail = 0
function OK($t){ $script:Pass++; Write-Host "PASS $t" }
function BAD($t){ $script:Fail++; Write-Host "FAIL $t" }

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = (Resolve-Path (Join-Path $Here "..\..")).Path
$Scripts = Join-Path $Repo "brain-link\scripts"
$Work = if ($env:WORK) { $env:WORK } else { Join-Path $env:RUNNER_TEMP "brain-lab" }
# путь пользователя с пробелом и кириллицей (требование ТЗ)
$Home_ = Join-Path $Work "Мой мозг"
$WS = Join-Path $Home_ "SecondBrain"
$Srv = Join-Path $Work "server"
$Cfg = Join-Path $Home_ ".config\brain"
$Py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Py) { $Py = (Get-Command py -ErrorAction SilentlyContinue).Source }
foreach ($d in @($WS+"\memory\inbox", $WS+"\memory\dialogues", $Srv+"\memory\inbox", $Srv+"\memory\dialogues", $Cfg, "$Home_\.claude\skills\brain-link")) {
  New-Item -ItemType Directory -Force -Path $d | Out-Null
}
Set-Content -Path (Join-Path $WS "CLAUDE.md") -Value "# CLAUDE" -Encoding UTF8
Set-Content -Path (Join-Path $WS "memory\MEMORY.md") -Value ("# MEMORY win " + [int][double]::Parse((Get-Date -UFormat %s))) -Encoding UTF8
Set-Content -Path (Join-Path $Home_ ".claude\skills\brain-link\SKILL.md") -Value "skill" -Encoding UTF8
Set-Content -Path (Join-Path $Cfg "ci_transport.txt") -Value ("local:" + $Srv) -Encoding ASCII
$EnvJson = Join-Path $Home_ ".claude\ikigai_env.json"
New-Item -ItemType Directory -Force -Path (Split-Path $EnvJson) | Out-Null
@{ workspace = $WS; workspace_win = $WS } | ConvertTo-Json -Compress | Set-Content -Path $EnvJson -Encoding UTF8

$env:HOME = $Home_; $env:USERPROFILE = $Home_
$env:BRAIN_CONFIG_DIR = $Cfg
$env:BRAIN_IKIGAI_ENV = $EnvJson

# 1. render_ps1 из модуля — настоящий шаблон читается, BOM + CRLF
& $Py -c @"
import sys; sys.path.insert(0, r'$Scripts')
import brain_link
b = brain_link.render_ps1()
assert b[:3] == b'\xef\xbb\xbf', 'нет BOM'
assert b'\r\n' in b, 'нет CRLF'
print('render_ps1 ok', len(b))
"@
if ($LASTEXITCODE -eq 0) { OK "настоящий шаблон install_task.ps1 рендерится (BOM+CRLF)" } else { BAD "render_ps1 упал" }

# 2. init (local) через шим
& $Py (Join-Path $Here "drive_link.py") --sync-shim -- init --yes --root $WS --skills-dir "$Home_\.claude\skills" --transport ("local:" + $Srv) | Out-Null
if ($LASTEXITCODE -eq 0) { OK "init (local) прошёл" } else { BAD "init (local) не прошёл (rc=$LASTEXITCODE)" }

# 3. запуск НАСТОЯЩЕГО install_task.ps1 с -Script = sync_shim.py (транспорт local), -Python = pythonw
$TaskName = "Ikigai brain-sync"
$Pyw = Join-Path (Split-Path $Py) "pythonw.exe"
if (-not (Test-Path $Pyw)) { $Pyw = $Py }
schtasks /Query /TN $TaskName 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { schtasks /Delete /TN $TaskName /F | Out-Null }
$installPs1 = Join-Path $Repo "brain-link\templates\install_task.ps1"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installPs1 -Script (Join-Path $Here "sync_shim.py") -Python $Pyw
if ($LASTEXITCODE -eq 0) { OK "install_task.ps1 отработал (Register + Start)" } else { BAD "install_task.ps1 вернул $LASTEXITCODE" }

# 4. поля задачи: StartWhenAvailable, работа от батареи, IgnoreNew
try {
  $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  if ($t.Settings.StartWhenAvailable) { OK "StartWhenAvailable=true" } else { BAD "StartWhenAvailable выключен" }
  if (-not $t.Settings.DisallowStartIfOnBatteries) { OK "запуск от батареи разрешён" } else { BAD "запуск от батареи запрещён" }
  if ("$($t.Settings.MultipleInstances)" -eq "IgnoreNew") { OK "MultipleInstances=IgnoreNew" } else { BAD "MultipleInstances=$($t.Settings.MultipleInstances)" }
} catch { BAD "задача не зарегистрирована: $_" }

# 5. Start → ждём обновления sync_status.json до 3 минут
$statusFile = Join-Path $Cfg "sync_status.json"
$before = if (Test-Path $statusFile) { (Get-Item $statusFile).LastWriteTimeUtc.Ticks } else { 0 }
Start-ScheduledTask -TaskName $TaskName
$updated = $false
for ($i=0; $i -lt 36; $i++) {
  if (Test-Path $statusFile) {
    $now = (Get-Item $statusFile).LastWriteTimeUtc.Ticks
    if ($now -gt $before) { $updated = $true; break }
  }
  Start-Sleep -Seconds 5
}
if ($updated) { OK "sync_status.json обновился после Start (≤3 мин)" } else { BAD "sync_status.json не обновился" }
if ($updated) {
  $st = Get-Content $statusFile -Raw | ConvertFrom-Json
  if (-not $st.consecutive_failures) { OK "синк по расписанию без ошибок" } else { BAD "синк падает: $($st.last_error)" }
}

# 6. Unregister
schtasks /Delete /TN $TaskName /F | Out-Null
schtasks /Query /TN $TaskName 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { OK "задача снята (Unregister)" } else { BAD "задача осталась после удаления" }

# 7. probe.ps1: ssh / ssh_keygen / python_version в ikigai_env.json
Push-Location $WS
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Repo "ikigai-preflight\scripts\probe.ps1") -Json | Out-Null
Pop-Location
if (Test-Path $EnvJson) {
  $p = Get-Content $EnvJson -Raw | ConvertFrom-Json
  $miss = @(); foreach ($k in @('ssh','ssh_keygen','python_version')) { if ($null -eq $p.$k) { $miss += $k } }
  if ($miss.Count -eq 0) { OK "probe.ps1 записал ssh/ssh_keygen/python_version" } else { BAD "в профиле нет полей: $($miss -join ',')" }
} else { BAD "probe.ps1 не записал профиль" }

# 8. audit.ps1 на фейковом HOME без сервера — без исключений
$auditOut = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Repo "novoselie-server-kit\audit\audit.ps1") $WS 2>&1
if ($LASTEXITCODE -eq 0 -or $null -ne $auditOut) { OK "audit.ps1 отработал без исключения (фейковый HOME, сервера нет)" } else { BAD "audit.ps1 упал" }

Write-Host "----"
Write-Host "win-integration: $Pass PASS, $Fail FAIL"
if ($Fail -gt 0) { exit 1 } else { exit 0 }
