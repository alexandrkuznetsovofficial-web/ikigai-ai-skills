#!/usr/bin/env bash
# =============================================================================
#  AI-ПОТОК · АУДИТ-ПАК
#  Проверяет, что у тебя уже собрано, и показывает, чего не хватает
#  до цели: мозг живёт на сервере 24/7, Telegram-бот говорит с ним из подписки.
#
#  Запуск:  bash audit.sh
#  Ничего не ломает и не устанавливает. Только смотрит и рассказывает.
# =============================================================================

VERSION="1.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT="$SCRIPT_DIR/audit_report.md"
PROMPT_FILE="$SCRIPT_DIR/PROMPT_for_claude.txt"
ACCESS_FILE="${BRAIN_ACCESS_FILE:-$HOME/.config/brain/server_access}"

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

BRAIN_DIR=""
for cand in "$PWD" "$HOME/brain" "$HOME/second-brain" "$HOME/Documents/brain" "$HOME/Documents/About me"; do
  if [ -f "$cand/CLAUDE.md" ] || [ -d "$cand/memory" ]; then BRAIN_DIR="$cand"; break; fi
done

if [ -z "$BRAIN_DIR" ]; then
  bad "Папку второго мозга не нашёл (искал CLAUDE.md и memory/)"
  info "Если она лежит в другом месте — запусти скрипт из неё: cd <папка> && bash <путь>/audit.sh"
  manual "Собери папку мозга — это Модуль 1, урок 1"
else
  ok "Папка мозга: $BRAIN_DIR"
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

  # читаем БЕЗ вывода значений
  SERVER_IP="$(grep -E '^[[:space:]]*SERVER_IP[[:space:]]*=' "$ACCESS_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d ' "'"'"'')"
  SERVER_USER="$(grep -E '^[[:space:]]*SERVER_USER[[:space:]]*=' "$ACCESS_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d ' "'"'"'')"
  SP="$(grep -E '^[[:space:]]*SERVER_PORT[[:space:]]*=' "$ACCESS_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d ' "'"'"'')"
  [ -n "$SP" ] && SERVER_PORT="$SP"
  [ -z "$SERVER_USER" ] && SERVER_USER="root"
  grep -qE '^[[:space:]]*BOT_TOKEN[[:space:]]*=[[:space:]]*[0-9]+:' "$ACCESS_FILE" 2>/dev/null && HAS_BOT_TOKEN=1
  USER_ID_VAL="$(grep -E '^[[:space:]]*(USER_ID|OWNER_USER_ID)[[:space:]]*=' "$ACCESS_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d ' "'"'"'')"
  case "$USER_ID_VAL" in ''|*[!0-9]*) HAS_USER_ID=0 ;; *) HAS_USER_ID=1 ;; esac

  if is_placeholder "$SERVER_IP"; then bad "IP сервера не вписан (или стоит заглушка)"; manual "Впиши в $ACCESS_FILE строку SERVER_IP=<IP от FoxCloud>"
  else ok "IP сервера вписан"; fi
  [ "$HAS_BOT_TOKEN" = "1" ] && ok "Токен Telegram-бота вписан" || { warn "Токена бота нет в Файле доступа"; manual "Создай бота у @BotFather и впиши BOT_TOKEN= в $ACCESS_FILE"; }
  [ "$HAS_USER_ID" = "1" ] && ok "Твой user_id вписан ($USER_ID_VAL)" || { warn "user_id не вписан"; manual "Напиши @userinfobot, получи число, впиши USER_ID= в $ACCESS_FILE"; }
else
  bad "Файла доступа нет — заготовки к серверу не собраны"
  info "Это тот самый чек-лист из чата: сервер, бот, user_id"
  manual "Создай файл ~/.config/brain/server_access (шаблон рядом: server_access.example)"
  manual "Закажи VPS на ru.foxcloud.net, кодовое слово «Икигай», Нидерланды, Ubuntu 24.04, 2 vCPU / 4 GB / 50 GB"
  manual "Создай бота у @BotFather → получи токен"
  manual "Узнай свой user_id у @userinfobot"
