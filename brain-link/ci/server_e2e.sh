#!/usr/bin/env bash
# server_e2e.sh — e2e связки brain-link против «сервера ученика», эмулированного на самом раннере.
# Отдельный sshd на 127.0.0.1:2222 (root по ключу), затем шаги установщика по шагам.
# Только для GitHub Actions (ubuntu, sudo). Ничего наружу не ходит, секретов репо не трогает.
#
# Переменные окружения, которые ждёт скрипт:
#   WORK      рабочая папка логов/артефактов (по умолчанию $RUNNER_TEMP/brain-lab)
#   REPO      корень репозитория (по умолчанию два уровня вверх от ci/)
# Пробрасываются в установщик: BRAIN_LAB_SKIP_UFW_ENABLE=1 (хук harden другого агента).
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="${REPO:-$(cd "$HERE/../.." && pwd)}"
SCRIPTS="$REPO/brain-link/scripts"
WORK="${WORK:-${RUNNER_TEMP:-/tmp}/brain-lab}"
PORT=2222
PASS=0; FAIL=0
LOG="$WORK/server_e2e.log"

mkdir -p "$WORK"
: > "$LOG"
say()  { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
ok()   { PASS=$((PASS+1)); echo "PASS $*" | tee -a "$LOG"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL $*" | tee -a "$LOG"; }
assert_rc() { # expected got label
  if [ "$1" = "$2" ]; then ok "$3 (rc=$2)"; else bad "$3 (ждали rc=$1, получили $2)"; fi
}

# brain-link под «драйвером»: один JSON в stdout, код выхода — реальный.
# Печатаем human и возвращаем rc.
LINK() { # шаг и флаги …
  local out rc
  out="$("$PY" "$HERE/drive_link.py" "$@" 2>>"$LOG")"; rc=$?
  echo "$out" | "$PY" -c 'import sys,json;
d=json.loads(sys.stdin.read() or "{}");
print("  human:", d.get("human","")[:400]);
print("  next:", d.get("next_step"))' 2>/dev/null | tee -a "$LOG" || echo "$out" | tee -a "$LOG"
  LAST_JSON="$out"
  return $rc
}
jget() { echo "$LAST_JSON" | "$PY" -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" 2>/dev/null; }

PY="$(command -v python3)"
say "python: $("$PY" --version 2>&1), repo: $REPO"

# ---------------------------------------------------------------- 1. sshd сервера на 127.0.0.1:2222
SRV="$WORK/server"              # «сервер ученика»: отдельный корень с /home, /etc, sshd
mkdir -p "$SRV"
SSHD="$(command -v sshd || echo /usr/sbin/sshd)"
if [ ! -x "$SSHD" ]; then
  sudo apt-get update -qq && sudo apt-get install -y -qq openssh-server >/dev/null 2>&1 || true
  SSHD="$(command -v sshd || echo /usr/sbin/sshd)"
fi
[ -x "$SSHD" ] || { bad "нет sshd — не поднять сервер"; echo "ИТОГ: $PASS PASS, $((FAIL+1)) FAIL"; exit 1; }

# ключ хоста сервера и конфиг отдельного sshd
HOSTKEY="$WORK/ssh_host_ed25519_key"
[ -f "$HOSTKEY" ] || ssh-keygen -q -t ed25519 -N "" -f "$HOSTKEY"
SSHD_CONF="$WORK/sshd_lab.conf"
# Корневой AuthorizedKeysFile: штатный ~/.ssh/authorized_keys (туда harden кладёт ключи brain, в т.ч. ключ
# синка с restrict,command= — проверяем НАСТОЯЩУЮ строку продукта) + файл root лаборатории (эмуляция ssh-copy-id).
# UsePAM yes — как на реальном сервере (иначе sshd без PAM отказывает «заблокированным» root/brain без пароля).
cat > "$SSHD_CONF" <<CONF
Port $PORT
ListenAddress 127.0.0.1
HostKey $HOSTKEY
PidFile $WORK/sshd.pid
PermitRootLogin prohibit-password
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
AuthorizedKeysFile .ssh/authorized_keys $WORK/authorized_root
UsePAM yes
StrictModes no
LogLevel VERBOSE
Subsystem sftp internal-sftp
CONF
: > "$WORK/authorized_root"
chmod 600 "$WORK/authorized_root" "$HOSTKEY"

# privilege separation dir: на раннере sshd как сервис не запущен, /run/sshd нет → «Missing privilege separation directory»
sudo mkdir -p /run/sshd && sudo chmod 0755 /run/sshd
sudo "$SSHD" -t -f "$SSHD_CONF" 2>&1 | tee -a "$LOG"
# запускаем sshd как root (раннер даёт passwd-sudo); он эмулирует «root-сервер ученика»
sudo "$SSHD" -f "$SSHD_CONF" -E "$WORK/sshd.log"
up=no
for _ in $(seq 1 20); do
  if sudo test -f "$WORK/sshd.pid" && (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null; then up=yes; break; fi
  sleep 0.5
done
if [ "$up" = yes ]; then ok "sshd на 127.0.0.1:$PORT поднят"; else
  bad "sshd не поднялся"; sudo cat "$WORK/sshd.log" 2>/dev/null | tail -20 | tee -a "$LOG"
  echo "ИТОГ: $PASS PASS, $FAIL FAIL (дальше без sshd смысла нет)"; exit 1
fi

# фейковый Telegram (для шага bot)
"$PY" "$HERE/fake_telegram.py" --port 18081 >"$WORK/tg.log" 2>&1 &
TG_PID=$!
sleep 1

# ---------------------------------------------------------------- 2. файл доступа и окружение brain-link
export BRAIN_CONFIG_DIR="$WORK/cfg-brain"
export BRAIN_IKIGAI_ENV="$WORK/ikigai_env.json"
export HOME="$WORK/laphome"           # «компьютер ученика»
mkdir -p "$HOME/.ssh" "$BRAIN_CONFIG_DIR"
# рабочая папка «компьютера» — память + CLAUDE.md + скилл
WS="$WORK/workspace"
mkdir -p "$WS/memory/inbox" "$WS/memory/dialogues" "$HOME/.claude/skills/brain-link"
printf '# CLAUDE\nрабочая папка лаборатории\n' > "$WS/CLAUDE.md"
printf '# MEMORY\nLAB-MEMORY-MARKER-7f3a\n' > "$WS/memory/MEMORY.md"
printf 'skill lab\n' > "$HOME/.claude/skills/brain-link/SKILL.md"
printf '{"workspace":"%s","skills_dir":"%s/.claude/skills"}\n' "$WS" "$HOME" > "$BRAIN_IKIGAI_ENV"
cat > "$BRAIN_CONFIG_DIR/server_access" <<ACC
SERVER_IP=127.0.0.1
SERVER_USER=root
SERVER_PORT=$PORT
USER_ID=111111111
ACC
chmod 600 "$BRAIN_CONFIG_DIR/server_access"

# ---------------------------------------------------------------- 3. keys (с отпечатком хоста, вход по ключу)
FP="$(ssh-keygen -lf "$HOSTKEY.pub" | awk '{print $2}')"
say "fingerprint хоста: $FP"
LINK -- keys --fingerprint "$FP"; rc=$?
# admin-ключ сгенерирован — кладём его в authorized_keys сервера (эмуляция ssh-copy-id вручную)
if [ -f "$HOME/.ssh/id_ed25519.pub" ]; then
  cat "$HOME/.ssh/id_ed25519.pub" | sudo tee -a "$WORK/authorized_root" >/dev/null
  ok "admin-ключ добавлен в authorized_keys сервера"
else
  bad "keys не создал admin-ключ"
fi
LINK -- keys --fingerprint "$FP"; rc=$?; assert_rc 0 $rc "keys: вход по ключу работает"
if [ "$rc" != 0 ]; then
  say "без входа по ключу остальные шаги бессмысленны — хвост sshd.log:"; sudo tail -15 "$WORK/sshd.log" | tee -a "$LOG"
  echo "ИТОГ: $PASS PASS, $FAIL FAIL"; exit 1
fi

# sync-ключ на сервер ставит harden (в /home/brain/.ssh/authorized_keys).
# detect
LINK -- detect; assert_rc 0 $? "detect отвечает"
say "ветка/next: $(jget branch) / $(jget next_step)"

# ---------------------------------------------------------------- 4. harden (brain, swap, ufw-правила без enable, brain-admin)
export BRAIN_LAB_SKIP_UFW_ENABLE=1   # хук harden другого агента: правила задать, enable пропустить
LINK -- harden; assert_rc 0 $? "harden прошёл"
# проверки на сервере от root
RSSH() { ssh -i "$HOME/.ssh/id_ed25519" -o BatchMode=yes -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null -p "$PORT" "$1@127.0.0.1" "$2" 2>>"$LOG"; }
id_brain="$(RSSH root 'id brain >/dev/null 2>&1 && echo yes || echo no')"
[ "$id_brain" = yes ] && ok "пользователь brain создан" || bad "пользователя brain нет"
cred_perm="$(RSSH root 'stat -c "%a %U" /etc/brain-bot/credentials 2>/dev/null')"
[ "$cred_perm" = "700 root" ] && ok "/etc/brain-bot/credentials 0700 root" || bad "credentials: $cred_perm"
mem_perm="$(RSSH root 'stat -c "%a" /home/brain/memory 2>/dev/null')"
[ "$mem_perm" = "750" ] && ok "/home/brain/memory 0750" || bad "memory: $mem_perm"
ufw_added="$(RSSH root 'ufw show added 2>/dev/null | tr "\n" " "')"
echo "$ufw_added" | grep -q "$PORT" && ok "ufw-правило на $PORT задано (enable пропущен)" || bad "ufw-правило не задано: $ufw_added"
# ключ синка ставит сам harden в /home/brain/.ssh/authorized_keys (restrict,command=…) — проверяем его строку
ak_sync="$(RSSH root "grep -c 'restrict,command=\"/home/brain/.local/bin/brain_sync_server.py\"' /home/brain/.ssh/authorized_keys 2>/dev/null")"
[ "${ak_sync:-0}" -ge 1 ] && ok "harden поставил ключ синка brain с restrict,command=" || bad "ключа синка с restrict,command= у brain нет"
sync_id="$(ssh -i "$HOME/.ssh/brain_sync_ed25519" -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
           -p "$PORT" brain@127.0.0.1 id 2>/dev/null)"
[ -z "$sync_id" ] && ok "ключ синка не даёт shell (id пуст)" || bad "ключ синка дал shell: $sync_id"

# ---------------------------------------------------------------- 5. claude (заглушка в PATH brain)
RSSH root "install -d -m0750 -o brain -g brain /home/brain/.local/bin"
sudo cp "$HERE/fake_claude.py" "$SRV/claude.tmp" 2>/dev/null || true
cat "$HERE/fake_claude.py" | RSSH root "cat > /home/brain/.local/bin/claude && chmod 755 /home/brain/.local/bin/claude && chown brain:brain /home/brain/.local/bin/claude"
RSSH root "mkdir -p /home/brain/.local/state/brain-bot && chown -R brain:brain /home/brain/.local/state"
# прокинем журнал fake_claude туда, где его потом прочитает security_checks (через FAKE_CLAUDE_LOG по умолчанию — state бота)
LINK -- claude; assert_rc 0 $? "claude (заглушка) принят"

# ---------------------------------------------------------------- 6. put-token claude|bot (через GETPASS-инъекцию)
"$PY" - <<PYGEN
import secrets, string
a = string.ascii_letters + string.digits
open("$WORK/tok_claude","w").write("sk-ant-oat01-" + "".join(secrets.choice(a) for _ in range(40)))
open("$WORK/tok_bot","w").write("8" + "".join(secrets.choice("0123456789") for _ in range(8)) + ":" + "".join(secrets.choice(a) for _ in range(35)))
PYGEN
LINK --getpass-file "$WORK/tok_claude" -- put-token claude --no-setup; assert_rc 0 $? "put-token claude"
LINK --getpass-file "$WORK/tok_bot" -- put-token bot; assert_rc 0 $? "put-token bot"
tok_c_perm="$(RSSH root 'stat -c "%a %U" /etc/brain-bot/credentials/claude_token 2>/dev/null')"
[ "$tok_c_perm" = "600 root" ] && ok "claude_token 0600 root" || bad "claude_token: $tok_c_perm"

# ---------------------------------------------------------------- 7. init (первая выгрузка памяти)
LINK -- init --yes; assert_rc 0 $? "init: память и скилл выгружены"
sv_mem="$(RSSH root 'find /home/brain/memory -name MEMORY.md 2>/dev/null | head -1')"
[ -n "$sv_mem" ] && ok "MEMORY.md доехал на сервер" || bad "MEMORY.md на сервере нет"
sv_priv="$(RSSH root 'ls -d /home/brain/memory/personal /home/brain/*.session 2>/dev/null')"
[ -z "$sv_priv" ] && ok "личного/сессий на сервере нет" || bad "на сервере личное: $sv_priv"

# ---------------------------------------------------------------- 8. bot (фейковый Telegram, lab drop-in)
# lab-only drop-in: разрешить localhost и указать адрес фейкового Bot API (см. ci/README.md)
RSSH root "install -d -m0755 /etc/systemd/system/brain-bot.service.d"
printf '%s\n' \
  '# ТОЛЬКО лаборатория (ci/server_e2e.sh). В прод не едет.' \
  '[Service]' 'IPAddressAllow=127.0.0.1/32' 'Environment=TELEGRAM_API_BASE=http://127.0.0.1:18081' \
  | RSSH root "cat > /etc/systemd/system/brain-bot.service.d/zz-lab.conf"
RSSH root "systemctl daemon-reload 2>/dev/null || true"
LINK -- bot --yes; rc=$?
say "bot rc=$rc"
# сценарию бота нужны те же токены (сравнивает по sha256, сами значения не печатает)
mkdir -p "$WORK/secforbot"; cp "$WORK/tok_bot" "$WORK/secforbot/bot_token"; cp "$WORK/tok_claude" "$WORK/secforbot/claude_token"
# фейковый Telegram слушает на раннере (хост), сервер=тот же хост — localhost достижим.
# Журнал fake claude бот пишет в свой state (0700 brain) — сценарий читаем от root (sudo).
CLOG=/home/brain/.local/state/brain-bot/fake_claude.jsonl
if [ "$rc" != 0 ]; then
  bad "шаг bot не прошёл (rc=$rc) — сценарий бота пропущен (без бота он 10 минут ждёт таймауты)"
  RSSH root "systemctl status brain-bot --no-pager -l 2>&1 | tail -20; journalctl -u brain-bot -n 30 --no-pager 2>&1" | tee -a "$LOG"
  bot_rc=skip
else
sudo "$PY" "$HERE/bot_scenario.py" full --tg http://127.0.0.1:18081 --owner 111111111 \
  --secrets "$WORK/secforbot" --claude-log "$CLOG" \
  --brain-home /home/brain --report "$WORK/bot_report.json" 2>&1 | tee -a "$LOG"
bot_rc=${PIPESTATUS[0]}
assert_rc 0 "$bot_rc" "сценарий бота (чужой молчит, режимы, фильтр, inbox)"
fi

# ---------------------------------------------------------------- 9. verify (что доступно без второго окна)
LINK -- verify --wait 60; rc=$?
say "verify rc=$rc"

# ---------------------------------------------------------------- 10. lockdown: успех + откат на испорченном ключе
LINK --lockdown-bad-key "$WORK/bogus_key" -- lockdown --confirm --confirm-again; rc=$?
# испорченный ключ → проверка «brain по ключу» провалится → автооткат, lockdown НЕ включён
lk="$(RSSH root 'test -f /etc/ssh/sshd_config.d/00-brain.conf && echo on || echo off')"
[ "$lk" = off ] && ok "lockdown с битым ключом откатился (вход как был)" || bad "lockdown не откатился: $lk"

say "----"
say "server-e2e: $PASS PASS, $FAIL FAIL"
# прибраться
kill "$TG_PID" 2>/dev/null || true
sudo kill "$(sudo cat "$WORK/sshd.pid" 2>/dev/null)" 2>/dev/null || true
[ "$FAIL" -eq 0 ]
