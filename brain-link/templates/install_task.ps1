# install_task.ps1 — расписание brain-sync на Windows (kit 2.1, KIT_CONVENTIONS §8).
# Задача "Ikigai brain-sync": каждые 5 минут бесконечно, при входе в систему, пропуск догоняется
# (StartWhenAvailable), работает от батареи, второй экземпляр не запускается (IgnoreNew).
# Запуск через pythonw.exe — без чёрного окна. LogonType Interactive: пароль Windows не хранится,
# задача идёт, пока человек вошёл в систему.
# Файл сохранён в UTF-8 с BOM и CRLF — иначе Windows PowerShell 5.1 ломает кириллицу в путях.
# Запуск (из Git Bash тоже — файлом, не одной строкой):
#   powershell -NoProfile -ExecutionPolicy Bypass -File "<путь>\install_task.ps1"
#   необязательно: -Python "C:\...\pythonw.exe" -Script "C:\...\brain_sync.py"
param(
  [string]$Python = "",
  [string]$Script = ""
)
$ErrorActionPreference = 'Stop'
$name = "Ikigai brain-sync"

if (-not $Script) { $Script = Join-Path (Split-Path -Parent $PSScriptRoot) "scripts\brain_sync.py" }
if (-not (Test-Path -LiteralPath $Script)) { Write-Output "СТОП: не найден $Script"; exit 1 }

if (-not $Python) {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    try {
      $Python = (& $py.Source -3 -c "import os,sys;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" | Select-Object -First 1).Trim()
    } catch { $Python = "" }
  }
  if (-not $Python -or -not (Test-Path -LiteralPath $Python)) {
    $pw = Get-Command pythonw -ErrorAction SilentlyContinue
    if ($pw) { $Python = $pw.Source }
  }
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python)) {
  Write-Output "СТОП: не найден pythonw.exe. Поставь Python 3 с python.org (галочка Add to PATH) и запусти снова."
  exit 1
}

$action = New-ScheduledTaskAction -Execute $Python -Argument ("`"{0}`" run" -f $Script) -WorkingDirectory $env:USERPROFILE

# Каждые 5 минут бесконечно. Новые сборки Windows без RepetitionDuration повторяют бесконечно;
# старые сборки Windows 10 на это ругаются — тогда ставим 10 лет.
$start = (Get-Date).AddMinutes(1)
try {
  $every = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Minutes 5)
} catch {
  $every = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
}
$logon = New-ScheduledTaskTrigger -AtLogOn -User ("{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME)

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId ("{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME) -LogonType Interactive -RunLevel Limited

try {
  Register-ScheduledTask -TaskName $name -Action $action -Trigger @($every, $logon) -Settings $settings `
    -Principal $principal -Description "brain-sync: память и скиллы компьютер -> сервер, inbox бота -> компьютер" -Force | Out-Null
} catch {
  # старые сборки: бесконечный повтор при регистрации не прошёл — повторяем с явным сроком
  $every = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
  Register-ScheduledTask -TaskName $name -Action $action -Trigger @($every, $logon) -Settings $settings `
    -Principal $principal -Description "brain-sync: память и скиллы компьютер -> сервер, inbox бота -> компьютер" -Force | Out-Null
}

Start-ScheduledTask -TaskName $name
$t = Get-ScheduledTask -TaskName $name
"{0} | StartWhenAvailable={1} | Interval={2} | Battery start={3} | Battery stop={4} | Python={5}" -f `
  $t.TaskName, $t.Settings.StartWhenAvailable, $t.Triggers[0].Repetition.Interval, `
  (-not $t.Settings.DisallowStartIfOnBatteries), $t.Settings.StopIfGoingOnBatteries, $Python
