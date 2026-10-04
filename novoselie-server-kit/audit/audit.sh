#!/usr/bin/env bash
# =============================================================================
#  AI-ПОТОК · АУДИТ-ПАК
#  Проверяет, что у тебя уже собрано, и показывает, чего не хватает
#  до цели (kit 2.1): компьютер — мастерская, сервер — база. Правишь на компьютере,
#  сервер держит копию памяти и Telegram-бота 24/7, бот говорит из подписки.
#
#  Запуск:  bash audit.sh [папка мозга]
#  Папку мозга скрипт находит сам: workspace из ~/.claude/ikigai_env.json.
#  Ничего не ломает и не устанавливает. Только смотрит и рассказывает.
# =============================================================================

VERSION="2.1"   # kit 2.0: блок 7 — точки 13–23 эталона; kit 2.1: файл доступа §8, блок 8 — связка brain-link
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT="$SCRIPT_DIR/audit_report.md"
PROMPT_FILE="$SCRIPT_DIR/PROMPT_for_claude.txt"
# Файл доступа (KIT_CONVENTIONS §8): ~/.config/brain/server_access; старый путь (Windows через Git Bash) — запасной.
ACCESS_NEW="$HOME/.config/brain/server_access"
ACCESS_OLD="$HOME/.secrets/brain/server_access.txt"
ACCESS_FILE="${BRAIN_ACCESS_FILE:-$ACCESS_NEW}"
ACCESS_LEGACY_PATH=0
if [ -z "${BRAIN_ACCESS_FILE:-}" ] && [ ! -f "$ACCESS_NEW" ] && [ -f "$ACCESS_OLD" ]; then ACCESS_FILE="$ACCESS_OLD"; ACCESS_LEGACY_PATH=1; fi
KNOWN_HOSTS="$HOME/.config/brain/known_hosts"
ADMIN_KEY="$HOME/.ssh/id_ed25519"

# --- цвета (отключаются, если терминал не умеет) ---------------------------
if [ -t 1 ] && command -v tput >/dev/null 2>&1 && [ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]; then
  B=$(tput bold); D=$(tput sgr0); DIM=$(tput dim)
else
  B=""; D=""; DIM=""
fi

OK_N=0; WARN_N=0; FAIL_N=0
TODO_MANUAL=(); TODO_AGENT=()

# --- вывод -----------------------------------------------------------------
say()  { printf '%s\n' "$*"; printf '%s\n' "$*" >>"$REPORT.tmp"; }
head1(){ printf '\n%s%s%s\n' "$B" "$*" "$D"; printf '\n## %s\n\n' "$*" >>"$REPORT.tmp"; }
ok()   { OK_N=$((OK_N+1));     printf '  🟢 %s\n' "$*"; printf -- '- 🟢 %s\n' "$*" >>"$REPORT.tmp"; }
warn() { WARN_N=$((WARN_N+1)); printf '  🟡 %s\n' "$*"; printf -- '- 🟡 %s\n' "$*" >>"$REPORT.tmp"; }
bad()  { FAIL_N=$((FAIL_N+1)); printf '  🔴 %s\n' "$*"; printf -- '- 🔴 %s\n' "$*" >>"$REPORT.tmp"; }
info() { printf '  %s·%s %s\n' "$DIM" "$D" "$*"; printf -- '- · %s\n' "$*" >>"$REPORT.tmp"; }
manual(){ TODO_MANUAL+=("$1"); }
agentdo(){ TODO_AGENT+=("$1"); }

: >"$REPORT.tmp"

cat <<BANNER

╔══════════════════════════════════════════════════════════════╗
║   AI-ПОТОК · АУДИТ-ПАК v$VERSION                                ║
║   Смотрим, что уже собрано и что осталось до финиша          ║
╚══════════════════════════════════════════════════════════════╝

Ничего не устанавливаю и не меняю. Только смотрю.
Секреты (токены, пароли) на экран не выводятся — никогда.

BANNER

# =============================================================================
# БЛОК 1 — ТВОЙ КОМПЬЮТЕР
# =============================================================================
head1 "1. Твой компьютер"

OS_NAME="$(uname -s)"
case "$OS_NAME" in
  Darwin) OS_H="macOS $(sw_vers -productVersion 2>/dev/null)"; ok "Система: $OS_H" ;;
  Linux)  OS_H="Linux $(uname -r)"; ok "Система: $OS_H" ;;
  *)      OS_H="$OS_NAME"; warn "Система: $OS_H — кит рассчитан на macOS/Windows, но продолжим" ;;
esac

# Node.js
if command -v node >/dev/null 2>&1; then
  NODE_V="$(node -v 2>/dev/null)"
  NODE_MAJ="$(printf '%s' "$NODE_V" | sed 's/^v//' | cut -d. -f1)"
  if [ "${NODE_MAJ:-0}" -ge 18 ] 2>/dev/null; then ok "Node.js $NODE_V"
  else warn "Node.js $NODE_V — старая версия, нужна 18 или новее"; agentdo "обнови Node.js до версии 18+"; fi
else
  warn "Node.js не найден (не обязателен, если Claude Code ставился нативным установщиком)"
fi

command -v git >/dev/null 2>&1 && ok "git $(git --version | awk '{print $3}')" || { bad "git не установлен — без него не будет истории и откатов"; agentdo "установи git"; }
command -v ssh >/dev/null 2>&1 && ok "ssh-клиент есть (сможем зайти на сервер)" || { bad "ssh не найден"; agentdo "установи openssh-client"; }
command -v curl >/dev/null 2>&1 || bad "curl не найден — не смогу проверить бота"

# VS Code
if command -v code >/dev/null 2>&1; then ok "VS Code доступен из терминала"
elif [ -d "/Applications/Visual Studio Code.app" ]; then ok "VS Code установлен (команда code в PATH не прописана — не страшно)"
else warn "VS Code не найден"; manual "Установи VS Code — в нём живёт Claude Code"; fi

# =============================================================================
# БЛОК 2 — CLAUDE CODE НА КОМПЬЮТЕРЕ
# =============================================================================
head1 "2. Claude Code на компьютере"

CLAUDE_LOCAL=0
if command -v claude >/dev/null 2>&1; then
  CV="$(claude --version 2>/dev/null | head -1)"
  ok "Claude Code установлен: ${CV:-версия не определилась}"
  CLAUDE_LOCAL=1
else
  bad "Claude Code не установлен на этом компьютере"
  manual "Установи Claude Code: curl -fsSL https://claude.ai/install.sh | bash"
fi

# Как авторизован: подписка или API-ключ
API_KEY_FOUND=""
[ -n "${ANTHROPIC_API_KEY:-}" ] && API_KEY_FOUND="переменная окружения"
for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile" "$HOME/.zprofile"; do
  [ -f "$rc" ] && grep -q 'ANTHROPIC_API_KEY' "$rc" 2>/dev/null && API_KEY_FOUND="${API_KEY_FOUND:+$API_KEY_FOUND, }$(basename "$rc")"
done

LOGGED_IN=0
if [ -f "$HOME/.claude/.credentials.json" ]; then
  LOGGED_IN=1
elif [ "$OS_NAME" = "Darwin" ] && security find-generic-password -s "Claude Code-credentials" >/dev/null 2>&1; then
  LOGGED_IN=1   # macOS хранит вход в Связке ключей, а не в файле
fi
if [ "$LOGGED_IN" = "1" ]; then
  ok "Вход по подписке на месте"
elif [ "$CLAUDE_LOCAL" = "1" ]; then
  warn "Не вижу входа в Claude — открой терминал, набери claude и войди под своей подпиской"
  manual "Войди в Claude Code под своей подпиской (команда: claude)"
fi

if [ -n "$API_KEY_FOUND" ]; then
  bad "Найден API-ключ ANTHROPIC_API_KEY ($API_KEY_FOUND) — это ОПЛАТА ПО СЧЁТЧИКУ, а не подписка"
  agentdo "убери ANTHROPIC_API_KEY отовсюду: должна остаться только подписка"
else
  ok "API-ключа нет — работаешь из подписки, как и задумано"
fi

# =============================================================================
# БЛОК 3 — ПАПКА ВТОРОГО МОЗГА
# =============================================================================
head1 "3. Папка второго мозга"

# Порядок поиска: 1) workspace из профиля ~/.claude/ikigai_env.json (пишет ikigai-preflight),
# 2) аргумент скрипта или переменная BRAIN_DIR, 3) текущая папка, если в ней CLAUDE.md и memory/,
# 4) привычные места. Кандидат годится, если в нём есть CLAUDE.md или memory/.
ENV_JSON="$HOME/.claude/ikigai_env.json"
WS_ENV=""
if [ -f "$ENV_JSON" ]; then
  WS_ENV="$(sed -n 's/.*"workspace"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$ENV_JSON" 2>/dev/null | head -1 | sed 's/\\\\/\\/g')"
fi
BRAIN_ARG="${1:-${BRAIN_DIR:-}}"
BRAIN_DIR=""; BRAIN_FROM=""
is_brain() { [ -n "$1" ] && [ -d "$1" ] && { [ -f "$1/CLAUDE.md" ] || [ -d "$1/memory" ]; }; }
if   is_brain "$WS_ENV";    then BRAIN_DIR="$WS_ENV";    BRAIN_FROM="профиль ~/.claude/ikigai_env.json"
elif is_brain "$BRAIN_ARG"; then BRAIN_DIR="$BRAIN_ARG"; BRAIN_FROM="указана при запуске"
elif [ -f "$PWD/CLAUDE.md" ] && [ -d "$PWD/memory" ]; then BRAIN_DIR="$PWD"; BRAIN_FROM="текущая папка"
else
  for cand in "$HOME/brain" "$HOME/second-brain" "$HOME/SecondBrain" "$HOME/Documents/brain" "$HOME/Documents/SecondBrain"; do
    if is_brain "$cand"; then BRAIN_DIR="$cand"; BRAIN_FROM="нашёл в привычном месте"; break; fi
  done
fi
BRAIN_DIR="${BRAIN_DIR%/}"
# Мозг прямо в домашней папке — по ней не ходим вглубь: поиск ограничен 4 уровнями
FIND_DEPTH=""
[ -n "$BRAIN_DIR" ] && [ "$(cd "$BRAIN_DIR" 2>/dev/null && pwd -P)" = "$(cd "$HOME" && pwd -P)" ] && FIND_DEPTH="-maxdepth 4"

if [ -z "$BRAIN_DIR" ]; then
  bad "Папку второго мозга не нашёл (искал CLAUDE.md и memory/)"
  [ -n "$WS_ENV" ] && info "В профиле ikigai_env.json записана папка, но в ней нет ни CLAUDE.md, ни memory/"
  info "Укажи папку явно: bash <путь>/audit.sh <папка мозга>  — или запусти скилл ikigai-preflight, он запишет её в профиль"
  manual "Собери папку мозга — это Модуль 1, шаг 1"
