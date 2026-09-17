#!/usr/bin/env bash
# probe.sh — «профиль компьютера» ученика Академии.
# Запускается из Claude Code (Mac: zsh/bash; Windows: Git Bash, который Claude Code использует для команд).
# Ничего не устанавливает и не меняет, кроме записи профиля в ~/.claude/ikigai_env.json.
# Вывод: таблица для человека + одна строка JSON (или только JSON с флагом --json).
# Версия 1.0 · 2026-09-17

PROBE_VERSION="1.0"
ONLY_JSON=0
[ "${1:-}" = "--json" ] && ONLY_JSON=1

# ---------- ОС ----------
UNAME="$(uname -s 2>/dev/null || echo unknown)"
case "$UNAME" in
  Darwin*)                 OS_BRANCH="mac" ;;
  MINGW*|MSYS*|CYGWIN*)    OS_BRANCH="windows" ;;
  Linux*)                  OS_BRANCH="linux" ;;
  *)                       OS_BRANCH="unknown" ;;
esac
ARCH="$(uname -m 2>/dev/null || echo unknown)"
OS_VERSION=""
if [ "$OS_BRANCH" = "mac" ]; then
  OS_VERSION="$(sw_vers -productVersion 2>/dev/null)"
elif [ "$OS_BRANCH" = "windows" ]; then
  OS_VERSION="$(cmd.exe /c ver 2>/dev/null | tr -d '\r' | grep -o '[0-9][0-9.]*' | head -1)"
else
  OS_VERSION="$(uname -r 2>/dev/null)"
fi
HOME_DIR="${HOME:-$(cd ~ && pwd)}"

# Windows-пути: Git Bash даёт %LOCALAPPDATA% в виде C:\..., переводим в /c/...
to_unix() { if command -v cygpath >/dev/null 2>&1; then cygpath -u "$1" 2>/dev/null; else printf '%s' "$1"; fi; }
LOCALAPP=""; APPDATA_U=""; PROGFILES=""
if [ "$OS_BRANCH" = "windows" ]; then
  LOCALAPP="$(to_unix "${LOCALAPPDATA:-}")"
  APPDATA_U="$(to_unix "${APPDATA:-}")"
  PROGFILES="$(to_unix "${PROGRAMFILES:-C:\\Program Files}")"
  # Запасной путь: в Git Bash HOME = /c/Users/<имя>, а переменные Windows иногда не пробрасываются.
  [ -d "$LOCALAPP" ] || LOCALAPP="$HOME_DIR/AppData/Local"
  [ -d "$APPDATA_U" ] || APPDATA_U="$HOME_DIR/AppData/Roaming"
  [ -d "$PROGFILES" ] || PROGFILES="/c/Program Files"
fi

have() { command -v "$1" >/dev/null 2>&1; }
ver_of() { "$@" 2>/dev/null | head -1 | tr -d '\r'; }

# ---------- Claude Code ----------
CLAUDE_CLI=""
if have claude; then CLAUDE_CLI="$(ver_of claude --version)"; fi
CLAUDE_SIGNED="unknown"
if [ "$OS_BRANCH" = "mac" ]; then
  if security find-generic-password -s "Claude Code-credentials" >/dev/null 2>&1; then CLAUDE_SIGNED="yes"; else CLAUDE_SIGNED="no"; fi
else
  if [ -s "$HOME_DIR/.claude/.credentials.json" ]; then CLAUDE_SIGNED="yes"; else CLAUDE_SIGNED="no"; fi
fi

# ---------- VS Code ----------
VSCODE=""
if have code; then VSCODE="$(ver_of code --version)"; fi
if [ -z "$VSCODE" ]; then
  if [ "$OS_BRANCH" = "mac" ] && [ -d "/Applications/Visual Studio Code.app" ]; then VSCODE="app"; fi
  if [ "$OS_BRANCH" = "windows" ]; then
    for p in "$LOCALAPP/Programs/Microsoft VS Code/Code.exe" "$PROGFILES/Microsoft VS Code/Code.exe" \
             "$HOME_DIR/AppData/Local/Programs/Microsoft VS Code/Code.exe"; do
      [ -f "$p" ] && VSCODE="app" && break
    done
  fi
fi
VSCODE_EXT_CLAUDE="no"
for d in "$HOME_DIR/.vscode/extensions"/anthropic.claude-code-* "$HOME_DIR/.vscode-insiders/extensions"/anthropic.claude-code-*; do
  [ -d "$d" ] && VSCODE_EXT_CLAUDE="yes" && break
done

# ---------- git / node / python ----------
GIT_V=""; have git && GIT_V="$(ver_of git --version | sed 's/git version //')"
NODE_V=""; have node && NODE_V="$(ver_of node --version)"
PY_CMD=""; PY_V=""
if [ "$OS_BRANCH" = "windows" ]; then
  if have py; then PY_V="$(ver_of py -3 --version)"; [ -n "$PY_V" ] && PY_CMD="py -3"; fi
  if [ -z "$PY_CMD" ] && have python; then PY_V="$(ver_of python --version)"; case "$PY_V" in Python*) PY_CMD="python";; *) PY_V="";; esac; fi