fi

# --- Живая проверка бота через Telegram API (токен на экран не попадает) ----
BOT_USERNAME=""
if [ "$HAS_BOT_TOKEN" = "1" ] && command -v curl >/dev/null 2>&1; then
  BT="$(grep -E '^[[:space:]]*BOT_TOKEN[[:space:]]*=' "$ACCESS_FILE" | head -1 | cut -d= -f2- | tr -d ' "'"'"'')"
  RESP="$(curl -s --max-time 15 "https://api.telegram.org/bot${BT}/getMe" 2>/dev/null)"
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
SSH="ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=12 -p $SERVER_PORT"

if is_placeholder "$SERVER_IP"; then
  bad "Сервера пока нет — это главный недостающий кусок"
  info "Без сервера мозг живёт только пока открыт ноутбук"
else
  if $SSH "${SERVER_USER}@${SERVER_IP}" 'echo alive' >/dev/null 2>&1; then
    ok "Сервер отвечает, вход по ключу работает"
    SRV_OK=1
  else
    warn "Сервер не пускает без пароля — не настроен вход по ключу"
    info "Починить одной командой:  ssh-copy-id -p $SERVER_PORT ${SERVER_USER}@${SERVER_IP}"
    info "(введёшь пароль один раз — дальше вход без пароля, и скрипт увидит сервер)"
    manual "Выполни: ssh-copy-id -p $SERVER_PORT ${SERVER_USER}@${SERVER_IP} и запусти аудит снова"
  fi
fi