else
  ok "Папка мозга: $BRAIN_DIR ($BRAIN_FROM)"
  [ -n "$FIND_DEPTH" ] && info "Мозг лежит прямо в домашней папке — вглубь смотрю только на 4 уровня"
  [ -f "$BRAIN_DIR/CLAUDE.md" ] && ok "CLAUDE.md есть — система знает правила работы с тобой" \
                               || { warn "Нет CLAUDE.md"; agentdo "создай CLAUDE.md в папке мозга"; }
  if [ -d "$BRAIN_DIR/memory" ]; then
    MEM_N=$(find "$BRAIN_DIR/memory" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
    if [ "$MEM_N" -ge 5 ]; then ok "Память: $MEM_N файлов — контекст собран"
    elif [ "$MEM_N" -ge 1 ]; then warn "Память: всего $MEM_N файлов — контекста мало, агент будет советовать 'среднему предпринимателю'"; agentdo "запусти сбор контекста (скилл founder-context-extractor)"
    else bad "Папка memory пустая"; agentdo "запусти скилл founder-context-extractor и собери контекст о себе"; fi
  else
    bad "Нет папки memory/ — мозгу негде помнить"; agentdo "создай memory/ и запусти founder-context-extractor"
  fi
  if [ -d "$BRAIN_DIR/.git" ]; then
    LAST_C="$(git -C "$BRAIN_DIR" log -1 --format='%cd' --date=short 2>/dev/null)"
    ok "Мозг под git, последнее сохранение: ${LAST_C:-неизвестно}"
  else
    warn "Мозг не под git — нет точек сохранения и отката"; agentdo "заведи git в папке мозга и настрой авто-коммиты"
  fi
fi

SKILLS_DIR="$HOME/.claude/skills"
if [ -d "$SKILLS_DIR" ]; then
  SK_N=$(find "$SKILLS_DIR" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
  if [ "$SK_N" -ge 10 ]; then ok "Скиллы: $SK_N штук — команда на месте"
  elif [ "$SK_N" -ge 1 ]; then warn "Скиллы: только $SK_N — пакет Модуля 1 поставлен не полностью"; agentdo "доставь скиллы из репозитория ikigai-ai-skills"
  else bad "Папка скиллов пустая"; agentdo "поставь пакет скиллов Модуля 1"; fi
  for must in orchestrator ikigai-provodnik; do
    [ -d "$SKILLS_DIR/$must" ] && ok "  скилл $must на месте" || warn "  нет скилла $must"
  done
  # техническая команда — ставится на ЭТАПЕ 0, до всякой стройки
  TEAM_MISS=""
  for t in cto secops devops code-reviewer anthropic-academy second-brain-audit; do
    [ -d "$SKILLS_DIR/$t" ] || TEAM_MISS="${TEAM_MISS:+$TEAM_MISS, }$t"
  done
  if [ -z "$TEAM_MISS" ]; then ok "  IT-команда на месте: cto, secops, devops, code-reviewer, academy, brain-audit"
  else bad "  Нет технической команды: $TEAM_MISS — сервер будет собирать некому проверять"
       agentdo "поставь технические скиллы из папки skills рядом с заданием в ~/.claude/skills/ (ЭТАП 0)"; fi
else
  bad "Скиллы не установлены (~/.claude/skills не существует)"; agentdo "поставь пакет скиллов Модуля 1"
fi

# =============================================================================
# БЛОК 4 — ЗАГОТОВКИ К СЕРВЕРУ (Файл доступа)
# =============================================================================
head1 "4. Заготовки к серверу"

SERVER_IP=""; SERVER_USER=""; SERVER_PORT="22"
HAS_BOT_TOKEN=0; HAS_USER_ID=0; USER_ID_VAL=""

is_placeholder() {
  case "$1" in
    ""|"<"*|*">"|"1.2.3.4"|"127.0.0.1"|"0.0.0.0"|"xxx"|"XXX"|"твой"*|"сюда"*) return 0 ;;
    *) return 1 ;;
  esac
}

if [ -f "$ACCESS_FILE" ]; then
  PERM="$(ls -l "$ACCESS_FILE" | cut -c1-10)"
  ok "Файл доступа найден: $ACCESS_FILE"
  if [ "$PERM" = "-rw-------" ]; then ok "Права на файл доступа правильные (600)"
  else warn "Права на файл доступа $PERM — должно быть -rw------- ; выполни: chmod 600 $ACCESS_FILE"; fi

  [ "$ACCESS_LEGACY_PATH" = "1" ] && { warn "Файл доступа лежит по старому пути — перенеси его в $ACCESS_NEW (brain-link detect скопирует сам)"; agentdo "запусти brain-link detect: он перенесёт файл доступа на новый путь ~/.config/brain/server_access"; }

  # читаем БЕЗ вывода значений; новые ключи §8, старые IP / LOGIN / PORT — запасной вариант с предупреждением
  akey() { grep -E "^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=" "$ACCESS_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d ' "'"'"''; }
  SERVER_IP="$(akey SERVER_IP)"; SERVER_USER="$(akey SERVER_USER)"; SP="$(akey SERVER_PORT)"
  OLD_KEYS=""
  [ -z "$SERVER_IP" ]   && SERVER_IP="$(akey IP)"     && [ -n "$SERVER_IP" ]   && OLD_KEYS="$OLD_KEYS IP→SERVER_IP"
  [ -z "$SERVER_USER" ] && SERVER_USER="$(akey LOGIN)" && [ -n "$SERVER_USER" ] && OLD_KEYS="$OLD_KEYS LOGIN→SERVER_USER"
  [ -z "$SP" ]          && SP="$(akey PORT)"           && [ -n "$SP" ]          && OLD_KEYS="$OLD_KEYS PORT→SERVER_PORT"
  [ -n "$OLD_KEYS" ] && { warn "В файле доступа старые ключи:$OLD_KEYS — переименуй (схема kit 2.1)"; agentdo "переименуй в файле доступа старые ключи:$OLD_KEYS (значения не показывай)"; }
  [ -n "$(akey CLAUDE_TOKEN)" ] && { warn "В файле доступа лежит CLAUDE_TOKEN — токен подписки там не хранится"; manual "Удали строку CLAUDE_TOKEN из файла доступа; токен на сервер передаётся шагом brain-link put-token claude (ты запускаешь сама)"; }
  [ -n "$SP" ] && SERVER_PORT="$SP"
  [ -z "$SERVER_USER" ] && SERVER_USER="root"
  grep -qE '^[[:space:]]*BOT_TOKEN[[:space:]]*=[[:space:]]*[0-9]+:' "$ACCESS_FILE" 2>/dev/null && HAS_BOT_TOKEN=1
  USER_ID_VAL="$(akey USER_ID)"; [ -z "$USER_ID_VAL" ] && USER_ID_VAL="$(akey OWNER_USER_ID)"
  case "$USER_ID_VAL" in ''|*[!0-9]*) HAS_USER_ID=0 ;; *) HAS_USER_ID=1 ;; esac

  if is_placeholder "$SERVER_IP"; then bad "IP сервера не вписан (или стоит заглушка)"; manual "Впиши в $ACCESS_FILE строку SERVER_IP=<IP от FoxCloud>"
  else ok "IP сервера вписан"; fi
  [ "$HAS_BOT_TOKEN" = "1" ] && ok "Токен Telegram-бота вписан" || { warn "Токена бота нет в Файле доступа"; manual "Создай бота у @BotFather и впиши BOT_TOKEN= в $ACCESS_FILE"; }
  [ "$HAS_USER_ID" = "1" ] && ok "Твой user_id вписан ($USER_ID_VAL)" || { warn "user_id не вписан"; manual "Напиши @userinfobot, получи число, впиши USER_ID= в $ACCESS_FILE"; }
else
  bad "Файла доступа нет — заготовки к серверу не собраны"
  info "Это тот самый чек-лист из чата: сервер, бот, user_id"
  manual "Создай файл ~/.config/brain/server_access (шаблон рядом: server_access.example; ключи SERVER_IP, SERVER_USER, SERVER_PORT, BOT_TOKEN, USER_ID)"
  manual "Закажи VPS на ru.foxcloud.net, кодовое слово «Икигай», Нидерланды, Ubuntu 24.04, 2 vCPU / 4 GB / 50 GB"
  manual "Создай бота у @BotFather → получи токен"
  manual "Узнай свой user_id у @userinfobot"
fi

# --- Живая проверка бота через Telegram API (токен на экран не попадает) ----
BOT_USERNAME=""
if [ "$HAS_BOT_TOKEN" = "1" ] && command -v curl >/dev/null 2>&1; then
  BT="$(grep -E '^[[:space:]]*BOT_TOKEN[[:space:]]*=' "$ACCESS_FILE" | head -1 | cut -d= -f2- | tr -d ' "'"'"'')"
  # адрес с токеном отдаём curl через stdin (-K -), чтобы токен не попал в список процессов
  RESP="$(printf 'url = "https://api.telegram.org/bot%s/getMe"\n' "$BT" | curl -s --max-time 15 -K - 2>/dev/null)"
  if printf '%s' "$RESP" | grep -q '"ok":true'; then
    BOT_USERNAME="$(printf '%s' "$RESP" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')"
    ok "Бот живой и отвечает Telegram: @${BOT_USERNAME}"
  else
    bad "Токен бота есть, но Telegram его не принял — токен неверный или бот удалён"
    manual "Перевыпусти токен у @BotFather (/mybots → твой бот → API Token)"
  fi
  unset BT
fi

# =============================================================================
# БЛОК 5 — СЕРВЕР
# =============================================================================
head1 "5. Сервер"

SRV_OK=0
# Ключ сервера — только закреплённый (brain-link keys кладёт его в ~/.config/brain/known_hosts).
# Нет закреплённого — проверяем по обычному ~/.ssh/known_hosts, но новый ключ молча не принимаем.
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=12 -o StrictHostKeyChecking=yes -p "$SERVER_PORT")
# путь в кавычках внутри значения: ssh сам делит значение -o по пробелам (папка пользователя с пробелом)
[ -s "$KNOWN_HOSTS" ] && SSH_OPTS+=(-o "UserKnownHostsFile=\"$KNOWN_HOSTS\"")
[ -f "$ADMIN_KEY" ] && SSH_OPTS+=(-i "$ADMIN_KEY")
SSH="ssh ${SSH_OPTS[*]}"
ssh_srv() { ssh "${SSH_OPTS[@]}" "$@"; }

if is_placeholder "$SERVER_IP"; then
  bad "Сервера пока нет — это главный недостающий кусок"
  info "Без сервера мозг живёт только пока открыт ноутбук"
else
  # после brain-link lockdown root закрыт — тогда ходим под brain
  for U in "$SERVER_USER" brain; do
    if ssh_srv "${U}@${SERVER_IP}" 'echo alive' >/dev/null 2>&1; then SERVER_USER="$U"; SRV_OK=1; break; fi
  done
  if [ "$SRV_OK" = "1" ]; then
    ok "Сервер отвечает, вход по ключу работает (пользователь $SERVER_USER)"
    [ -s "$KNOWN_HOSTS" ] && ok "Ключ сервера закреплён (~/.config/brain/known_hosts)" || warn "Ключ сервера не закреплён в ~/.config/brain/known_hosts — это делает brain-link keys"
  else
    warn "Сервер не пускает по ключу (или ключ сервера не закреплён)"
    info "Починить: шаг brain-link keys — он создаст ключи, закрепит ключ сервера и покажет одну команду"
    manual "Скажи Claude Code: «Запусти brain-link, шаг keys» — и выполни одну команду, которую он покажет (пароль root вводишь сама)"
  fi
fi

if [ "$SRV_OK" = "1" ]; then
  SRV_INFO="$(ssh_srv "${SERVER_USER}@${SERVER_IP}" 'bash -s' 2>/dev/null <<'REMOTE'
. /etc/os-release 2>/dev/null
echo "OS=$PRETTY_NAME"
echo "RAM=$(free -m 2>/dev/null | awk '/Mem:/{print $2}')"
echo "CPU=$(nproc 2>/dev/null)"
echo "DISK=$(df -BG --output=size / 2>/dev/null | tail -1 | tr -dc 0-9)"
id brain >/dev/null 2>&1 && echo "BRAINUSER=yes" || echo "BRAINUSER=no"
if [ -x /home/brain/.local/bin/claude ] || command -v claude >/dev/null 2>&1; then echo "CLAUDE=yes"; else echo "CLAUDE=no"; fi
# токен подписки: kit 2.1 — /etc/brain-bot/credentials/claude_token (root 0600); старая модель — env-файл в ~/.config
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
# ufw: только «ufw status» (от root или через brain-admin). systemctl is-active ufw врёт: юнит active и при выключенном файрволе.
# Нет ufw вовсе (контейнерный VPS) — UFW=none.
if [ "$(id -u)" = 0 ]; then
  if ! command -v ufw >/dev/null 2>&1; then echo "UFW=none"
  else ufw status 2>/dev/null | grep -q "Status: active" && echo "UFW=yes" || echo "UFW=no"; fi