else
  if have python3; then PY_V="$(ver_of python3 --version)"; PY_CMD="python3"; fi
fi

# ---------- Handy ----------
HANDY="no"; HANDY_MODEL="unknown"; HANDY_SETTINGS=""
if [ "$OS_BRANCH" = "mac" ]; then
  [ -d "/Applications/Handy.app" ] && HANDY="yes"
  for d in "$HOME_DIR/Library/Application Support/com.pais.handy" "$HOME_DIR/Library/Application Support/handy" "$HOME_DIR/Library/Application Support/Handy"; do
    [ -d "$d" ] && HANDY_SETTINGS="$d" && break
  done
elif [ "$OS_BRANCH" = "windows" ]; then
  for p in "$LOCALAPP/Programs/Handy/Handy.exe" "$LOCALAPP/Programs/handy/Handy.exe" "$PROGFILES/Handy/Handy.exe" \
           "$LOCALAPP/Handy/Handy.exe" "$HOME_DIR/AppData/Local/Programs/Handy/Handy.exe"; do
    [ -f "$p" ] && HANDY="yes" && break
  done
  for d in "$APPDATA_U/com.pais.handy" "$APPDATA_U/handy" "$APPDATA_U/Handy" "$LOCALAPP/com.pais.handy" \
           "$HOME_DIR/AppData/Roaming/com.pais.handy" "$HOME_DIR/AppData/Local/com.pais.handy"; do
    [ -d "$d" ] && HANDY_SETTINGS="$d" && break
  done
fi
if [ -n "$HANDY_SETTINGS" ]; then
  HANDY="yes"
  # ищем выбранную модель в json-настройках (значение печатаем как есть, без ключей)
  M="$(grep -rhoE '"(selected_model|model|current_model)"[[:space:]]*:[[:space:]]*"[^"]*"' "$HANDY_SETTINGS" 2>/dev/null | head -1 | sed 's/.*:[[:space:]]*"//; s/"$//')"
  [ -n "$M" ] && HANDY_MODEL="$M"
fi

# ---------- рабочая папка (второй мозг) ----------
WS="$(pwd)"
WS_HAS_CLAUDE_MD="no"; [ -f "$WS/CLAUDE.md" ] && WS_HAS_CLAUDE_MD="yes"
WS_LATIN="yes"; printf '%s' "$WS" | LC_ALL=C grep -q '[^ -~]' && WS_LATIN="no"
SKILLS_DIR="$HOME_DIR/.claude/skills"
SKILLS_COUNT=0; [ -d "$SKILLS_DIR" ] && SKILLS_COUNT="$(find "$SKILLS_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"

# ---------- инструменты для видео-паков (только Mac) ----------
FFMPEG="no"; have ffmpeg && FFMPEG="yes"
WHISPER="no"; have whisper-cli && WHISPER="yes"
BREW="no"; have brew && BREW="yes"

# ---------- запись профиля ----------
CHECKED_AT="$(date '+%Y-%m-%dT%H:%M:%S')"
esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
JSON=$(printf '{"probe_version":"%s","checked_at":"%s","os":"%s","os_branch":"%s","os_version":"%s","arch":"%s","home":"%s","claude_cli":"%s","claude_signed_in":"%s","vscode":"%s","vscode_ext_claude":"%s","git":"%s","node":"%s","python_cmd":"%s","python":"%s","handy":"%s","handy_model":"%s","workspace":"%s","workspace_has_claude_md":"%s","workspace_latin":"%s","skills_dir":"%s","skills_count":%s,"ffmpeg":"%s","whisper_cli":"%s","brew":"%s"}' \
  "$PROBE_VERSION" "$CHECKED_AT" "$(esc "$UNAME")" "$OS_BRANCH" "$(esc "$OS_VERSION")" "$(esc "$ARCH")" "$(esc "$HOME_DIR")" \
  "$(esc "$CLAUDE_CLI")" "$CLAUDE_SIGNED" "$(esc "$VSCODE")" "$VSCODE_EXT_CLAUDE" "$(esc "$GIT_V")" "$(esc "$NODE_V")" \
  "$(esc "$PY_CMD")" "$(esc "$PY_V")" "$HANDY" "$(esc "$HANDY_MODEL")" "$(esc "$WS")" "$WS_HAS_CLAUDE_MD" "$WS_LATIN" \
  "$(esc "$SKILLS_DIR")" "${SKILLS_COUNT:-0}" "$FFMPEG" "$WHISPER" "$BREW")
mkdir -p "$HOME_DIR/.claude" 2>/dev/null
printf '%s\n' "$JSON" > "$HOME_DIR/.claude/ikigai_env.json" 2>/dev/null

if [ "$ONLY_JSON" = "1" ]; then printf '%s\n' "$JSON"; exit 0; fi

# ---------- таблица для человека ----------
ok()   { printf '  ✅ %s\n' "$1"; }
bad()  { printf '  ❌ %s\n' "$1"; }
warn() { printf '  ⚠️  %s\n' "$1"; }
case "$OS_BRANCH" in
  mac) OSN="Mac (macOS $OS_VERSION, $ARCH)";;
  windows) OSN="Windows ($OS_VERSION, команды через Git Bash)";;
  linux) OSN="Linux ($OS_VERSION)";;
  *) OSN="не распознал систему ($UNAME)";;