if [ "$SRV_OK" = "1" ]; then
  SRV_INFO="$($SSH "${SERVER_USER}@${SERVER_IP}" '
    . /etc/os-release 2>/dev/null
    echo "OS=$PRETTY_NAME"
    echo "RAM=$(free -m 2>/dev/null | awk "/Mem:/{print \$2}")"
    echo "CPU=$(nproc 2>/dev/null)"
    echo "DISK=$(df -BG --output=size / 2>/dev/null | tail -1 | tr -dc 0-9)"
    id brain >/dev/null 2>&1 && echo "BRAINUSER=yes" || echo "BRAINUSER=no"
    if [ -x /usr/bin/claude ] || command -v claude >/dev/null 2>&1; then echo "CLAUDE=yes"; else
      if [ -x /home/brain/.local/bin/claude ]; then echo "CLAUDE=yes"; else echo "CLAUDE=no"; fi; fi
    ENVF=$(grep -rlE "^CLAUDE_CODE_OAUTH_TOKEN=" /home/brain/.config/ 2>/dev/null | head -1)
    if [ -n "$ENVF" ]; then echo "OAUTH=yes"; echo "OAUTHPERM=$(stat -c %a "$ENVF" 2>/dev/null)"; else echo "OAUTH=no"; fi
    grep -rqE "^ANTHROPIC_API_KEY=" /home/brain/.config/ /etc/environment 2>/dev/null && echo "APIKEY=yes" || echo "APIKEY=no"
    ( [ -f /home/brain/CLAUDE.md ] && echo "BRAINMD=yes" ) || echo "BRAINMD=no"
    echo "MEMN=$(find /home/brain/memory -name "*.md" 2>/dev/null | wc -l)"
    U=$(systemctl list-unit-files --no-pager --no-legend 2>/dev/null | awk "{print \$1}" | grep -iE "bot|brain|bridge" | head -1)
    if [ -n "$U" ]; then
      echo "UNIT=$U"
      systemctl is-active  "$U" >/dev/null 2>&1 && echo "UNITACTIVE=yes"  || echo "UNITACTIVE=no"
      systemctl is-enabled "$U" >/dev/null 2>&1 && echo "UNITENABLED=yes" || echo "UNITENABLED=no"
      systemctl cat "$U" 2>/dev/null | grep -q "Restart=always" && echo "UNITRESTART=yes" || echo "UNITRESTART=no"
    else echo "UNIT="; fi
    crontab -l 2>/dev/null | grep -cqE "backup|snapshot|rsync" && echo "BACKUP=yes" || echo "BACKUP=no"
    command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active" && echo "UFW=yes" || echo "UFW=no"
  ' 2>/dev/null)"

  g(){ printf '%s' "$SRV_INFO" | grep -E "^$1=" | head -1 | cut -d= -f2-; }

  S_OS="$(g OS)"; S_RAM="$(g RAM)"; S_CPU="$(g CPU)"; S_DISK="$(g DISK)"

  case "$S_OS" in *"24.04"*) ok "ОС сервера: $S_OS" ;; *) warn "ОС сервера: ${S_OS:-неизвестно} — в ките Ubuntu 24.04 LTS" ;; esac
  [ "${S_RAM:-0}" -ge 3500 ] 2>/dev/null && ok "Память: ${S_RAM} МБ" || warn "Память: ${S_RAM:-?} МБ — по схеме нужно 4 ГБ"
  [ "${S_CPU:-0}" -ge 2 ] 2>/dev/null && ok "Ядер: $S_CPU" || warn "Ядер: ${S_CPU:-?} — по схеме нужно 2"
  [ "${S_DISK:-0}" -ge 40 ] 2>/dev/null && ok "Диск: ${S_DISK} ГБ" || warn "Диск: ${S_DISK:-?} ГБ — по схеме 50 ГБ"

  [ "$(g BRAINUSER)" = "yes" ] && ok "Отдельный пользователь brain создан (мозг живёт не под root)" \
      || { bad "Нет пользователя brain — мозг ещё не переехал"; agentdo "создай на сервере пользователя brain и перенеси мозг (модуль 02)"; }

  if [ "$(g CLAUDE)" = "yes" ]; then ok "Claude Code установлен на сервере"
  else bad "На сервере нет Claude Code — мозгу нечем думать"; agentdo "поставь Claude Code на сервер: curl -fsSL https://claude.ai/install.sh | bash"; fi

  if [ "$(g OAUTH)" = "yes" ]; then
    ok "Токен подписки на сервере есть (CLAUDE_CODE_OAUTH_TOKEN)"
    [ "$(g OAUTHPERM)" = "600" ] && ok "Права на env-файл 600 — правильно" || { warn "Права на env-файл $(g OAUTHPERM), должно быть 600"; agentdo "поставь chmod 600 на env-файл с токеном"; }
  else
    bad "На сервере нет токена подписки — бот не сможет думать"
    manual "Выполни У СЕБЯ в терминале: claude setup-token  → получишь строку sk-ant-oat…"
    manual "Впиши её в $ACCESS_FILE строкой CLAUDE_TOKEN=… (в чат не вставлять!)"
    agentdo "перенеси CLAUDE_TOKEN на сервер в ~brain/.config/<имя>/env как CLAUDE_CODE_OAUTH_TOKEN, chmod 600"
  fi

  [ "$(g APIKEY)" = "no" ] && ok "API-ключа на сервере нет — работает из подписки" \
      || { bad "На сервере есть ANTHROPIC_API_KEY — он ПЕРЕБИВАЕТ подписку, платежи пойдут по счётчику"; agentdo "убери ANTHROPIC_API_KEY с сервера (проверь и /etc/environment) — должен остаться только CLAUDE_CODE_OAUTH_TOKEN"; }

  [ "$(g BRAINMD)" = "yes" ] && ok "CLAUDE.md на сервере есть" || warn "На сервере нет CLAUDE.md"
  S_MEMN="$(g MEMN)"
  if [ "${S_MEMN:-0}" -ge 5 ] 2>/dev/null; then ok "Память на сервере: $S_MEMN файлов — истина переехала"
  elif [ "${S_MEMN:-0}" -ge 1 ] 2>/dev/null; then warn "Память на сервере: $S_MEMN файлов — переехало не всё"; agentdo "долей память на сервер (модуль 02)"
  else bad "На сервере нет памяти — мозг пустой"; agentdo "перенеси память на сервер (модуль 02)"; fi

  S_UNIT="$(g UNIT)"
  if [ -n "$S_UNIT" ]; then
    ok "Сервис бота найден: $S_UNIT"
    [ "$(g UNITACTIVE)"  = "yes" ] && ok "  бот запущен прямо сейчас" || { bad "  бот НЕ запущен"; agentdo "подними сервис бота и разберись, почему он упал"; }
    [ "$(g UNITENABLED)" = "yes" ] && ok "  автозапуск после перезагрузки включён" || { warn "  автозапуск выключен"; agentdo "включи автозапуск сервиса бота"; }
    [ "$(g UNITRESTART)" = "yes" ] && ok "  сам поднимается после падения (Restart=always)" || { warn "  нет Restart=always"; agentdo "добавь Restart=always в сервис бота"; }
  else
    bad "Сервиса бота на сервере нет — бот ещё не собран"
    agentdo "собери Telegram-бота на сервере под пользователем brain с systemd и Restart=always (модуль 03A)"
  fi

  [ "$(g BACKUP)" = "yes" ] && ok "Бэкапы настроены" || { warn "Бэкапов не видно"; agentdo "настрой бэкап: снапшоты на сервере + ночное зеркало на мой компьютер (модуль 04)"; }
  [ "$(g UFW)"    = "yes" ] && ok "Файрвол включён" || warn "Файрвол выключен — займёмся после запуска (модуль 05)"