else
  BAS=$(sudo -n brain-admin status 2>/dev/null)
  if printf '%s\n' "$BAS" | grep -qiE '^(ufw[: ]+active|status: active)'; then echo "UFW=yes"
  elif printf '%s\n' "$BAS" | grep -qiE '^(ufw[: ]+(inactive|not active)|status: inactive)'; then echo "UFW=no"
  else echo "UFW=unknown"; fi
fi
# --- для блока 8 (связка kit 2.1) ---
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
REMOTE
)"

  g(){ printf '%s' "$SRV_INFO" | grep -E "^$1=" | head -1 | cut -d= -f2-; }

  S_OS="$(g OS)"; S_RAM="$(g RAM)"; S_CPU="$(g CPU)"; S_DISK="$(g DISK)"

  case "$S_OS" in *"24.04"*) ok "ОС сервера: $S_OS" ;; *) warn "ОС сервера: ${S_OS:-неизвестно} — в ките Ubuntu 24.04 LTS" ;; esac
  [ "${S_RAM:-0}" -ge 3500 ] 2>/dev/null && ok "Память: ${S_RAM} МБ" || warn "Память: ${S_RAM:-?} МБ — по схеме нужно 4 ГБ"
  [ "${S_CPU:-0}" -ge 2 ] 2>/dev/null && ok "Ядер: $S_CPU" || warn "Ядер: ${S_CPU:-?} — по схеме нужно 2"
  [ "${S_DISK:-0}" -ge 40 ] 2>/dev/null && ok "Диск: ${S_DISK} ГБ" || warn "Диск: ${S_DISK:-?} ГБ — по схеме 50 ГБ"

  [ "$(g BRAINUSER)" = "yes" ] && ok "Отдельный пользователь brain создан (мозг живёт не под root)" \
      || { bad "Нет пользователя brain — сервер ещё не подготовлен"; agentdo "запусти brain-link, шаг harden (модуль 02)"; }

  if [ "$(g CLAUDE)" = "yes" ]; then ok "Claude Code установлен на сервере"
  else bad "На сервере нет Claude Code — мозгу нечем думать"; agentdo "запусти brain-link, шаг claude (официальный установщик под brain)"; fi

  if [ "$(g OAUTH)" = "yes" ]; then
    case "$(g OAUTHKIND)" in
      cred) ok "Токен подписки на сервере есть (/etc/brain-bot/credentials, kit 2.1)" ;;
      *)    ok "Токен подписки на сервере есть (env-файл старой модели)"; warn "Токен лежит в env-файле в ~brain/.config — в kit 2.1 он живёт в /etc/brain-bot/credentials"; agentdo "перенеси токен по-новому: brain-link put-token claude (я запущу сама), старый env-файл потом удали" ;;
    esac
    case "$(g OAUTHPERM)" in "600 root"|"600 brain"|"-rw------- root"|"-rw------- brain") ok "Права на файл с токеном 600 — правильно" ;;
      *) warn "Права на файл с токеном: $(g OAUTHPERM) — должно быть 600"; agentdo "поставь права 600 на файл с токеном подписки на сервере" ;; esac
  elif [ "$(g OAUTH)" = "unknown" ]; then
    info "Токен подписки отсюда не виден (вход под brain без brain-admin) — проверит brain-link verify"
  else
    bad "На сервере нет токена подписки — бот не сможет думать"
    manual "Запусти САМА в своём терминале: brain_link.py put-token claude — откроется вход в Claude, токен вводится скрыто и сразу уходит на сервер (в чат и в файл доступа не вставлять!)"
  fi

  [ "$(g APIKEY)" = "no" ] && ok "API-ключа на сервере нет — работает из подписки" \
      || { bad "На сервере есть ANTHROPIC_API_KEY — он ПЕРЕБИВАЕТ подписку, платежи пойдут по счётчику"; agentdo "убери ANTHROPIC_API_KEY с сервера (проверь /etc/environment, профили brain и юниты brain-*) — токен подписки остаётся только в /etc/brain-bot/credentials"; }

  [ "$(g BRAINMD)" = "yes" ] && ok "CLAUDE.md на сервере есть" || warn "На сервере нет CLAUDE.md"
  S_MEMN="$(g MEMN)"; S_HB="$(g HEARTBEAT)"
  if [ "${S_MEMN:-0}" -ge 5 ] 2>/dev/null; then ok "Копия памяти на сервере: $S_MEMN файлов"
  elif [ "${S_MEMN:-0}" -ge 1 ] 2>/dev/null; then warn "Копия памяти на сервере: всего $S_MEMN файлов"; agentdo "проверь синк: brain-link status, затем brain-link init (новый сервер) или adopt (старая модель)"
  else bad "На сервере нет памяти — бот отвечает вслепую"; agentdo "включи синк памяти: brain-link init (чистый сервер) или adopt (сервер по старой модели)"; fi

  S_UNIT="$(g UNIT)"
  if [ -n "$S_UNIT" ]; then
    ok "Сервис бота найден: $S_UNIT"
    [ "$(g UNITACTIVE)"  = "yes" ] && ok "  бот запущен прямо сейчас" || { bad "  бот НЕ запущен"; agentdo "подними сервис бота и разберись, почему он упал"; }
    [ "$(g UNITENABLED)" = "yes" ] && ok "  автозапуск после перезагрузки включён" || { warn "  автозапуск выключен"; agentdo "включи автозапуск сервиса бота"; }
    [ "$(g UNITRESTART)" = "yes" ] && ok "  сам поднимается после падения (Restart=always)" || { warn "  нет Restart=always"; agentdo "добавь Restart=always в сервис бота"; }
    [ "$S_UNIT" = "brain-bot.service" ] || { warn "  это не стандартный brain-bot kit 2.1"; agentdo "поставь стандартного бота: brain-link, шаг bot (старый будет выключен, не удалён)"; }
  else
    bad "Сервиса бота на сервере нет — бот ещё не собран"
    agentdo "запусти brain-link, шаг bot (модуль 03A)"
  fi

  if [ -n "$S_HB" ]; then ok "Сервер — копия, главная версия и бэкап (локальный git) — на компьютере; синк отмечается на сервере"
  elif [ "$(g BACKUP)" = "yes" ]; then warn "На сервере снапшоты старой модели — в kit 2.1 главная копия на компьютере"; agentdo "переведи на связку: brain-link adopt (снапшоты на сервере будут выключены, не удалены)"
  else warn "Синк с компьютера ещё не работал"; agentdo "включи связку: brain-link init или adopt, затем schedule"; fi
  case "$(g UFW)" in yes) ok "Файрвол включён" ;; unknown) info "Файрвол отсюда не виден (вход под brain) — проверит блок 8" ;; none) warn "На сервере нет ufw (похоже на контейнерный VPS) — закрой порты в панели хостера (модуль 08)" ;; *) warn "Файрвол выключен — его включает brain-link harden (модуль 05)" ;; esac

  # --- сверка с definition of done ---
  S_SKN="$(g SKILLSN)"
  if [ "${S_SKN:-0}" -ge 5 ] 2>/dev/null; then ok "Скиллы на сервере: $S_SKN — бот видит команду"
  else bad "На сервере нет скиллов ($S_SKN) — бот видит память, но не умеет ей пользоваться"; agentdo "скиллы едут синком из ~/.claude/skills в /home/brain/.claude/skills — проверь brain-link status"; fi

  if [ "$(g WHITELIST)" = "yes" ]; then ok "Белый список включён — бот отвечает только владельцу"
  else bad "У бота НЕТ белого списка — любой посторонний тратит твою подписку"; agentdo "поставь стандартного бота brain-link (шаг bot): он отвечает только по OWNER_ID из USER_ID"; fi

  # автокоммиты в kit 2.1 живут на компьютере (блок 3, auto-commit-backup); на сервере — только старая модель
  if [ -z "$S_HB" ]; then
    [ "$(g AUTOCOMMIT)" = "yes" ] && ok "Автокоммиты мозга на сервере настроены (старая модель)" \
        || info "Автокоммитов на сервере нет — в kit 2.1 история правок живёт в git на компьютере"
  fi

  [ "$(g BRIEF)" = "yes" ] && ok "Утренний брифинг стоит в расписании" \
      || { warn "Утреннего брифинга нет — это заодно проверка, что связка cron + бот + память жива"; agentdo "поставь утренний брифинг по расписанию (SETUP_MORNING_BRIEF)"; }

  [ "$(g TEAMKIT)" = "yes" ] && ok "IT-команда на сервере есть (точка входа — cto)" \
      || { warn "team-kit не установлен"; agentdo "поставь team-kit на сервер, точка входа — cto"; }
fi

# =============================================================================
# БЛОК 6 — ДВЕ ЖИВЫЕ ПРОВЕРКИ (главный смысл всего аудита)
# =============================================================================
head1 "6. Живые проверки"

ENGINE_OK=0; BRIDGE_OK=0

# 6.1 — думает ли мозг на сервере из подписки
if [ "$SRV_OK" = "1" ] && [ "$(printf '%s' "$SRV_INFO" | grep -c '^CLAUDE=yes')" = "1" ]; then
  printf '  %s·%s спрашиваю мозг на сервере (до 90 сек)…\n' "$DIM" "$D"
  ANSWER="$(ssh_srv "${SERVER_USER}@${SERVER_IP}" 'bash -s' <<'REMOTE'
CL=/home/brain/.local/bin/claude; [ -x "$CL" ] || CL=claude
if [ "$(id -u)" != 0 ]; then echo "NOT_ROOT"; exit 0; fi
if [ -s /etc/brain-bot/credentials/claude_token ]; then
  # kit 2.1: токен только у root. В argv его нет: файл открывает root как stdin, внутри sh -c токен читается
  # в переменную и уходит claude только окружением. Настройки и конфиг-папка — те же, что у бота.
  # kit 2.1 (RT-11): бот — brainbot, конфиг claude в /var/lib/brain-bot; ранние установки — brain и ~/.local/state
  RU=brain; CCD=/home/brain/.local/state/brain-bot/claude-config
  if id brainbot >/dev/null 2>&1 && [ -d /var/lib/brain-bot/claude-config ]; then RU=brainbot; CCD=/var/lib/brain-bot/claude-config; fi
  [ -d "$CCD" ] || CCD=/home/brain/.claude
  ST=/etc/brain-bot/claude_settings.json; [ -f "$ST" ] || ST=
  cd /tmp && runuser -u "$RU" -- env -i HOME=/home/brain LANG=C.UTF-8 PATH=/home/brain/.local/bin:/usr/local/bin:/usr/bin:/bin \
    CLAUDE_CONFIG_DIR="$CCD" sh -c 'IFS= read -r CLAUDE_CODE_OAUTH_TOKEN; export CLAUDE_CODE_OAUTH_TOKEN
      if [ -n "$2" ]; then exec timeout 80 "$1" -p "Ответь ровно одним словом: живой" --settings "$2" </dev/null
      else exec timeout 80 "$1" -p "Ответь ровно одним словом: живой" </dev/null; fi' sh "$CL" "$ST" \
    < /etc/brain-bot/credentials/claude_token 2>&1 | tail -3
  exit 0
