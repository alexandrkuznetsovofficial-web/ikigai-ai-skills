# Установка окружения пака «Второй мозг ↔ почта и календарь» на Windows.
# Запускается из Claude Code, руками ничего вводить не нужно. Повторный запуск безопасен.
$ErrorActionPreference = "Stop"
$venv = Join-Path $env:USERPROFILE ".venvs\mck"
$dir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$req  = Join-Path $dir "requirements.txt"

function Say-Json($obj) { $obj | ConvertTo-Json -Compress -Depth 4 }

$py = $null
foreach ($c in @("py -3", "python", "python3")) {
  try { & cmd /c "$c --version" *> $null; if ($LASTEXITCODE -eq 0) { $py = $c; break } } catch {}
}
if (-not $py) {
  Say-Json @{ ok = $false; human = "Python не найден. Поставь его из Microsoft Store (ищи «Python 3») и повтори." }
  exit 1
}

$vpy = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $vpy)) {
  & cmd /c "$py -m venv `"$venv`"" *> $null
  if (-not (Test-Path $vpy)) {
    Say-Json @{ ok = $false; human = "Не удалось создать окружение в $venv. Проверь, что Python установлен полностью." }
    exit 1
  }
}

& $vpy -m pip install --quiet --upgrade pip *> $null
& $vpy -m pip install --quiet -r $req 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
  Say-Json @{ ok = $false; human = "pip не смог поставить зависимости — чаще всего это отсутствие интернета." }
  exit 1
}

$check = @"
import json, sys
mods = {}
for m in ('caldav', 'icalendar', 'recurring_ical_events', 'dotenv', 'certifi', 'googleapiclient', 'google_auth_oauthlib', 'notion_client'):
    try:
        __import__(m); mods[m] = True
    except Exception:
        mods[m] = False
ok = all(mods[m] for m in ('caldav', 'icalendar', 'recurring_ical_events', 'dotenv'))
print(json.dumps({'ok': ok, 'python': sys.executable, 'modules': mods,
                  'human': ('окружение готово: ' + sys.executable) if ok else 'часть модулей не встала, см. modules'},
                 ensure_ascii=False))
sys.exit(0 if ok else 1)
"@
$check | & $vpy -
exit $LASTEXITCODE