fi

# =============================================================================
# БЛОК 6 — ДВЕ ЖИВЫЕ ПРОВЕРКИ (главный смысл всего аудита)
# =============================================================================
head1 "6. Живые проверки"

ENGINE_OK=0; BRIDGE_OK=0

# 6.1 — думает ли мозг на сервере из подписки
if [ "$SRV_OK" = "1" ] && [ "$(printf '%s' "$SRV_INFO" | grep -c '^CLAUDE=yes')" = "1" ]; then
  printf '  %s·%s спрашиваю мозг на сервере (до 90 сек)…\n' "$DIM" "$D"
  ANSWER="$($SSH "${SERVER_USER}@${SERVER_IP}" 'bash -s' <<'REMOTE'
ENVF=$(grep -rlE "^CLAUDE_CODE_OAUTH_TOKEN=" /home/brain/.config/ 2>/dev/null | head -1)
if [ -z "$ENVF" ]; then echo "NO_ENV_FILE"; exit 0; fi
sudo -u brain -i bash -lc "unset ANTHROPIC_API_KEY; set -a; . '$ENVF'; set +a; cd /home/brain 2>/dev/null; timeout 80 claude -p 'Ответь ровно одним словом: живой'" 2>&1 | tail -3
REMOTE
)"
  if printf '%s' "$ANSWER" | grep -qi 'жив'; then
    ok "МОЗГ НА СЕРВЕРЕ ДУМАЕТ и отвечает из твоей подписки"
    ENGINE_OK=1
  elif printf '%s' "$ANSWER" | grep -qiE 'credit|balance|login|auth|subscription|invalid'; then
    bad "Мозг на сервере не пускает по подписке — токен протух или не тот"
    agentdo "перевыпусти токен подписки (claude setup-token) и положи на сервер заново"
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
      SEND="$(curl -s --max-time 15 -X POST "https://api.telegram.org/bot${BT}/sendMessage" \
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
# ВЕРДИКТ
# =============================================================================
TOTAL=$((OK_N+WARN_N+FAIL_N))
PCT=0; [ "$TOTAL" -gt 0 ] && PCT=$(( OK_N * 100 / TOTAL ))