fi
ENVF=$(grep -rlE "^CLAUDE_CODE_OAUTH_TOKEN=" /home/brain/.config/ 2>/dev/null | head -1)
if [ -z "$ENVF" ]; then echo "NO_ENV_FILE"; exit 0; fi
sudo -u brain -i bash -lc "unset ANTHROPIC_API_KEY; set -a; . '$ENVF'; set +a; cd /home/brain 2>/dev/null; timeout 80 claude -p 'Ответь ровно одним словом: живой'" 2>&1 | tail -3
REMOTE
)"
  if printf '%s' "$ANSWER" | grep -q 'NOT_ROOT'; then
    info "После lockdown вход root закрыт — мозг проверь из Telegram: напиши боту /status и любой вопрос"
  elif printf '%s' "$ANSWER" | grep -qi 'жив'; then
    ok "МОЗГ НА СЕРВЕРЕ ДУМАЕТ и отвечает из твоей подписки"
    ENGINE_OK=1
  elif printf '%s' "$ANSWER" | grep -qiE 'credit|balance|login|auth|subscription|invalid'; then
    bad "Мозг на сервере не пускает по подписке — токен протух или не тот"
    manual "Перевыпусти токен подписки: запусти САМА brain_link.py put-token claude"
  else
    warn "Мозг на сервере не ответил внятно — смотри модуль 08 «Если не взлетело»"
  fi
else
  info "Живую проверку мозга пропускаю — сервер или Claude Code на нём ещё не готовы"
fi

# 6.2 — соединён ли бот с этим мозгом (бот пишет тебе в Telegram)
if [ -n "$BOT_USERNAME" ] && [ "$HAS_USER_ID" = "1" ]; then
  printf '\n  Отправить тебе в Telegram проверочное сообщение от @%s? [Y/n] ' "$BOT_USERNAME"
  read -r ANS </dev/tty 2>/dev/null || ANS="n"
  case "${ANS:-Y}" in
    [Nn]*) info "Пропустил отправку" ;;
    *)
      BT="$(grep -E '^[[:space:]]*BOT_TOKEN[[:space:]]*=' "$ACCESS_FILE" | head -1 | cut -d= -f2- | tr -d ' "'"'"'')"
      SEND="$(printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$BT" | curl -s --max-time 15 -K - -X POST \
              --data-urlencode "chat_id=${USER_ID_VAL}" \
              --data-urlencode "text=Проверка связи от аудит-пака AI-Потока. Если ты видишь это сообщение — бот твой, токен верный, user_id верный." 2>/dev/null)"
      unset BT
      if printf '%s' "$SEND" | grep -q '"ok":true'; then
        ok "Бот написал тебе в Telegram — проверь, сообщение должно быть уже там"
        BRIDGE_OK=1
      else
        bad "Бот не смог тебе написать — скорее всего ты ещё не нажал /start в чате с ним"
        manual "Открой @${BOT_USERNAME} в Telegram и нажми Start, потом запусти аудит снова"
      fi ;;
  esac
else
  info "Проверку бота пропускаю — нужны токен бота и user_id"
fi

# =============================================================================
# БЛОК 7 — ВТОРОЙ МОЗГ ПО ЭТАЛОНУ (точки 13–23, kit 2.0)
# Меряем без модели: файлы, поля, расписание. «Работает ли» — проверяет
# скилл second-brain-audit поведением. Счёт этого блока идёт отдельно и не
# меняет ветку A/B/ГОТОВО выше. Точка, которой у человека нет смысла быть
# (например, расписание брифинга, когда брифинга-скрипта нет), — «не применимо»
# и в знаменатель не идёт: «X из N применимых».
# =============================================================================
head1 "7. Второй мозг по эталону (точки 13–23, kit 2.0)"

PT_YES=0; PT_PART=0; PT_NO=0; PT_NA=0
PT_ROWS=(); PT_FIX=()
# pt <номер> <есть|частично|нет|не применимо> <название> <что видно> [чем чинить]
pt() {
  case "$2" in
    есть)           PT_YES=$((PT_YES+1));   printf '  🟢 %s · %s — %s\n' "$1" "$3" "$4"; printf -- '- 🟢 %s · %s — %s\n' "$1" "$3" "$4" >>"$REPORT.tmp" ;;
    частично)       PT_PART=$((PT_PART+1)); printf '  🟡 %s · %s — %s\n' "$1" "$3" "$4"; printf -- '- 🟡 %s · %s — %s\n' "$1" "$3" "$4" >>"$REPORT.tmp" ;;
    "не применимо") PT_NA=$((PT_NA+1));     printf '  ⚪ %s · %s — %s\n' "$1" "$3" "$4"; printf -- '- ⚪ %s · %s — %s\n' "$1" "$3" "$4" >>"$REPORT.tmp" ;;
    *)              PT_NO=$((PT_NO+1));     printf '  🔴 %s · %s — %s\n' "$1" "$3" "$4"; printf -- '- 🔴 %s · %s — %s\n' "$1" "$3" "$4" >>"$REPORT.tmp" ;;
  esac
  PT_ROWS+=("| $1 | $3 | $2 | $4 |")
  case "$2" in есть|"не применимо") ;; *) [ -n "${5:-}" ] && PT_FIX+=("точка $1: $5") ;; esac
  return 0
}

# число знаков в файле (UTF-8); если локали нет — байты
chars_of() {
  local n=""
  for loc in en_US.UTF-8 C.UTF-8 ru_RU.UTF-8; do
    n="$(LC_ALL=$loc wc -m <"$1" 2>/dev/null | tr -d ' ')"
    case "$n" in ''|*[!0-9]*) n="" ;; *) break ;; esac
  done
  [ -z "$n" ] && n="$(wc -c <"$1" | tr -d ' ')"
  printf '%s' "$n"
}

BOM="$(printf '\357\273\277')"
# шапка файла (frontmatter): строки между первой «---» и следующей «---»; BOM и CR снимаются
fm_of() {
  LC_ALL=C awk -v bom="$BOM" '
    FNR==1 { l=$0; sub(/\r$/,"",l); if (index(l,bom)==1) l=substr(l,4); if (l !~ /^---[ \t]*$/) exit; next }
    { l=$0; sub(/\r$/,"",l) }
    l ~ /^[ \t]*---[ \t]*$/ { exit }
    { print l }' "$1" 2>/dev/null
}

PT_TMP="$(mktemp -d 2>/dev/null || mktemp -d -t brainaudit)"
TODAY="$(date +%Y-%m-%d)"
D14="$(date -v-14d +%Y-%m-%d 2>/dev/null || date -d '14 days ago' +%Y-%m-%d 2>/dev/null)"
BRIEF_PY="$HOME/morning_brief.py"

# --- скиллы набора: kit_version в шапке ИЛИ имя из списка скиллов репозитория -
# Свои скиллы человека (не из набора) в точку 15 не идут.
KIT_NAMES=" ai-strategist anthropic-academy anti-slop-filter auto-commit-backup claude-autoflow code-reviewer content-researcher copywriter-multiplatform craft-to-skill cto deep-build deep-focus design-critique devops dossier-checker dossier-maker first-principles founder-context-extractor gpt-context-export gtd-weekly ikigai-graduation ikigai-preflight ikigai-provodnik instagram-copywriter kpt-psychologist landing-architect linkedin-copywriter lms-builder lms-constructor lms-prototyper mail-calendar-kit memory-garden memory-upgrade model-switcher morning-brief one-thing-focus orchestrator oscar-hartmann partnerships personal-bot-upgrade project-splitter reels-content-factory researcher second-brain-architect second-brain-audit second-brain-os secops seo team-architect threads-copywriter toc-analyzer tone-of-voice-builder triz-solver website-builder weekly-distill "
SK_ALL=0; SK_KIT=0; SK_OWN=0; SK_NOHEAD=0; SK_NORU=0
KIT_WITH=0; KIT_WITHOUT=0; KIT_VERS=""; MB_KIT2=0
: >"$PT_TMP/sknames"
if [ -d "$SKILLS_DIR" ]; then
  for f in "$SKILLS_DIR"/*/SKILL.md; do
    [ -f "$f" ] || continue
    SK_ALL=$((SK_ALL+1))
    dir="$(basename "$(dirname "$f")")"
    HDR="$(fm_of "$f")"
    nm="$(printf '%s\n' "$HDR" | sed -n 's/^[[:space:]]*name:[[:space:]]*//p' | head -1 | tr -d "\"'" | sed 's/[[:space:]]*$//')"
    v="$(printf '%s\n' "$HDR" | sed -n 's/^[[:space:]]*kit_version:[[:space:]]*//p' | head -1 | tr -d "\"' ")"
    INKIT=0
    case "$KIT_NAMES" in *" $dir "*) INKIT=1 ;; esac
    [ -n "$nm" ] && case "$KIT_NAMES" in *" $nm "*) INKIT=1 ;; esac
    if [ -z "$v" ] && [ "$INKIT" = "0" ]; then SK_OWN=$((SK_OWN+1)); continue; fi
    SK_KIT=$((SK_KIT+1))
    printf '%s\n' "${nm:-$dir}" >>"$PT_TMP/sknames"
    if [ -n "$v" ]; then KIT_WITH=$((KIT_WITH+1)); KIT_VERS="$KIT_VERS
$v"; else KIT_WITHOUT=$((KIT_WITHOUT+1)); fi
    { [ "$dir" = "morning-brief" ] || [ "$nm" = "morning-brief" ]; } && case "$v" in 2*) MB_KIT2=1 ;; esac
    if ! printf '%s\n' "$HDR" | grep -qE '^[[:space:]]*name:' || ! printf '%s\n' "$HDR" | grep -qE '^[[:space:]]*description:'; then
      SK_NOHEAD=$((SK_NOHEAD+1))
    elif ! printf '%s' "$HDR" | LC_ALL=C grep -q "$(printf '[\320\321]')"; then
      SK_NORU=$((SK_NORU+1))
    fi
  done
fi
KIT_LIST="$(printf '%s\n' "$KIT_VERS" | sed '/^$/d' | sort | uniq -c | awk '{printf "%s%s у %s", (NR>1?", ":""), $2, $1}')"
if [ "$KIT_WITH" -gt 0 ]; then
  info "Версия набора (kit_version у скиллов набора): ${KIT_LIST}; без версии — $KIT_WITHOUT; своих скиллов (не из набора) — $SK_OWN"
elif [ "$SK_KIT" = "0" ]; then
  info "Версия набора: скиллов набора в ~/.claude/skills нет (своих скиллов — $SK_OWN)"
else
  info "Версия набора: ни у одного скилла набора нет kit_version — стоит набор до kit 2.0"
fi

if [ -z "$BRAIN_DIR" ]; then
  info "Папку мозга не нашёл — точки 13–23 мерить не на чем (см. блок 3)"
  for n in 13 14 15 16 17 18 19 20 21 22 23; do PT_ROWS+=("| $n | — | не проверено | нет папки мозга |"); done
