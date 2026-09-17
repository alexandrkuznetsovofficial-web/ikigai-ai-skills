# probe.ps1 — «профиль компьютера» ученика Академии, версия для PowerShell (Windows 10/11, без прав администратора).
# Когда нужен: если Claude Code не может выполнить probe.sh (нет Git Bash). Запуск руками из PowerShell:
#   powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.claude\skills\ikigai-preflight\scripts\probe.ps1"
# Ничего не устанавливает и не меняет, кроме записи профиля в %USERPROFILE%\.claude\ikigai_env.json.
# Версия 1.0 · 2026-09-17
param([switch]$Json)
$ErrorActionPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

function Ver($cmd, $arg) { try { $o = & cmd /c "$cmd $arg 2>nul"; if ($LASTEXITCODE -eq 0 -and $o) { return ([string]$o).Split("`n")[0].Trim() } } catch {}; return "" }
function Has($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

$os = Get-CimInstance Win32_OperatingSystem
$home_ = $env:USERPROFILE
$local = if ($env:LOCALAPPDATA -and (Test-Path $env:LOCALAPPDATA)) { $env:LOCALAPPDATA } else { Join-Path $home_ 'AppData\Local' }
$roam  = if ($env:APPDATA -and (Test-Path $env:APPDATA)) { $env:APPDATA } else { Join-Path $home_ 'AppData\Roaming' }
$pf    = if ($env:ProgramFiles) { $env:ProgramFiles } else { 'C:\Program Files' }

$claudeCli = if (Has 'claude') { Ver 'claude' '--version' } else { '' }
$signed = if (Test-Path (Join-Path $home_ '.claude\.credentials.json')) { 'yes' } else { 'no' }

$vscode = ''
if (Has 'code') { $vscode = Ver 'code' '--version' }
if (-not $vscode) {
  foreach ($p in @("$local\Programs\Microsoft VS Code\Code.exe", "$pf\Microsoft VS Code\Code.exe")) { if (Test-Path $p) { $vscode = 'app'; break } }
}
$ext = 'no'
if (Get-ChildItem "$home_\.vscode\extensions" -Directory -Filter 'anthropic.claude-code-*' -ErrorAction SilentlyContinue) { $ext = 'yes' }

$gitV = if (Has 'git') { (Ver 'git' '--version') -replace 'git version ', '' } else { '' }
$nodeV = if (Has 'node') { Ver 'node' '--version' } else { '' }
$pyCmd = ''; $pyV = ''
if (Has 'py') { $pyV = Ver 'py' '-3 --version'; if ($pyV) { $pyCmd = 'py -3' } }
if (-not $pyCmd -and (Has 'python')) { $v = Ver 'python' '--version'; if ($v -like 'Python*') { $pyV = $v; $pyCmd = 'python' } }

$handy = 'no'; $handyModel = 'unknown'; $handySettings = ''
foreach ($p in @("$local\Programs\Handy\Handy.exe", "$local\Programs\handy\Handy.exe", "$pf\Handy\Handy.exe", "$local\Handy\Handy.exe")) { if (Test-Path $p) { $handy = 'yes'; break } }
foreach ($d in @("$roam\com.pais.handy", "$roam\handy", "$roam\Handy", "$local\com.pais.handy")) { if (Test-Path $d) { $handySettings = $d; break } }
if ($handySettings) {
  $handy = 'yes'
  $m = Get-ChildItem $handySettings -Recurse -Filter '*.json' -ErrorAction SilentlyContinue | Select-String -Pattern '"(selected_model|model|current_model)"\s*:\s*"([^"]*)"' | Select-Object -First 1
  if ($m) { $handyModel = $m.Matches[0].Groups[2].Value }
}

$ws = (Get-Location).Path
$wsClaude = if (Test-Path (Join-Path $ws 'CLAUDE.md')) { 'yes' } else { 'no' }
$wsLatin = if ($ws -match '[^\x20-\x7E]') { 'no' } else { 'yes' }
$skillsDir = Join-Path $home_ '.claude\skills'
$skillsCount = 0; if (Test-Path $skillsDir) { $skillsCount = (Get-ChildItem $skillsDir -Directory | Measure-Object).Count }

$profile = [ordered]@{
  probe_version = '1.0'; checked_at = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')
  os = "Windows"; os_branch = 'windows'; os_version = "$($os.Caption) $($os.BuildNumber)"; arch = $env:PROCESSOR_ARCHITECTURE; home = $home_
  claude_cli = $claudeCli; claude_signed_in = $signed; vscode = $vscode; vscode_ext_claude = $ext
  git = $gitV; node = $nodeV; python_cmd = $pyCmd; python = $pyV
  handy = $handy; handy_model = $handyModel
  workspace = $ws; workspace_has_claude_md = $wsClaude; workspace_latin = $wsLatin
  skills_dir = $skillsDir; skills_count = $skillsCount; ffmpeg = 'no'; whisper_cli = 'no'; brew = 'no'
}
$jsonText = ($profile | ConvertTo-Json -Compress)
New-Item -ItemType Directory -Force -Path (Join-Path $home_ '.claude') | Out-Null
[IO.File]::WriteAllText((Join-Path $home_ '.claude\ikigai_env.json'), $jsonText, (New-Object System.Text.UTF8Encoding($false)))
if ($Json) { Write-Output $jsonText; exit 0 }

function OK($t) { Write-Host "  ✅ $t" }; function BAD($t) { Write-Host "  ❌ $t" }; function WARN($t) { Write-Host "  ⚠️  $t" }
Write-Host ""; Write-Host "ПРОФИЛЬ КОМПЬЮТЕРА · $($profile.checked_at)"
Write-Host "  🖥  Windows: $($os.Caption), сборка $($os.BuildNumber), $($env:PROCESSOR_ARCHITECTURE)"
Write-Host "  🏠 домашняя папка: $home_"
if ($vscode) { OK "VS Code установлен ($vscode)" } else { BAD "VS Code не найден → скачать code.visualstudio.com, Windows x64 User Installer" }
if ($ext -eq 'yes') { OK "расширение «Claude Code for VS Code» установлено" } else { BAD "расширения Claude Code в VS Code нет → Extensions → «Claude Code» (Anthropic) → Install → перезапустить VS Code" }
if ($signed -eq 'yes') { OK "вход в Claude выполнен" } else { BAD "входа в Claude нет → панель Claude Code (оранжевый значок) → Sign in → браузер → «Создайте нечто великое»" }
if ($claudeCli) { OK "Claude Code CLI: $claudeCli" } else { WARN "Claude Code CLI в PATH нет (для расширения VS Code не обязателен)" }
if ($gitV) { OK "git $gitV" } else { BAD "git не найден → PowerShell: winget install --id Git.Git -e --source winget, затем перезапустить VS Code" }
if ($pyCmd) { OK "Python: $pyV (команда: $pyCmd)" } else { WARN "Python не найден (нужен только паку почты и календаря) → Microsoft Store: «Python 3»" }
if ($nodeV) { OK "Node.js $nodeV" } else { WARN "Node.js нет (для нашей сборки не обязателен)" }
if ($handy -eq 'yes') {
  if ($handyModel -match 'v3') { OK "Handy стоит, модель $handyModel (многоязычная, русский понимает) — проверь диктовкой, что она скачана" }
  elseif ($handyModel -match 'parakeet') { BAD "Handy стоит, но модель $handyModel — английская → Handy → Модели → скачать Whisper (многоязычная) или Parakeet V3 → выбрать" }
  elseif ($handyModel -eq 'unknown') { WARN "Handy стоит, модель не смог прочитать → проверь диктовкой: Блокнот, горячая клавиша, фраза по-русски" }
  else { OK "Handy стоит, модель: $handyModel" }
} else { WARN "Handy не найден (голосовой ввод; не обязателен, есть микрофон VS Code)" }
if ($wsClaude -eq 'yes') { OK "рабочая папка с CLAUDE.md: $ws" } else { WARN "в текущей папке нет CLAUDE.md — открой папку второго мозга: File → Open Folder" }
if ($wsLatin -eq 'no') { BAD "в пути рабочей папки есть не-латинские символы → переименуй папку латиницей (SecondBrain)" }
Write-Host "  📚 скиллов в ${skillsDir}: $skillsCount"
Write-Host "  💾 профиль записан: $home_\.claude\ikigai_env.json"; Write-Host ""
Write-Output $jsonText