if   [ "$SRV_OK" != "1" ] && is_placeholder "$SERVER_IP"; then BRANCH="A"; BRANCH_TXT="Сервера пока нет. Твой путь: заказать VPS → перенести мозг → собрать бота."
elif [ "$ENGINE_OK" = "1" ] && [ "$BRIDGE_OK" = "1" ] && [ "$FAIL_N" -eq 0 ]; then BRANCH="ГОТОВО"; BRANCH_TXT="Система собрана: мозг на сервере думает, бот с ним соединён."
else BRANCH="B"; BRANCH_TXT="Сервер есть, но собран не до конца. Твой путь: закрыть красные пункты выше."
fi

printf '\n%s══════════════════════════════════════════════════════════════%s\n' "$B" "$D"
printf '%sИТОГ%s   🟢 %s   🟡 %s   🔴 %s      готовность ~%s%%\n' "$B" "$D" "$OK_N" "$WARN_N" "$FAIL_N" "$PCT"
printf '%sВЕТКА %s%s — %s\n' "$B" "$BRANCH" "$D" "$BRANCH_TXT"
printf '%s══════════════════════════════════════════════════════════════%s\n' "$B" "$D"

{
  printf '\n## Итог\n\n'
  printf -- '- Зелёных: %s · жёлтых: %s · красных: %s\n' "$OK_N" "$WARN_N" "$FAIL_N"
  printf -- '- Готовность: ~%s%%\n' "$PCT"
  printf -- '- Ветка: **%s** — %s\n' "$BRANCH" "$BRANCH_TXT"
  printf -- '- Мозг на сервере думает: %s\n' "$([ "$ENGINE_OK" = 1 ] && echo да || echo нет)"
  printf -- '- Бот соединён и пишет тебе: %s\n' "$([ "$BRIDGE_OK" = 1 ] && echo да || echo нет)"
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
  printf 'Ты мой технический помощник. Я участница AI-Потока. Цель: мой второй мозг живёт\n'
  printf 'на моём сервере 24/7, а мой Telegram-бот разговаривает с ним из моей ПОДПИСКИ\n'
  printf '(переменная CLAUDE_CODE_OAUTH_TOKEN), а не по API-ключу.\n\n'
  printf 'Я прогнала аудит. Вот что он нашёл — отчёт целиком в файле:\n%s\n\n' "$REPORT"
  printf 'МОЯ ВЕТКА: %s — %s\n\n' "$BRANCH" "$BRANCH_TXT"
  if [ ${#TODO_AGENT[@]} -gt 0 ]; then
    printf 'ЗАКРОЙ ЭТИ ПУНКТЫ, по одному, после каждого — короткий отчёт мне:\n'
    i=1; for t in "${TODO_AGENT[@]}"; do printf '%s. %s\n' "$i" "$t"; i=$((i+1)); done
    printf '\n'
  fi
  printf 'ПРАВИЛА (соблюдай неукоснительно):\n'
  printf -- '- Никогда не выводи в чат пароли и токены. Только путь к файлу и факт наличия.\n'
  printf -- '- Секреты живут в env-файлах с правами 600. Не в коде, не в git, не в чате.\n'
  printf -- '- Личное (здоровье, семья, финансы) на сервер НЕ переносим.\n'
  printf -- '- Команду claude setup-token я выполняю САМА в своём терминале — ты её не запускаешь\n'
  printf '  и её вывод не читаешь.\n'
  printf -- '- Ничего необратимого без моего явного «да».\n'
  printf -- '- Инструкции бери из кита novoselie-server-kit в репозитории\n'
  printf '  https://github.com/alexandrkuznetsovofficial-web/ikigai-ai-skills\n'
  printf '  (модуль 02 — переезд мозга, 03A — бот с нуля, 03 — подключение готового бота,\n'
  printf '   04 — бэкапы, 05 — безопасность, 06 — приёмка, 08 — если не взлетело).\n\n'
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