else
  MEM="$BRAIN_DIR/memory"
  CMD="$BRAIN_DIR/CLAUDE.md"

  # Заметки сада — тот же знаменатель, что у garden_stage.py: без memory/sessions/,
  # без папок secret* / .secret* / .secrets, .git, .obsidian, node_modules, .trash.
  : >"$PT_TMP/notes"
  [ -d "$MEM" ] && find "$MEM" \( -type d \( -name .git -o -name .obsidian -o -name .secrets -o -name node_modules -o -name .trash \
      -o -iname 'secret*' -o -iname '.secret*' -o -path "$MEM/sessions" \) -prune \) -o \( -type f -name '*.md' -print0 \) \
      2>/dev/null >"$PT_TMP/notes"
  NOTES_N="$(tr -cd '\0' <"$PT_TMP/notes" | wc -c | tr -d ' ')"

  # --- 13. Проекты отделены от ядра ---------------------------------------
  # shellcheck disable=SC2086
  NESTED_N="$(find "$BRAIN_DIR" $FIND_DEPTH \( -name .git -o -name node_modules -o -name .claude \) -prune -o -name CLAUDE.md ! -path "$BRAIN_DIR/CLAUDE.md" -print 2>/dev/null | wc -l | tr -d ' ')"
  if [ -f "$MEM/PROJECTS.md" ] && [ "$NESTED_N" = "0" ]; then
    pt 13 есть "Проекты отделены от ядра" "есть memory/PROJECTS.md, вложенных CLAUDE.md нет (тест «что ты знаешь обо мне» из папки проекта — в скилле)"
  elif [ -f "$MEM/PROJECTS.md" ] || [ "$NESTED_N" = "0" ]; then
    D13=""; [ -f "$MEM/PROJECTS.md" ] || D13="нет memory/PROJECTS.md"
    [ "$NESTED_N" != "0" ] && D13="${D13:+$D13; }вложенных CLAUDE.md внутри мозга: $NESTED_N — проект видит всё ядро"
    pt 13 частично "Проекты отделены от ядра" "$D13" "memory-upgrade (черновик PROJECTS.md) и project-splitter (вынести проект из дерева мозга)"
  else
    pt 13 нет "Проекты отделены от ядра" "нет PROJECTS.md, вложенных CLAUDE.md внутри мозга: $NESTED_N" "memory-upgrade + project-splitter"
  fi

  # --- 14. Бюджет ядра: цель ~12 000 знаков, норма до 20 000, больше 40 000 — красное
  if [ -f "$CMD" ]; then
    C14="$(chars_of "$CMD")"; T14=$((C14 / 3))
    if   [ "$C14" -le 12000 ]; then pt 14 есть     "Бюджет ядра" "CLAUDE.md $C14 знаков ≈ $T14 токенов (цель ~12 000, норма до 20 000)"
    elif [ "$C14" -le 20000 ]; then pt 14 есть     "Бюджет ядра" "CLAUDE.md $C14 знаков ≈ $T14 токенов — в норме до 20 000, цель ~12 000 (можно ужать)"
    elif [ "$C14" -le 40000 ]; then pt 14 частично "Бюджет ядра" "CLAUDE.md $C14 знаков ≈ $T14 токенов — тяжелее нормы 20 000 (цель ~12 000)" "расслоить CLAUDE.md: подробности в memory/, в ядре строка со ссылкой (weekly-distill подскажет)"
    else                            pt 14 нет      "Бюджет ядра" "CLAUDE.md $C14 знаков ≈ $T14 токенов — больше 40 000, Claude Code сам предупреждает" "расслоить CLAUDE.md: подробности в memory/, в ядре строка со ссылкой"
    fi
  else
    pt 14 нет "Бюджет ядра" "нет CLAUDE.md — ядра нет" "second-brain-architect / memory-upgrade"
  fi

  # --- 15. Здоровье скиллов набора ----------------------------------------
  SK_DUP="$(sort "$PT_TMP/sknames" | uniq -d | tr '\n' ' ' | sed 's/ *$//')"
  SK_LOCAL="$(find "$BRAIN_DIR/.claude/skills" -mindepth 2 -maxdepth 2 -name SKILL.md 2>/dev/null | wc -l | tr -d ' ')"
  D15="скиллов набора $SK_KIT (своих, не из набора, — $SK_OWN, их не оцениваю); без шапки $SK_NOHEAD; без русских триггеров $SK_NORU; без kit_version $KIT_WITHOUT"
  [ -n "$SK_DUP" ] && D15="$D15; одно имя у двух папок: $SK_DUP"
  [ "$SK_LOCAL" != "0" ] && D15="$D15; второе место установки в папке мозга ($SK_LOCAL шт.)"
  FIX15_INSTALL="поставить или обновить скиллы из пака (папка skills/ рядом со скриптом; в выпускном паке — папки скиллов в корне, порядок — в его README)"
  if [ "$SK_KIT" = "0" ]; then
    pt 15 нет "Здоровье скиллов" "в ~/.claude/skills нет скиллов набора (своих — $SK_OWN)" "$FIX15_INSTALL"
  elif [ "$SK_NOHEAD" = "0" ] && [ "$SK_NORU" = "0" ] && [ "$SK_LOCAL" = "0" ] && [ -z "$SK_DUP" ] && [ "$KIT_WITHOUT" = "0" ]; then
    pt 15 есть "Здоровье скиллов" "$D15"
  else
    F15=""
    [ "$KIT_WITHOUT" != "0" ] && F15="$FIX15_INSTALL — у $KIT_WITHOUT скиллов набора нет kit_version, это версия до kit 2.0"
    if [ "$SK_NOHEAD" != "0" ] || [ "$SK_NORU" != "0" ] || [ -n "$SK_DUP" ] || [ "$SK_LOCAL" != "0" ]; then
      F15="${F15:+$F15; }шапки, дубли и вторая установка: переустановить из пака в ~/.claude/skills (memory-upgrade покажет список и сохранит твои правки)"
    fi
    pt 15 частично "Здоровье скиллов" "$D15" "$F15"
  fi

  # --- 16. Бэкап без личного в облаке -------------------------------------
  # У папки мозга облака нет; локальный git хранит ВСЁ, включая personal/; в облако не
  # пускает pre-push-замок; .gitignore исключает только секреты и мусор. Отсутствие
  # memory/ в .gitignore — не ошибка.
  if [ -d "$BRAIN_DIR/.git" ] && command -v git >/dev/null 2>&1; then
    CLOUD_RE='github\.com|gitlab\.|bitbucket\.org|codeberg\.org|gitee\.com|sr\.ht|dev\.azure\.com|visualstudio\.com|gitflic\.ru|gitverse\.ru|huggingface\.co'
    CLOUD16="$(git -C "$BRAIN_DIR" remote -v 2>/dev/null | grep -iE "$CLOUD_RE" | awk '{print $1}' | sort -u)"
    ALLR16="$(git -C "$BRAIN_DIR" remote 2>/dev/null | sort -u)"
    OTHER16=0
    for r in $ALLR16; do printf '%s\n' "$CLOUD16" | grep -qx "$r" || OTHER16=$((OTHER16+1)); done
    git -C "$BRAIN_DIR" remote -v 2>/dev/null | grep -qE '://[^/[:space:]]+:[^/@[:space:]]+@' && \
      warn "В адресе git-репозитория зашит пароль или токен — адрес не показываю; смени его и убери из адреса"
    HP16="$(git -C "$BRAIN_DIR" rev-parse --git-path hooks 2>/dev/null)"
    case "$HP16" in /*) ;; '') HP16="$BRAIN_DIR/.git/hooks" ;; *) HP16="$BRAIN_DIR/$HP16" ;; esac
    LOCK16=0
    if [ -f "$HP16/pre-push" ]; then
      if grep -q 'ikigai guard' "$HP16/pre-push" 2>/dev/null; then LOCK16=1; else LOCK16=2; fi
    fi
    SEC16="$(git -C "$BRAIN_DIR" ls-files -- .env '*.env' .secrets '*.session' 2>/dev/null | wc -l | tr -d ' ')"
    N16=""; [ "$OTHER16" != "0" ] && N16="; других адресов (свой сервер или диск, не облако): $OTHER16"
    [ "$SEC16" != "0" ] && N16="$N16; в git лежат секреты (.env / .secrets / *.session): $SEC16 — их место в .gitignore"
    if [ -z "$CLOUD16" ]; then
      if [ "$SEC16" = "0" ]; then
        pt 16 есть "Бэкап без личного в облаке" "у мозга нет облачного адреса — локальный git хранит всё, включая personal/, и никуда не отправляет$N16"
      else
        pt 16 частично "Бэкап без личного в облаке" "облачного адреса нет$N16" "auto-commit-backup kit 2.0: .gitignore исключает секреты и мусор (.secrets/, .env, *.session, rag_db/, *.bak*)"
      fi
    else
      H16=0
      for r in $CLOUD16; do
        h="$(git -C "$BRAIN_DIR" log --remotes="$r" --oneline -- memory/personal memory/private memory/sessions .secrets 2>/dev/null | wc -l | tr -d ' ')"
        H16=$((H16 + ${h:-0}))
      done
      NC16="$(printf '%s\n' "$CLOUD16" | sed '/^$/d' | wc -l | tr -d ' ')"
      if [ "$H16" != "0" ]; then
        pt 16 нет "Бэкап без личного в облаке" "облачных адресов: $NC16; в облачных ветках есть личное (memory/personal, private, sessions, .secrets): коммитов $H16$N16" "auto-commit-backup kit 2.0, шаг 1: убрать облачный адрес у папки мозга и поставить замок pre-push; что делать с уже отправленной историей — решаешь ты"
      elif [ "$LOCK16" = "1" ] && [ "$SEC16" = "0" ]; then
        pt 16 есть "Бэкап без личного в облаке" "облачных адресов: $NC16; замок pre-push (ikigai guard) стоит, в облачных ветках личного нет (по последней синхронизации)$N16"
      else
        W16="облачных адресов: $NC16; в облачных ветках личного нет, но"
        if [ "$LOCK16" = "1" ]; then W16="$W16 замок стоит"; elif [ "$LOCK16" = "2" ]; then W16="$W16 pre-push свой, без метки ikigai guard — проверь, что он не пускает memory/"; else W16="$W16 замка pre-push нет — следующая отправка может унести личное"; fi
        pt 16 частично "Бэкап без личного в облаке" "$W16$N16" "auto-commit-backup kit 2.0: убрать облачный адрес у папки мозга или поставить замок pre-push; .gitignore — только секреты и мусор"
      fi
    fi
  else
    pt 16 нет "Бэкап без личного в облаке" "мозг не под git — бэкапа нет" "auto-commit-backup kit 2.0 (локальный git по умолчанию)"
  fi

  # --- 17. Специалисты вызываются -----------------------------------------
  TEAM17=0
  { find "$BRAIN_DIR" -maxdepth 3 -name TEAM.md -not -path '*/.git/*' 2>/dev/null; find "$SKILLS_DIR" -maxdepth 2 -name TEAM.md 2>/dev/null; } | grep -q . && TEAM17=1
  HOOK17=0
  for sf in "$BRAIN_DIR/.claude/settings.json" "$BRAIN_DIR/.claude/settings.local.json" "$HOME/.claude/settings.json"; do
    [ -f "$sf" ] && grep -q 'UserPromptSubmit' "$sf" 2>/dev/null && HOOK17=1
  done
  if   [ "$TEAM17" = "1" ] && [ "$HOOK17" = "1" ]; then pt 17 есть "Специалисты вызываются" "TEAM.md и хук-диспетчер есть (вызывается ли скилл на деле — проверка фразами в скилле second-brain-audit)"
  elif [ "$TEAM17" = "1" ] || [ "$HOOK17" = "1" ]; then pt 17 частично "Специалисты вызываются" "$([ "$TEAM17" = 1 ] && echo 'TEAM.md есть, хука-диспетчера нет' || echo 'хук есть, TEAM.md нет')" "orchestrator kit 2.0: TEAM.md с русскими триггерами + хук"
  else pt 17 нет "Специалисты вызываются" "нет TEAM.md и хука — специалистов упоминают, а не вызывают" "orchestrator kit 2.0"
  fi

  # --- 18. Сад: stage в шапке у ≥90% заметок ------------------------------
  # Считаем только поле в шапке (между первыми ---), с отступом и без: ^\s*stage:
  if [ "${NOTES_N:-0}" -gt 0 ]; then
    ST18="$(xargs -0 env LC_ALL=C awk -v bom="$BOM" '
      FNR==1 { inh=0; done=0; l=$0; sub(/\r$/,"",l); if (index(l,bom)==1) l=substr(l,4); if (l ~ /^---[ \t]*$/) inh=1; else done=1; next }
      done { next }
      { l=$0; sub(/\r$/,"",l) }
      l ~ /^[ \t]*---[ \t]*$/ { done=1; next }
      inh && l ~ /^[ \t]*stage:/ { print FILENAME; done=1 }' <"$PT_TMP/notes" 2>/dev/null | wc -l | tr -d ' ')"
    P18=$(( ST18 * 100 / NOTES_N ))
    if   [ "$P18" -ge 90 ]; then pt 18 есть     "Сад: стадии заметок" "stage: в шапке у $ST18 из $NOTES_N заметок ($P18%; без sessions/ и секретного)"
    elif [ "$ST18" -gt 0 ]; then pt 18 частично "Сад: стадии заметок" "stage: в шапке у $ST18 из $NOTES_N заметок ($P18%), норма ≥90%" "memory-garden (garden_stage.py) через memory-upgrade"
    else                         pt 18 нет      "Сад: стадии заметок" "stage: в шапке нет ни у одной из $NOTES_N заметок" "memory-garden (garden_stage.py) через memory-upgrade"
    fi
  else
    pt 18 нет "Сад: стадии заметок" "в memory/ нет заметок" "собрать память (founder-context-extractor), потом memory-garden"
  fi

  # --- 19. Граф: связано ≥50% ---------------------------------------------
  # Связь — [[имя]] / [[name-из-шапки]] или markdown-ссылка ](путь.md)
  GRAPH="$HOME/.claude/graph/memory_graph.html"
  P19=0; L19=0
  LINK_RE='\[\[|\]\([^)]*\.md[)#]'
  if [ "${NOTES_N:-0}" -gt 0 ]; then
    {
      xargs -0 grep -hoE '\[\[[^]|#]+' <"$PT_TMP/notes" 2>/dev/null | sed -e 's/^\[\[//' -e 's/\.md$//'
      xargs -0 grep -hoE '\]\([^)]*\.md[)#]' <"$PT_TMP/notes" 2>/dev/null | sed -e 's/^](//' -e 's/[)#]$//' -e 's/\.md$//' -e 's/.*\///'
    } | sed -e 's/[[:space:]]*$//' -e 's/^[[:space:]]*//' | sort -u >"$PT_TMP/targets"
    # без исходящих ссылок; из них считаем тех, на кого ссылаются по имени файла или name: из шапки
    xargs -0 grep -LE "$LINK_RE" <"$PT_TMP/notes" >"$PT_TMP/unlinked" 2>/dev/null
    xargs -0 grep -m1 -H -E '^[[:space:]]*name:' <"$PT_TMP/notes" >"$PT_TMP/names" 2>/dev/null
    R19="$(awk -v T="$PT_TMP/targets" -v N="$PT_TMP/names" -v U="$PT_TMP/unlinked" '
      FILENAME==T { t[$0]=1; next }
      FILENAME==N { if (match($0, /:[[:space:]]*name:[[:space:]]*/)) { k=substr($0,1,RSTART-1); v=substr($0,RSTART+RLENGTH); gsub(/["\047]/,"",v); sub(/[[:space:]]+$/,"",v); nm[k]=v }; next }
      FILENAME==U { u++; b=$0; sub(/.*\//,"",b); sub(/\.md$/,"",b); if ((b in t) || ((($0) in nm) && (nm[$0] in t))) r++ }
      END { printf "%d %d", u, r }' "$PT_TMP/targets" "$PT_TMP/names" "$PT_TMP/unlinked")"
    U19="${R19% *}"; R19="${R19#* }"
    L19=$(( NOTES_N - ${U19:-0} + ${R19:-0} ))
    P19=$(( L19 * 100 / NOTES_N ))
  fi
  G19="нет"; [ -f "$GRAPH" ] && G19="есть"
  D19="граф ~/.claude/graph/memory_graph.html: $G19; связано ≈$P19% заметок ($L19 из ${NOTES_N:-0}; ссылки [[…]] и ](….md); точно — build_memory_graph.py --stats)"
  if   [ "$G19" = "есть" ] && [ "$P19" -ge 50 ]; then pt 19 есть "Граф связей" "$D19"
  elif [ "$G19" = "есть" ] || [ "$P19" -ge 50 ]; then pt 19 частично "Граф связей" "$D19" "memory-garden (build_memory_graph.py); связи добавляет weekly-distill"
  else pt 19 нет "Граф связей" "$D19" "memory-garden (build_memory_graph.py) + weekly-distill"
  fi

  # --- 20. Правило двойной ошибки -----------------------------------------
  R20=0; [ -f "$CMD" ] && LC_ALL=C grep -qE '(Д|д)войн.{0,40}ошибк' "$CMD" 2>/dev/null && R20=1
  F20="$( [ -d "$MEM" ] && find "$MEM" -name 'feedback_*.md' -not -path '*/secret*' 2>/dev/null | wc -l | tr -d ' ')"; F20="${F20:-0}"
  if   [ "$R20" = "1" ] && [ "$F20" -gt 0 ]; then pt 20 есть "Правило двойной ошибки" "правило в CLAUDE.md есть, feedback-файлов: $F20"
  elif [ "$R20" = "1" ] || [ "$F20" -gt 0 ]; then pt 20 частично "Правило двойной ошибки" "$([ "$R20" = 1 ] && echo 'правило в CLAUDE.md есть, feedback-файлов нет' || echo "feedback-файлов $F20, а правила в CLAUDE.md нет")" "memory-upgrade: раздел «Правило двойной ошибки» в CLAUDE.md"
  else pt 20 нет "Правило двойной ошибки" "ни правила, ни feedback-файлов — система не учится на поправках" "memory-upgrade: раздел «Правило двойной ошибки» в CLAUDE.md"
  fi

  # --- 21. Журнал обещаний читается брифингом -----------------------------
  # Читатель — скрипт брифинга ~/morning_brief.py (там должно быть слово commitments).
  # Скрипта нет (брифинг без бота) — читает сам скилл morning-brief kit 2.0, проверка скрипта не применима.
  C21=0; [ -f "$MEM/commitments.md" ] && C21=1
  OPEN21=0; [ "$C21" = "1" ] && OPEN21="$(grep -cE '\|[[:space:]]*open[[:space:]]*\|' "$MEM/commitments.md" 2>/dev/null | tr -d ' ')"
  if [ -f "$BRIEF_PY" ]; then
    B21=0; grep -q 'commitments' "$BRIEF_PY" 2>/dev/null && B21=1
    if   [ "$C21" = "1" ] && [ "$B21" = "1" ]; then pt 21 есть "Журнал обещаний" "memory/commitments.md есть (открытых: ${OPEN21:-0}), ~/morning_brief.py его читает"
    elif [ "$C21" = "1" ]; then pt 21 частично "Журнал обещаний" "memory/commitments.md есть, но ~/morning_brief.py его не читает" "SETUP_MORNING_BRIEF kit 2.0, шаг 3: блок «Обещал — не закрыто» в скрипте брифинга"
    elif [ "$B21" = "1" ]; then pt 21 частично "Журнал обещаний" "~/morning_brief.py умеет читать обещания, а файла memory/commitments.md нет" "memory-upgrade создаст memory/commitments.md"
    else pt 21 нет "Журнал обещаний" "нет memory/commitments.md, и ~/morning_brief.py его не читает" "memory-upgrade + SETUP_MORNING_BRIEF kit 2.0"
    fi
  elif [ "$MB_KIT2" = "1" ]; then
    if [ "$C21" = "1" ]; then pt 21 есть "Журнал обещаний" "memory/commitments.md есть (открытых: ${OPEN21:-0}); скрипта брифинга нет — журнал читает скилл morning-brief kit 2.0 (проверка скрипта не применима)"
    else pt 21 нет "Журнал обещаний" "нет memory/commitments.md (скрипта брифинга нет — это нормально, читает скилл morning-brief kit 2.0)" "memory-upgrade создаст memory/commitments.md"
    fi
  else
    if [ "$C21" = "1" ]; then pt 21 частично "Журнал обещаний" "memory/commitments.md есть, но читать его некому: нет ни ~/morning_brief.py, ни скилла morning-brief kit 2.0" "поставить morning-brief kit 2.0 из пака"
    else pt 21 нет "Журнал обещаний" "нет memory/commitments.md и брифинга kit 2.0" "memory-upgrade + morning-brief kit 2.0"
    fi
  fi

  # --- 22. Distill живой ---------------------------------------------------
  DD="$MEM/distill"
  if [ -d "$DD" ] && ls "$DD"/*.md >/dev/null 2>&1; then
    LAST22="$(ls "$DD"/*.md 2>/dev/null | sed -nE 's/.*([0-9]{4}-[0-9]{2}-[0-9]{2}).*/\1/p' | sort | tail -1)"
    FRESH22=0
    [ -n "$LAST22" ] && [ -n "$D14" ] && [ ! "$LAST22" \< "$D14" ] && FRESH22=1
    [ "$FRESH22" = "0" ] && [ -n "$(find "$DD" -name '*.md' -mtime -14 2>/dev/null | head -1)" ] && FRESH22=1
    if [ "$FRESH22" = "1" ]; then pt 22 есть "Дистилляция живая" "последняя: ${LAST22:-свежий файл} (норма — не старше 14 дней)"
    else pt 22 частично "Дистилляция живая" "последняя: ${LAST22:-дата не видна} — старше 14 дней" "weekly-distill по пятницам (gtd-weekly вызывает его в конце обзора)"; fi
  else
    pt 22 нет "Дистилляция живая" "нет memory/distill/ с файлами" "weekly-distill"
  fi

  # --- 23. Расписание переживает сон --------------------------------------
  # Брифинг-скрипт ~/morning_brief.py есть — он обязан стоять в launchd / systemd timer.
  # Нет ни скрипта, ни задачи в расписании (брифинг вызывают словами) — не применимо.
  HAS_PY23=0; [ -f "$BRIEF_PY" ] && HAS_PY23=1
  CRON23=0; crontab -l 2>/dev/null | grep -v '^[[:space:]]*#' | grep -qiE 'brief|morning|брифинг' && CRON23=1
  case "$OS_NAME" in
    Darwin)
      LA23="$(ls "$HOME/Library/LaunchAgents/" 2>/dev/null | grep -iE '^com\.ikigai\..*(brief|morning)' | head -1)"
      [ -z "$LA23" ] && LA23="$(ls "$HOME/Library/LaunchAgents/" 2>/dev/null | grep -iE '(brief|morning).*\.plist$' | head -1)"
      if   [ -n "$LA23" ] && [ "$CRON23" = "0" ]; then pt 23 есть "Расписание переживает сон" "брифинг в launchd: $LA23"
      elif [ -n "$LA23" ]; then pt 23 частично "Расписание переживает сон" "брифинг в launchd ($LA23), но в cron тоже — будет дубль" "SETUP_MORNING_BRIEF kit 2.0, шаг 4: убрать строку брифинга из cron"
      elif [ "$CRON23" = "1" ]; then pt 23 частично "Расписание переживает сон" "брифинг только в cron — пропускается, когда Mac спит" "SETUP_MORNING_BRIEF kit 2.0, шаг 4: перенести на launchd"
      elif [ "$HAS_PY23" = "1" ]; then pt 23 нет "Расписание переживает сон" "~/morning_brief.py есть, а в расписании его нет — утром брифинг не придёт" "SETUP_MORNING_BRIEF kit 2.0, шаг 4 (launchd)"
      else pt 23 "не применимо" "Расписание переживает сон" "брифинг не настроен как скрипт (нет ~/morning_brief.py и задачи в расписании) — будить нечего"; fi ;;
    Linux)
      TM23=0; systemctl --user list-timers --all --no-pager 2>/dev/null | grep -qiE 'brief|morning' && TM23=1
      systemctl list-timers --all --no-pager 2>/dev/null | grep -qiE 'brief|morning' && TM23=1
      if   [ "$TM23" = "1" ]; then pt 23 есть "Расписание переживает сон" "брифинг в systemd timer (нужен Persistent=true)"
      elif [ "$CRON23" = "1" ]; then pt 23 есть "Расписание переживает сон" "брифинг в cron — на сервере допустимо (сервер не спит)"
      elif [ "$HAS_PY23" = "1" ]; then pt 23 нет "Расписание переживает сон" "~/morning_brief.py есть, а в расписании его нет" "SETUP_MORNING_BRIEF kit 2.0"
      else pt 23 "не применимо" "Расписание переживает сон" "брифинг не настроен как скрипт — будить нечего"; fi ;;
    *)
      PT_ROWS+=("| 23 | Расписание переживает сон | не проверено | на Windows — audit.ps1 |") ;;
  esac
fi
rm -rf "$PT_TMP" 2>/dev/null

PT_APPL=$((PT_YES + PT_PART + PT_NO))
say ""
if [ -n "$BRAIN_DIR" ]; then
  say "  Эталон 13–23: есть $PT_YES · частично $PT_PART · нет $PT_NO · не применимо $PT_NA → $PT_YES из $PT_APPL применимых"
else say "  Эталон 13–23: не проверено — нет папки мозга"; fi
info "Работает ли это на деле (тест из папки проекта, вызов скиллов фразами) — проверяет скилл second-brain-audit"
[ $((PT_PART+PT_NO)) -gt 0 ] && info "Почти всё это закрывает один скилл memory-upgrade — он покажет план и без «делай» ничего не меняет"

# =============================================================================
# БЛОК 8 — СВЯЗКА «КОМПЬЮТЕР — МАСТЕРСКАЯ, СЕРВЕР — БАЗА» (kit 2.1, brain-link)
# Отдельный счёт, как у блока 7: ветку A/B/ГОТОВО выше не меняет.
# Серверные точки берутся из того же ssh-запроса блока 5 (поля LK_*).
# =============================================================================
head1 "8. Связка компьютер ↔ сервер (kit 2.1)"

LK_YES=0; LK_PART=0; LK_NO=0; LK_ROWS=(); LK_FIX=()
lk() { # <есть|частично|нет> <название> <что видно> [чем чинить]
  case "$1" in
    есть)     LK_YES=$((LK_YES+1));   printf '  🟢 %s — %s\n' "$2" "$3"; printf -- '- 🟢 %s — %s\n' "$2" "$3" >>"$REPORT.tmp" ;;
    частично) LK_PART=$((LK_PART+1)); printf '  🟡 %s — %s\n' "$2" "$3"; printf -- '- 🟡 %s — %s\n' "$2" "$3" >>"$REPORT.tmp" ;;
    *)        LK_NO=$((LK_NO+1));     printf '  🔴 %s — %s\n' "$2" "$3"; printf -- '- 🔴 %s — %s\n' "$2" "$3" >>"$REPORT.tmp" ;;
  esac
  LK_ROWS+=("| $2 | $1 | $3 |")
  case "$1" in есть) ;; *) [ -n "${4:-}" ] && LK_FIX+=("$2: $4") ;; esac
  return 0
}
CFG_BRAIN="$HOME/.config/brain"