esac
printf '\nПРОФИЛЬ КОМПЬЮТЕРА · %s\n' "$CHECKED_AT"
printf '  🖥  %s\n' "$OSN"
printf '  🏠 домашняя папка: %s\n' "$HOME_DIR"

if [ -n "$VSCODE" ]; then ok "VS Code установлен${VSCODE:+ ($VSCODE)}"; else
  if [ "$OS_BRANCH" = "windows" ]; then bad "VS Code не найден → скачать code.visualstudio.com, Windows x64 User Installer"; else bad "VS Code не найден → скачать code.visualstudio.com (Apple Silicon или Intel по процессору)"; fi; fi
if [ "$VSCODE_EXT_CLAUDE" = "yes" ]; then ok "расширение «Claude Code for VS Code» установлено"; else bad "расширения Claude Code в VS Code нет → Extensions → «Claude Code» (Anthropic) → Install → перезапустить VS Code"; fi
if [ "$CLAUDE_SIGNED" = "yes" ]; then ok "вход в Claude выполнен"; elif [ "$CLAUDE_SIGNED" = "no" ]; then bad "входа в Claude нет → открыть панель Claude Code (оранжевый значок) → Sign in → браузер → «Создайте нечто великое»"; else warn "вход в Claude: не смог проверить"; fi
if [ -n "$CLAUDE_CLI" ]; then ok "Claude Code CLI: $CLAUDE_CLI"; else warn "Claude Code CLI в PATH нет (для расширения VS Code не обязателен)"; fi
if [ -n "$GIT_V" ]; then ok "git $GIT_V"; else
  if [ "$OS_BRANCH" = "windows" ]; then bad "git не найден → PowerShell: winget install --id Git.Git -e --source winget, затем перезапустить VS Code"; else bad "git не найден → xcode-select --install"; fi; fi
if [ -n "$PY_CMD" ]; then ok "Python: $PY_V (команда: $PY_CMD)"; else
  if [ "$OS_BRANCH" = "windows" ]; then warn "Python не найден (нужен только для паков вроде почты и календаря) → Microsoft Store: «Python 3»"; else warn "Python не найден → python.org или brew install python3"; fi; fi
if [ -n "$NODE_V" ]; then ok "Node.js $NODE_V"; else warn "Node.js нет (для нашей сборки не обязателен)"; fi
if [ "$HANDY" = "yes" ]; then
  case "$HANDY_MODEL" in
    *v3*|*V3*) ok "Handy стоит, модель $HANDY_MODEL (многоязычная, русский понимает) — проверь диктовкой, что она скачана";;
    *[Pp]arakeet*) bad "Handy стоит, но модель $HANDY_MODEL — английская → Handy → Модели → скачать Whisper (многоязычная) или Parakeet V3 → выбрать";;
    unknown) warn "Handy стоит, модель не смог прочитать → проверь диктовкой: Блокнот, горячая клавиша, фраза по-русски";;
    *) ok "Handy стоит, модель: $HANDY_MODEL";;
  esac
else warn "Handy не найден (голосовой ввод; не обязателен, есть микрофон VS Code)"; fi
if [ "$WS_HAS_CLAUDE_MD" = "yes" ]; then ok "рабочая папка с CLAUDE.md: $WS"; else warn "в текущей папке нет CLAUDE.md — открой папку второго мозга: File → Open Folder"; fi
if [ "$WS_LATIN" = "no" ]; then bad "в пути рабочей папки есть не-латинские символы → переименуй папку латиницей (SecondBrain)"; fi
printf '  📚 скиллов в %s: %s\n' "$SKILLS_DIR" "${SKILLS_COUNT:-0}"
if [ "$OS_BRANCH" = "mac" ]; then
  [ "$FFMPEG" = "yes" ] && ok "ffmpeg есть (для рилс-пака)" || warn "ffmpeg нет (нужен только рилс-паку: brew install ffmpeg)"
  [ "$WHISPER" = "yes" ] && ok "whisper-cli есть" || warn "whisper-cli нет (нужен только рилс-паку: brew install whisper-cpp)"
fi
printf '  💾 профиль записан: %s/.claude/ikigai_env.json\n\n' "$HOME_DIR"
printf '%s\n' "$JSON"