# 8.1 расписание синка
case "$OS_NAME" in
  Darwin)
    if [ -f "$HOME/Library/LaunchAgents/com.ikigai.brain-sync.plist" ]; then
      if launchctl print "gui/$(id -u)/com.ikigai.brain-sync" >/dev/null 2>&1; then lk есть "Расписание синка" "launchd com.ikigai.brain-sync загружен (каждые 5 минут)"
      else lk частично "Расписание синка" "plist есть, но в launchd не загружен" "brain-link schedule"; fi
    else lk нет "Расписание синка" "нет launchd com.ikigai.brain-sync" "brain-link schedule"; fi ;;
  MINGW*|MSYS*|CYGWIN*)
    if MSYS_NO_PATHCONV=1 schtasks.exe /Query /TN "Ikigai brain-sync" >/dev/null 2>&1; then lk есть "Расписание синка" "задача Планировщика «Ikigai brain-sync»"
    else lk нет "Расписание синка" "задачи «Ikigai brain-sync» нет" "brain-link schedule"; fi ;;
  *) lk частично "Расписание синка" "на этой системе расписание ставится вручную (systemd user timer)" "brain-link schedule — для Mac и Windows" ;;
esac

# 8.2 синк свежий (sync_status.json не старше 15 минут) и 8.3 нет паузы
ST_JSON="$CFG_BRAIN/sync_status.json"
if [ -f "$ST_JSON" ]; then
  LAST_OK="$(sed -n 's/.*"last_success_epoch":[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$ST_JSON" | head -1)"
  FAILS="$(sed -n 's/.*"consecutive_failures":[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$ST_JSON" | head -1)"
  AGE=$(( $(date +%s) - ${LAST_OK:-0} ))
  if [ -n "$LAST_OK" ] && [ "$AGE" -le 900 ] && [ "${FAILS:-0}" = "0" ]; then lk есть "Синк свежий" "последний успешный синк $((AGE/60)) мин назад"
  elif [ -n "$LAST_OK" ] && [ "$AGE" -le 86400 ]; then lk частично "Синк свежий" "последний успешный синк $((AGE/60)) мин назад, ошибок подряд: ${FAILS:-0}" "brain-link status — там причина; модуль 08"
  else lk нет "Синк свежий" "успешного синка нет больше суток (ошибок подряд: ${FAILS:-?})" "brain-link status, затем модуль 08"; fi
else lk нет "Синк свежий" "синк ещё ни разу не запускался" "brain-link init / adopt, затем schedule"; fi
if [ -f "$CFG_BRAIN/sync.pause" ]; then lk частично "Синк не на паузе" "стоит пауза (sync.pause)" "brain-link resume, когда закончишь массовую правку"
else lk есть "Синк не на паузе" "паузы нет"; fi

# 8.4 ключ сервера закреплён
if [ -s "$KNOWN_HOSTS" ]; then lk есть "Ключ сервера закреплён" "~/.config/brain/known_hosts"
else lk нет "Ключ сервера закреплён" "нет ~/.config/brain/known_hosts — подмену сервера никто не заметит" "brain-link keys"; fi

# 8.5 нет пароля в скриптах и выключенной проверки ключа сервера (шаблоны собраны по частям,
# чтобы этот файл сам не попадал под поиск)
# ловим и вариант через «=», и через пробел (так пишут в ~/.ssh/config), с кавычками и без
PAT_PASS="ssh""pass"; PAT_NOHOST="StrictHostKeyChecking([[:space:]]*=[[:space:]]*|[[:space:]]+)[\"']?""no"
WHERE85=()
for f in "$HOME/Library/LaunchAgents"/*.plist "$HOME/.ssh/config" "$CFG_BRAIN"/*.ps1; do
  [ -f "$f" ] && grep -qiE "$PAT_PASS|$PAT_NOHOST" "$f" 2>/dev/null && WHERE85+=("$(basename "$f")")
done
crontab -l 2>/dev/null | grep -v '^[[:space:]]*#' | grep -qiE "$PAT_PASS|$PAT_NOHOST" && WHERE85+=("crontab")
if [ -n "$BRAIN_DIR" ]; then
  while IFS= read -r f; do WHERE85+=("${f#$BRAIN_DIR/}"); done < <(find "$BRAIN_DIR" -maxdepth 4 \( -name .git -o -name node_modules \) -prune -o \
      -type f \( -name '*.sh' -o -name '*.py' -o -name '*.plist' -o -name '*.ps1' \) -print 2>/dev/null \
      | head -500 | while IFS= read -r f; do grep -qiE "$PAT_PASS|$PAT_NOHOST" "$f" 2>/dev/null && printf '%s\n' "$f"; done | head -5)
fi
if [ ${#WHERE85[@]} -eq 0 ]; then lk есть "Вход без пароля в скриптах" "пароль через $PAT_PASS и выключенная проверка ключа сервера не найдены"
else lk нет "Вход без пароля в скриптах" "найдено в: ${WHERE85[*]}" "заменить на вход по ключу и закреплённый known_hosts (brain-link keys); пароль из файлов убрать"; fi

# 8.6–8.15 — сервер
if [ "$SRV_OK" = "1" ]; then
  P=$(g LK_PRIVATE)
  [ -z "$(printf '%s' "$P" | tr -d ' ')" ] && lk есть "Личного на сервере нет" "personal/ private/ secret/ sessions/ не найдены" \
    || lk нет "Личного на сервере нет" "найдено: $P" "забрать домой: brain-link adopt --pull-private; удалить на сервере: sudo brain-admin remove-private"
  case "$(g UFW)" in yes) lk есть "Файрвол" "ufw active" ;; unknown) lk частично "Файрвол" "отсюда не видно (вход под brain)" "sudo brain-admin status" ;;
    none) lk частично "Файрвол" "ufw нет (контейнерный VPS?)" "файрвол в панели хостера, модуль 08" ;;
    *) lk нет "Файрвол" "ufw выключен" "brain-link harden" ;; esac
  [ "$(g LK_F2B)" = "active" ] && lk есть "fail2ban" "active" || lk нет "fail2ban" "$(g LK_F2B)" "brain-link harden"
  case "$(g LK_PWAUTH)" in
    no)  lk есть "Вход только по ключам" "PasswordAuthentication no" ;;
    yes) if [ "$(g LK_LOCKDOWN)" = "yes" ]; then lk нет "Вход только по ключам" "lockdown включён, а пароль всё ещё принимается" "модуль 08: проверить файлы в /etc/ssh/sshd_config.d"
         else lk частично "Вход только по ключам" "пароль ещё принимается — до lockdown так и должно быть" "brain-link lockdown после зелёного verify"; fi ;;
    *)   lk частично "Вход только по ключам" "не смог проверить" "brain-link verify" ;;
  esac
  # kit 2.1 (RT-11): бот — отдельный пользователь brainbot; под brain токены LoadCredential читает любой процесс brain
  if [ "$(g UNIT)" = "brain-bot.service" ] && [ "$(g UNITACTIVE)" = "yes" ] && [ "$(g UNITUSER)" = "brainbot" ]; then lk есть "Бот под brainbot" "brain-bot active, User=brainbot"
  elif [ "$(g UNIT)" = "brain-bot.service" ] && [ "$(g UNITUSER)" = "brain" ]; then lk нет "Бот под brainbot" "brain-bot под brain (ранняя установка): его токены читает любой процесс brain" "brain-link bot до lockdown — переведёт на brainbot (после lockdown — VNC-консоль, root: brain-link bot)"
  elif [ "$(g UNIT)" = "brain-bot.service" ]; then lk нет "Бот под brainbot" "brain-bot: active=$(g UNITACTIVE), User=$(g UNITUSER)" "brain-link bot"
  else lk нет "Бот под brainbot" "стандартного brain-bot нет" "brain-link bot"; fi
  case "$(g LK_CREDREAD)" in
    no)  lk есть "brain не читает токены бота" "/etc/brain-bot/credentials и /run/credentials/brain-bot.service закрыты для brain" ;;
    yes) lk нет "brain не читает токены бота" "brain читает токен бота — RT-11" "brain-link bot до lockdown (бот уйдёт под brainbot)" ;;
    *)   lk частично "brain не читает токены бота" "не смог проверить" "brain-link verify, пункт (ж)" ;;
  esac
  C=$(g LK_CREDS)
  if [ -z "$C" ]; then lk нет "Секреты бота 0600 root" "секретов в /etc/brain-bot/credentials нет (или не видно)" "brain-link put-token claude и put-token bot"
  elif printf '%s' "$C" | tr ';' '\n' | sed '/^$/d' | grep -vqE '^(600|-rw-------) root$'; then lk нет "Секреты бота 0600 root" "права: $C" "sudo brain-admin set-token … заново (ставит 0600 root)"
  else lk есть "Секреты бота 0600 root" "оба токена 0600 root"; fi
  [ "$(g APIKEY)" = "no" ] && lk есть "API-ключа нет" "ANTHROPIC_API_KEY на сервере не задан" || lk нет "API-ключа нет" "ANTHROPIC_API_KEY найден" "убрать отовсюду (модуль 02, шаг 3)"
  NOWL=$(date +%s); NOWS=$(g LK_NOW); SKEW=$(( ${NOWS:-0} - NOWL )); SKEW=${SKEW#-}
  if [ "$(g LK_NTP)" = "yes" ] && [ "$SKEW" -lt 60 ]; then lk есть "Часы" "NTP синхронизирован, расхождение ~${SKEW} с"
  else lk нет "Часы" "NTPSynchronized=$(g LK_NTP), расхождение ~${SKEW} с" "на сервере: sudo brain-admin timesync-restart"; fi
  DK=$(g LK_DISK)
  if [ "${DK:-0}" -lt 85 ] 2>/dev/null; then lk есть "Диск" "занято ${DK:-?}%"
  else lk нет "Диск" "занято ${DK:-?}% (порог 85%)" "почистить ~/.cache на сервере, старые журналы: модуль 08"; fi
else
  lk нет "Сервер по ключу" "нет входа по ключу — серверные проверки связки пропущены" "brain-link keys"
fi

LK_ALL=$((LK_YES + LK_PART + LK_NO))
say ""
say "  Связка kit 2.1: есть $LK_YES · частично $LK_PART · нет $LK_NO → $LK_YES из $LK_ALL"
info "Живьём (бот → inbox, правка → сервер, «красная команда») связку проверяет brain-link verify"

# =============================================================================
# ВЕРДИКТ
# =============================================================================
TOTAL=$((OK_N+WARN_N+FAIL_N))
PCT=0; [ "$TOTAL" -gt 0 ] && PCT=$(( OK_N * 100 / TOTAL ))

if   [ "$SRV_OK" != "1" ] && is_placeholder "$SERVER_IP"; then BRANCH="A"; BRANCH_TXT="Сервера пока нет. Твой путь: заказать VPS → brain-link (detect → … → lockdown)."
elif [ "$ENGINE_OK" = "1" ] && [ "$BRIDGE_OK" = "1" ] && [ "$FAIL_N" -eq 0 ]; then BRANCH="ГОТОВО"; BRANCH_TXT="Система собрана: мозг на сервере думает, бот с ним соединён."
else BRANCH="B"; BRANCH_TXT="Сервер есть, но собран не до конца. Твой путь: закрыть красные пункты выше."
fi

printf '\n%s══════════════════════════════════════════════════════════════%s\n' "$B" "$D"
printf '%sИТОГ%s   🟢 %s   🟡 %s   🔴 %s      готовность ~%s%%\n' "$B" "$D" "$OK_N" "$WARN_N" "$FAIL_N" "$PCT"
printf '%sВЕТКА %s%s — %s\n' "$B" "$BRANCH" "$D" "$BRANCH_TXT"
if [ -n "$BRAIN_DIR" ]; then printf '%sЭТАЛОН 13–23%s   🟢 есть %s   🟡 частично %s   🔴 нет %s   ⚪ не применимо %s   → %s из %s применимых\n' "$B" "$D" "$PT_YES" "$PT_PART" "$PT_NO" "$PT_NA" "$PT_YES" "$PT_APPL"
else printf '%sЭТАЛОН 13–23%s   не проверено — нет папки мозга\n' "$B" "$D"; fi
printf '%sСВЯЗКА kit 2.1%s   🟢 %s   🟡 %s   🔴 %s   → %s из %s\n' "$B" "$D" "$LK_YES" "$LK_PART" "$LK_NO" "$LK_YES" "$LK_ALL"
printf '%s══════════════════════════════════════════════════════════════%s\n' "$B" "$D"

{
  printf '\n## Итог\n\n'
  printf -- '- Зелёных: %s · жёлтых: %s · красных: %s\n' "$OK_N" "$WARN_N" "$FAIL_N"
  printf -- '- Готовность: ~%s%%\n' "$PCT"
  printf -- '- Ветка: **%s** — %s\n' "$BRANCH" "$BRANCH_TXT"
  printf -- '- Мозг на сервере думает: %s\n' "$([ "$ENGINE_OK" = 1 ] && echo да || echo нет)"
  printf -- '- Бот соединён и пишет тебе: %s\n' "$([ "$BRIDGE_OK" = 1 ] && echo да || echo нет)"
  printf -- '- Второй мозг по эталону (13–23): есть %s · частично %s · нет %s · не применимо %s → **%s из %s применимых**\n' "$PT_YES" "$PT_PART" "$PT_NO" "$PT_NA" "$PT_YES" "$PT_APPL"
  printf '\n### Точки 13–23 эталона (kit 2.0)\n\n'
  printf '| № | Точка | Вердикт | Что видно |\n|---|---|---|---|\n'
  for r in "${PT_ROWS[@]}"; do printf '%s\n' "$r"; done
  printf -- '\n- Связка компьютер ↔ сервер (kit 2.1): есть %s · частично %s · нет %s → **%s из %s**\n' "$LK_YES" "$LK_PART" "$LK_NO" "$LK_YES" "$LK_ALL"
  printf '\n### Связка kit 2.1\n\n| Точка | Вердикт | Что видно |\n|---|---|---|\n'
  for r in "${LK_ROWS[@]}"; do printf '%s\n' "$r"; done
  printf '\nВерсия набора: %s\n' "$([ "$KIT_WITH" -gt 0 ] && echo "${KIT_LIST}; без версии — $KIT_WITHOUT" || { [ "$SK_KIT" = 0 ] && echo "скиллов набора нет" || echo "kit_version нет ни у одного скилла набора — набор до kit 2.0"; })"
} >>"$REPORT.tmp"

if [ ${#TODO_MANUAL[@]} -gt 0 ]; then
  printf '\n%sСДЕЛАТЬ РУКАМИ — это нельзя поручить агенту:%s\n' "$B" "$D"
  printf '\n### Сделать руками\n\n' >>"$REPORT.tmp"
  i=1; for t in "${TODO_MANUAL[@]}"; do printf '  %s. %s\n' "$i" "$t"; printf '%s. %s\n' "$i" "$t" >>"$REPORT.tmp"; i=$((i+1)); done
fi

if [ ${#TODO_AGENT[@]} -gt 0 ]; then
  printf '\n%sСДЕЛАЕТ АГЕНТ — готовый текст лежит в PROMPT_for_claude.txt%s\n' "$B" "$D"
  printf '\n### Сделает агент\n\n' >>"$REPORT.tmp"
  i=1; for t in "${TODO_AGENT[@]}"; do printf '  %s. %s\n' "$i" "$t"; printf '%s. %s\n' "$i" "$t" >>"$REPORT.tmp"; i=$((i+1)); done
fi

# --- генерируем персональный промпт ---------------------------------------
{
  printf 'Ты мой технический помощник. Я участница AI-Потока. Цель (kit 2.1): компьютер — мастерская,\n'
  printf 'сервер — база. Память и скиллы правлю на компьютере, сервер держит их копию и моего\n'
  printf 'Telegram-бота 24/7, бот думает из моей ПОДПИСКИ, а не по API-ключу. Ставит всё скилл brain-link.\n\n'
  printf 'Я прогнала аудит. Вот что он нашёл — отчёт целиком в файле:\n%s\n\n' "$REPORT"
  printf 'МОЯ ВЕТКА: %s — %s\n\n' "$BRANCH" "$BRANCH_TXT"
  if [ ${#TODO_AGENT[@]} -gt 0 ]; then
    printf 'ЗАКРОЙ ЭТИ ПУНКТЫ, по одному, после каждого — короткий отчёт мне:\n'
    i=1; for t in "${TODO_AGENT[@]}"; do printf '%s. %s\n' "$i" "$t"; i=$((i+1)); done
    printf '\n'
  fi
  if [ ${#LK_FIX[@]} -gt 0 ]; then
    printf 'СВЯЗКА КОМПЬЮТЕР ↔ СЕРВЕР (kit 2.1) — чинит скилл brain-link, по шагам:\n'
    i=1; for t in "${LK_FIX[@]}"; do printf '%s. %s\n' "$i" "$t"; i=$((i+1)); done
    printf '\n'
  fi
  if [ ${#PT_FIX[@]} -gt 0 ]; then
    printf 'ОТДЕЛЬНО — МОЙ ВТОРОЙ МОЗГ ПО ЭТАЛОНУ (точки 13–23, kit 2.0).\n'
    printf 'Запусти скилл second-brain-audit: он сверит меня со свежим эталоном и предложит план.\n'
    printf 'Что нашёл аудит:\n'
    i=1; for t in "${PT_FIX[@]}"; do printf '%s. %s\n' "$i" "$t"; i=$((i+1)); done
    printf 'Почти всё это ставит скилл memory-upgrade из того же репозитория. Применять — только\n'
    printf 'после моего «делай», ничего не удалять, сначала снимок.\n\n'
  fi
  printf 'ПРАВИЛА (соблюдай неукоснительно):\n'
  printf -- '- Никогда не выводи в чат пароли и токены. Только путь к файлу и факт наличия.\n'
  printf -- '- Токены на сервер передаю я сама шагом brain-link put-token (скрытый ввод); на сервере они\n'
  printf '  живут в /etc/brain-bot/credentials (root, 600). Не в коде, не в git, не в чате, не в файле доступа.\n'
  printf -- '- Личное (здоровье, семья, финансы) на сервер НЕ переносим.\n'
  printf -- '- Команду brain-link put-token claude (внутри — claude setup-token) я выполняю САМА в своём\n'
  printf '  терминале — ты её не запускаешь и её вывод не читаешь.\n'
  printf -- '- Ничего необратимого без моего явного «да».\n'
  printf -- '- Инструкции бери из кита novoselie-server-kit в репозитории\n'
  printf '  https://github.com/alexandrkuznetsovofficial-web/ikigai-ai-skills\n'
  printf '  и скилла brain-link (detect → keys → harden → claude → put-token → init/adopt → schedule →\n'
  printf '  bot → verify → lockdown); модули: 02 — сервер и Claude, 03A — бот, 04 — кто чем владеет,\n'
  printf '  05 — безопасность, 06 — приёмка, 08 — если не взлетело.\n\n'
  printf 'Сначала покажи мне план. Потом делай.\n'
  printf 'Когда закончишь — я снова запущу audit.sh, и он должен показать зелёным\n'
  printf '«МОЗГ НА СЕРВЕРЕ ДУМАЕТ» и «Бот написал тебе в Telegram».\n'
} >"$PROMPT_FILE"

{ printf '# Аудит AI-Поток — %s\n' "$(date '+%Y-%m-%d %H:%M')"; cat "$REPORT.tmp"; } >"$REPORT"
rm -f "$REPORT.tmp"

cat <<FINAL

${B}ЧТО ДЕЛАТЬ ПРЯМО СЕЙЧАС${D}

  1. Если выше есть пункты «сделать руками» — сделай их, это 15-20 минут.
  2. Открой Claude Code в папке своего мозга.
  3. Скопируй туда текст из файла:
     ${PROMPT_FILE}
  4. Когда агент закончит — запусти аудит снова: bash audit.sh

  Отчёт сохранён: ${REPORT}
  Застряла больше 20 минут — пиши в чат Потока, не жди следующей встречи.

FINAL
