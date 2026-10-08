#!/usr/bin/env bash
# server_e2e.sh — e2e связки brain-link против «сервера участника», эмулированного на самом раннере.
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
# команда на «сервере» по admin-ключу (HOME = «компьютер» участника, задаётся ниже)
RSSH() { ssh -i "$HOME/.ssh/id_ed25519" -o BatchMode=yes -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null -p "$PORT" "$1@127.0.0.1" "$2" 2>>"$LOG"; }
jget() { echo "$LAST_JSON" | "$PY" -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" 2>/dev/null; }

PY="$(command -v python3)"
say "python: $("$PY" --version 2>&1), repo: $REPO"

# ---------------------------------------------------------------- 1. sshd сервера на 127.0.0.1:2222
# «Сервер участника» = сам раннер. Поднимаем ШТАТНЫЙ ssh.service с лабораторным drop-in, а не отдельный sshd:
# так harden видит порт через `sshd -T`, lockdown кладёт 00-brain.conf в тот же sshd_config.d и делает
# настоящий `systemctl reload ssh`, ключи читаются из штатных ~/.ssh/authorized_keys (root и brain).
SSHD="$(command -v sshd || echo /usr/sbin/sshd)"
if [ ! -x "$SSHD" ]; then
  sudo apt-get update -qq && sudo apt-get install -y -qq openssh-server >/dev/null 2>&1 || true
  SSHD="$(command -v sshd || echo /usr/sbin/sshd)"
fi
[ -x "$SSHD" ] || { bad "нет sshd — не поднять сервер"; echo "ИТОГ: $PASS PASS, $((FAIL+1)) FAIL"; exit 1; }
sudo ssh-keygen -A >/dev/null 2>&1 || true
HOSTKEY=/etc/ssh/ssh_host_ed25519_key
# 10- : после 00-brain.conf (lockdown должен перебивать лабораторию), до 50-cloud-init.conf раннера
LABCONF=/etc/ssh/sshd_config.d/10-brain-lab.conf
printf '%s\n' '# ТОЛЬКО лаборатория (ci/server_e2e.sh): «сервер участника» на 127.0.0.1:2222. В прод не едет.' \
  "Port $PORT" 'ListenAddress 127.0.0.1' 'PermitRootLogin yes' 'PubkeyAuthentication yes' \
  'PasswordAuthentication yes' 'KbdInteractiveAuthentication no' 'LogLevel VERBOSE' | sudo tee "$LABCONF" >/dev/null
# как у свежего VPS: root входит по паролю из письма хостера (keys кладёт ключ сам через SSH_ASKPASS),
# lockdown (00-brain.conf) потом перебивает это. Пароль — случайный, только в $WORK/tok_rootpw (вычищается из артефактов).
"$(command -v python3)" -c 'import secrets,string;a=string.ascii_letters+string.digits;print("Lab%!^&@-"+"".join(secrets.choice(a) for _ in range(20)))' > "$WORK/tok_rootpw"
chmod 600 "$WORK/tok_rootpw"
printf 'root:%s\n' "$(cat "$WORK/tok_rootpw")" | sudo chpasswd && say "пароль root на «сервере» задан" || say "ВНИМАНИЕ: chpasswd root не прошёл"
grep -q '^Include /etc/ssh/sshd_config.d' /etc/ssh/sshd_config || say "ВНИМАНИЕ: sshd_config без Include sshd_config.d"
sudo install -d -m 0700 /root/.ssh; sudo touch /root/.ssh/authorized_keys; sudo chmod 600 /root/.ssh/authorized_keys
sudo mkdir -p /run/sshd && sudo chmod 0755 /run/sshd   # privilege separation dir (сервис сам создаёт, на всякий случай)
sudo "$SSHD" -t 2>&1 | tee -a "$LOG"
# socket activation (ubuntu 24.04) отключаем: ssh.service слушает сам, reload работает как на обычном VPS
sudo systemctl disable --now ssh.socket >/dev/null 2>&1 || true
sudo systemctl enable ssh.service >/dev/null 2>&1 || true
sudo systemctl restart ssh.service 2>&1 | tee -a "$LOG"
up=no
for _ in $(seq 1 30); do
  if (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null; then up=yes; break; fi
  sleep 0.5
done
say "sshd -T port: $(sudo "$SSHD" -T 2>/dev/null | awk '$1=="port"{print $2}' | tr '\n' ' ')"
if [ "$up" = yes ]; then ok "sshd (ssh.service) на 127.0.0.1:$PORT поднят"; else
  bad "sshd не поднялся"; sudo systemctl status ssh.service --no-pager 2>&1 | tail -15 | tee -a "$LOG"
  sudo journalctl -u ssh -n 30 --no-pager 2>&1 | tee -a "$LOG"
  echo "ИТОГ: $PASS PASS, $FAIL FAIL (дальше без sshd смысла нет)"; exit 1
fi

# фейковый Telegram (для шага bot)
setsid nohup "$PY" "$HERE/fake_telegram.py" --port 18081 >"$WORK/tg.log" 2>&1 </dev/null &
TG_PID=$!
sleep 1

# ---------------------------------------------------------------- 2. файл доступа и окружение brain-link
export BRAIN_CONFIG_DIR="$WORK/cfg-brain"
export BRAIN_IKIGAI_ENV="$WORK/ikigai_env.json"
export HOME="$WORK/laphome"           # «компьютер участника»
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

# ---------------------------------------------------------------- 3. keys (доверие при первом входе + ключ по паролю, SSH_ASKPASS)
FP="$(sudo ssh-keygen -lf "$HOSTKEY.pub" | awk '{print $2}')"
say "fingerprint хоста: $FP"
ROOTPW="$(cat "$WORK/tok_rootpw")"
WRONGPW="Wrong%!-$(date +%s)-nope"
KLOG="$WORK/keys_stderr.log"; : > "$KLOG"
KEYS() { # запуск keys: JSON → LAST_JSON, stderr → KLOG (отдельно, для проверки утечки)
  local rc
  LAST_JSON="$("$PY" "$HERE/drive_link.py" -- keys "$@" 2>>"$KLOG")"; rc=$?
  echo "$LAST_JSON" | "$PY" -c 'import sys,json;d=json.loads(sys.stdin.read() or "{}");print("  human:",d.get("human","")[:300]);print("  key_install:",d.get("key_install"),"key_installed:",d.get("key_installed"),"host_key:",d.get("host_key"),"check:",d.get("host_key_check"))' 2>/dev/null | tee -a "$LOG"
  return $rc
}
set_pw() { # PASSWORD в файле доступа: set_pw <значение> | set_pw (убрать)
  grep -v '^PASSWORD=' "$BRAIN_CONFIG_DIR/server_access" > "$BRAIN_CONFIG_DIR/server_access.tmp"
  [ -n "${1:-}" ] && printf 'PASSWORD=%s\n' "$1" >> "$BRAIN_CONFIG_DIR/server_access.tmp"
  mv "$BRAIN_CONFIG_DIR/server_access.tmp" "$BRAIN_CONFIG_DIR/server_access"; chmod 600 "$BRAIN_CONFIG_DIR/server_access"
}
no_leak() { # <пароль> <метка>: пароля нет ни в JSON, ни в stderr keys
  if printf '%s' "$LAST_JSON" | grep -qF -- "$1" || grep -qF -- "$1" "$KLOG"; then bad "$2: пароль утёк в вывод keys"
  else ok "$2: пароля нет ни в JSON, ни в stderr keys"; fi
}
ak_count() { local n; n="$(sudo grep -cxF "$(cat "$HOME/.ssh/id_ed25519.pub" 2>/dev/null)" /root/.ssh/authorized_keys 2>/dev/null)"; echo "${n:-0}"; }

# 3a. без PASSWORD — ключ сервера закреплён (first_use), команда для человека, rc=2
set_pw
KEYS; rc=$?; assert_rc 2 $rc "keys без PASSWORD: команда для человека"
[ "$(jget host_key_check)" = first_use ] && ok "keys: ключ сервера закреплён при первом входе (first_use)" \
  || bad "keys: host_key_check=$(jget host_key_check)"
[ -f "$HOME/.ssh/id_ed25519.pub" ] && ok "keys создал admin-ключ" || bad "keys не создал admin-ключ"
[ -n "$(jget command)" ] && ok "keys без PASSWORD отдал command" || bad "keys без PASSWORD не отдал command"

# 3b. неверный PASSWORD — одна попытка, rc=2, key_install=password_rejected, ключ не положен, пароля в выводе нет
set_pw "$WRONGPW"
KEYS; rc=$?; assert_rc 2 $rc "keys с неверным паролем"
[ "$(jget key_install)" = password_rejected ] && ok "keys: неверный пароль → password_rejected" \
  || bad "keys: неверный пароль → key_install=$(jget key_install)"
[ "$(ak_count)" = 0 ] && ok "неверный пароль: ключ на сервер не попал" || bad "неверный пароль, а ключ в authorized_keys"
no_leak "$WRONGPW" "неверный пароль"
fails="$(sudo journalctl -u ssh --since '-2min' --no-pager 2>/dev/null | grep -c 'Failed password for root')"
say "журнал sshd: неудачных паролей root за 2 мин: $fails"
[ "${fails:-0}" -le 1 ] && ok "неверный пароль: ровно одна попытка (fail2ban-бережно)" || bad "попыток пароля: $fails (ждали ≤1)"

# 3c. верный PASSWORD — ключ кладётся сам, rc=0, key_installed=password, пароля в выводе нет
set_pw "$ROOTPW"
KEYS; rc=$?; assert_rc 0 $rc "keys кладёт ключ по паролю (SSH_ASKPASS)"
[ "$(jget key_installed)" = password ] && ok "keys: key_installed=password" || bad "keys: key_installed=$(jget key_installed)"
grep -q '^PASSWORD=' "$BRAIN_CONFIG_DIR/server_access" && bad "строка PASSWORD осталась в файле доступа" \
  || ok "строка PASSWORD убрана из файла доступа (password_line_removed=$(jget password_line_removed))"
ls "$BRAIN_CONFIG_DIR"/server_access.bak* >/dev/null 2>&1 && grep -lqF -- "$ROOTPW" "$BRAIN_CONFIG_DIR"/server_access.bak* \
  && bad "пароль остался в копии .bak файла доступа" || ok "копии файла доступа с паролем нет"
[ "$(ak_count)" = 1 ] && ok "admin-ключ в /root/.ssh/authorized_keys ровно один раз" || bad "admin-ключ в authorized_keys: $(ak_count) раз"
no_leak "$ROOTPW" "верный пароль"
ls -d "${TMPDIR:-/tmp}"/brain-askpass-* >/dev/null 2>&1 && bad "временная папка askpass не убрана" || ok "временная папка askpass убрана"

# 3d. повторный keys — уже вход по ключу (без пароля), идемпотентно
KEYS; rc=$?; assert_rc 0 $rc "keys повторно: вход по ключу работает"
[ -z "$(jget key_installed)" ] && ok "повторный keys пароль не трогал" || bad "повторный keys снова шёл по паролю"
[ "$(ak_count)" = 1 ] && ok "повторный keys не задвоил ключ" || bad "ключ задвоен: $(ak_count)"
if [ "$rc" != 0 ]; then
  say "без входа по ключу остальные шаги бессмысленны — журнал ssh:"; sudo journalctl -u ssh -n 25 --no-pager | tee -a "$LOG"
  echo "ИТОГ: $PASS PASS, $FAIL FAIL"; exit 1
fi
# 3e. report (диагностика куратору) не содержит пароля
LINK -- report; rrc=$?
REP="$(ls -t "$HOME"/brain-link-report-*.txt 2>/dev/null | head -1)"
if [ -n "$REP" ]; then
  cp "$REP" "$WORK/brain-link-report.log"
  grep -qF -- "$ROOTPW" "$REP" && bad "report: пароль root в отчёте" || ok "report: пароля root в отчёте нет"
  grep -qF -- "$ROOTPW" "$LOG" && bad "журнал e2e содержит пароль" || ok "журнал e2e без пароля"
else bad "report не создал файл (rc=$rrc)"; fi

# sync-ключ на сервер ставит harden (в /home/brain/.ssh/authorized_keys).
# detect
LINK -- detect; assert_rc 0 $? "detect отвечает"
say "ветка/next: $(jget branch) / $(jget next_step)"

# ---------------------------------------------------------------- 4. harden (brain, swap, ufw-правила без enable, brain-admin)
# Нормализация раннера (не «сервера участника»): у образа GitHub /etc/sudoers.d/runner с режимом 0644 —
# из-за этого `visudo -c` в harden ругается на чужой файл. На чистом VPS такого файла нет.
# (/etc/sudoers.d — 0750 root, глобом от runner не читается — ищем через sudo find)
sudo find /etc/sudoers.d -maxdepth 1 -type f ! -perm 0440 -printf '%p\n' 2>/dev/null | while read -r f; do
  sudo chmod 0440 "$f" && say "раннер: chmod 0440 $f"; done
if sudo visudo -c >/dev/null 2>&1; then say "раннер: visudo -c чисто до harden"
else say "раннер: visudo -c ругается ещё ДО harden:"; sudo visudo -c 2>&1 | grep -v "parsed OK" | sed 's/^/   /' | tee -a "$LOG"; fi
export BRAIN_LAB_SKIP_UFW_ENABLE=1   # хук harden другого агента: правила задать, enable пропустить
LINK -- harden; rc=$?; assert_rc 0 $rc "harden прошёл"
if [ "$rc" != 0 ]; then
  echo "$LAST_JSON" | "$PY" -c 'import sys,json;d=json.loads(sys.stdin.read() or "{}");[print("   ❌",x) for x in (d.get("lines") or {}).get("bad",[])]' 2>/dev/null | tee -a "$LOG"
  say "диагностика: visudo -c и /etc/sudoers.d"
  RSSH root 'visudo -c 2>&1 | grep -v "parsed OK"; ls -l /etc/sudoers.d' | sed 's/^/   /' | tee -a "$LOG"
fi
id_brain="$(RSSH root 'id brain >/dev/null 2>&1 && echo yes || echo no')"
[ "$id_brain" = yes ] && ok "пользователь brain создан" || bad "пользователя brain нет"
cred_perm="$(RSSH root 'stat -c "%a %U" /etc/brain-bot/credentials 2>/dev/null')"
[ "$cred_perm" = "700 root" ] && ok "/etc/brain-bot/credentials 0700 root" || bad "credentials: $cred_perm"
mem_perm="$(RSSH root 'stat -c "%a" /home/brain/memory 2>/dev/null')"
[ "$mem_perm" = "750" ] && ok "/home/brain/memory 0750" || bad "memory: $mem_perm"
# RT-11: бот — системный пользователь brainbot (nologin, группа brain), его состояние — /var/lib/brain-bot 0700
bb_info="$(RSSH root 'getent passwd brainbot | cut -d: -f7; id -nG brainbot; stat -c "%a %U" /var/lib/brain-bot /var/lib/brain-bot/claude-config; stat -c "%a %G" /home/brain/memory/inbox /home/brain/memory/dialogues' | tr '\n' '|')"
say "brainbot: $bb_info"
case "$bb_info" in
  /usr/sbin/nologin\|*brain*\|"700 brainbot|700 brainbot|2770 brain|2770 brain|") ok "brainbot: nologin, в группе brain, /var/lib/brain-bot 0700, inbox/dialogues 2770" ;;
  *) bad "brainbot/права не те: $bb_info" ;;
esac
in_grp="$(RSSH root 'id -nG brain' | tr ' ' '\n' | grep -cx brainbot)"
[ "${in_grp:-0}" = 0 ] && ok "brain не в группе brainbot" || bad "brain в группе brainbot"
ufw_added="$(RSSH root 'ufw show added 2>/dev/null | tr "\n" " "')"
echo "$ufw_added" | grep -q "$PORT" && ok "ufw-правило на $PORT задано (enable пропущен)" || bad "ufw-правило не задано: $ufw_added"
# ключ синка ставит сам harden в /home/brain/.ssh/authorized_keys (restrict,command=…) — проверяем его строку
ak_sync="$(RSSH root "grep -c 'restrict,command=\"/home/brain/.local/bin/brain_sync_server.py\"' /home/brain/.ssh/authorized_keys 2>/dev/null")"
[ "${ak_sync:-0}" -ge 1 ] && ok "harden поставил ключ синка brain с restrict,command=" || bad "ключа синка с restrict,command= у brain нет"
sync_id="$(ssh -i "$HOME/.ssh/brain_sync_ed25519" -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
           -p "$PORT" brain@127.0.0.1 id 2>/dev/null)"
[ -z "$sync_id" ] && ok "ключ синка не даёт shell (id пуст)" || bad "ключ синка дал shell: $sync_id"

# ---------------------------------------------------------------- 5. claude: владельца (заглушка) + root-копия бота
# claude владельца — заглушка в ~/.local/bin brain (для его ручной работы; бот её НЕ использует, RT-11b).
RSSH root "install -d -m0750 -o brain -g brain /home/brain/.local/bin"
cat "$HERE/fake_claude.py" | RSSH root "cat > /home/brain/.local/bin/claude && chmod 755 /home/brain/.local/bin/claude && chown brain:brain /home/brain/.local/bin/claude"
# claude бота ставит шаг claude → brain-admin update-claude ТЕМ ЖЕ путём, что у участника (временная папка,
# установщик от brainbot, проверка ELF и --version, root-копия, sha256). Вместо скачивания claude.ai/install.sh —
# root-файл /etc/brain-bot/lab-claude-installer.sh: та же раскладка versions/<версия>, внутри ELF-обёртка заглушки.
LAB_SHA="$("$PY" "$HERE/make_lab_claude_installer.py" "$WORK/lab-claude-installer.sh" 2>>"$LOG")"
[ -n "$LAB_SHA" ] && ok "лабораторный установщик claude собран (ELF ${LAB_SHA:0:12}…)" || bad "лабораторный установщик claude не собрался (нет cc?)"
cat "$WORK/lab-claude-installer.sh" | RSSH root "install -d -m0755 -o root -g root /etc/brain-bot && cat > /etc/brain-bot/lab-claude-installer.sh && chown root:root /etc/brain-bot/lab-claude-installer.sh && chmod 0644 /etc/brain-bot/lab-claude-installer.sh"
# журнал fake_claude по умолчанию — рядом с CLAUDE_CONFIG_DIR бота, т.е. в /var/lib/brain-bot (0700 brainbot)
LINK -- claude; assert_rc 0 $? "claude: заглушка владельца + root-копия бота (brain-admin update-claude)"
bc="$(RSSH root 'stat -c "%U:%G %a" /usr/local/lib/brain-bot /usr/local/lib/brain-bot/claude /usr/local/lib/brain-bot/claude/bin /usr/local/lib/brain-bot/claude/bin/claude /usr/local/lib/brain-bot/claude.sha256; head -c 4 /usr/local/lib/brain-bot/claude/bin/claude | od -An -tx1 | tr -d " \n"; echo; sha256sum /usr/local/lib/brain-bot/claude/bin/claude | cut -d" " -f1; cut -d" " -f1 /usr/local/lib/brain-bot/claude.sha256; ls -d /var/cache/brain-claude-install.* 2>/dev/null | wc -l' | tr '\n' '|')"
say "root-копия claude: $bc"
case "$bc" in
  "root:root 755|root:root 755|root:root 755|root:root 755|root:root 644|7f454c46|$LAB_SHA|$LAB_SHA|0|") ok "claude бота: root:root 0755 ELF, sha256 записан и совпадает, временная папка убрана" ;;
  *) bad "root-копия claude не та: $bc" ;;
esac
bw="$(RSSH root 'for u in brain brainbot; do for f in /usr/local/lib/brain-bot /usr/local/lib/brain-bot/claude/bin /usr/local/lib/brain-bot/claude/bin/claude /usr/local/lib/brain-bot/claude.sha256; do runuser -u $u -- test -w $f && echo "$u:$f"; done; done; true')"
[ -z "$bw" ] && ok "brain и brainbot не могут писать в /usr/local/lib/brain-bot (код и claude бота)" || bad "запись в /usr/local/lib/brain-bot: $bw"

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
# миграция ранней установки (бот был под brain, состояние в ~/.local/state/brain-bot): шаг bot переносит
# состояние в /var/lib/brain-bot и убирает старую папку. Безвредный файл — watch_state.json.
# Эмуляция ранней установки: юнит brain-bot ещё под User=brain и метки переноса нет (harden свежей версии
# уже поставил юнит под brainbot и метку — на свежей установке перенос запрещён, это проверяет RT-11c).
RSSH root "sed -i 's/^User=brainbot\$/User=brain/' /etc/systemd/system/brain-bot.service && rm -f /var/lib/brain-bot/.migrated-from-brain && systemctl daemon-reload"
printf '{"lab": 1}\n' | RSSH root "runuser -u brain -- sh -c 'mkdir -p /home/brain/.local/state/brain-bot/claude-config && cat > /home/brain/.local/state/brain-bot/watch_state.json'"
LINK -- bot --yes; rc=$?
say "bot rc=$rc"
say "права для бота (диагностика):"
RSSH root 'stat -c "%A %U:%G %n" /home/brain /home/brain/memory /home/brain/memory/inbox /home/brain/memory/dialogues /var/lib/brain-bot
  runuser -u brainbot -- id
  runuser -u brainbot -- sh -c "test -w /home/brain/memory/inbox && echo inbox:W || echo inbox:NO-W; touch /home/brain/memory/inbox/.diag.brain-tmp 2>&1; rm -f /home/brain/memory/inbox/.diag.brain-tmp"
  findmnt -no TARGET,OPTIONS -T /home/brain/memory/inbox
  getfacl -p /home/brain/memory/inbox 2>/dev/null | grep -v "^#"
  /usr/local/sbin/brain-admin selftest 2>&1 | grep -E "❌|🟡|ИТОГ"' 2>&1 | sed 's/^/   /' | tee -a "$LOG"
# сценарию бота нужны те же токены (сравнивает по sha256, сами значения не печатает)
mkdir -p "$WORK/secforbot"; cp "$WORK/tok_bot" "$WORK/secforbot/bot_token"; cp "$WORK/tok_claude" "$WORK/secforbot/claude_token"
# фейковый Telegram слушает на раннере (хост), сервер=тот же хост — localhost достижим.
# Журнал fake claude бот пишет в свой state (0700 brainbot) — сценарий читаем от root (sudo).
CLOG=/var/lib/brain-bot/fake_claude.jsonl
if [ "$rc" != 0 ]; then
  bad "шаг bot не прошёл (rc=$rc) — сценарий бота пропущен (без бота он 10 минут ждёт таймауты)"
  RSSH root "systemctl status brain-bot --no-pager -l 2>&1 | tail -20; journalctl -u brain-bot -n 30 --no-pager 2>&1" | tee -a "$LOG"
  bot_rc=skip
else
mig="$(RSSH root 'cat /var/lib/brain-bot/watch_state.json 2>/dev/null; test -e /home/brain/.local/state/brain-bot && echo LEGACY_LEFT || echo LEGACY_GONE')"
case "$mig" in *'"lab": 1'*LEGACY_GONE*) ok "миграция: состояние ранней установки перенесено в /var/lib/brain-bot, старая папка убрана" ;;
  *) bad "миграция состояния не сработала: $(echo "$mig" | tr '\n' ' ')" ;; esac
bu="$(RSSH root 'systemctl show -p User --value brain-bot.service; ps -o user= -p "$(systemctl show -p MainPID --value brain-bot.service)"' | tr '\n' ' ')"
[ "$bu" = "brainbot brainbot " ] && ok "бот работает под brainbot (юнит и процесс)" || bad "бот не под brainbot: $bu"
sudo "$PY" "$HERE/bot_scenario.py" full --tg http://127.0.0.1:18081 --owner 111111111 \
  --secrets "$WORK/secforbot" --claude-log "$CLOG" \
  --brain-home /home/brain --report "$WORK/bot_report.json" 2>&1 | tee -a "$LOG"
bot_rc=${PIPESTATUS[0]}
assert_rc 0 "$bot_rc" "сценарий бота (чужой молчит, режимы, фильтр, inbox)"
fi

# ---------------------------------------------------------------- 9. verify
# На Linux-«компьютере» schedule нет (только Mac/Windows) — расписание эмулируем фоновым циклом настоящего
# brain_sync.py run (ssh-транспорт, ключ синка), «запомни тест связки» владелец пишет в фейковый Telegram.
VSTOP="$WORK/verify_sync.stop"; rm -f "$VSTOP"
( while [ ! -f "$VSTOP" ]; do
    "$PY" "$SCRIPTS/brain_sync.py" run >>"$WORK/verify_sync.log" 2>&1
    sleep 10
  done ) &
VLOOP=$!
( sleep 5; "$PY" "$HERE/bot_scenario.py" say --tg http://127.0.0.1:18081 --owner 111111111 "запомни тест связки" \
    >>"$WORK/verify_say.log" 2>&1 ) &
LINK -- verify --wait 240; vrc=$?
touch "$VSTOP"; wait "$VLOOP" 2>/dev/null || true
echo "$LAST_JSON" | "$PY" -c 'import sys,json
d=json.loads(sys.stdin.read() or "{}")
for k,c in sorted((d.get("checks") or {}).items()):
    print("   %s %s — %s: %s" % ("✅" if c.get("status")=="ok" else "❌", k, c.get("title"), str(c.get("detail"))[:200]))' 2>/dev/null | tee -a "$LOG"
assert_rc 0 "$vrc" "verify зелёный (расписание эмулировано циклом brain_sync, «запомни» через фейковый TG)"
if [ "$vrc" != 0 ]; then
  say "диагностика самопроверки (stderr brain-admin, без секретов):"
  RSSH root "/usr/local/sbin/brain-admin selfcheck-security 2>&1 | grep -vE '^(INFO|SELFCHECK_)' | tail -25; journalctl -u brain-watch -n 10 --no-pager -o cat 2>/dev/null" \
    | sed -E 's/sk-ant-[A-Za-z0-9_-]+/<скрыто>/g; s/[0-9]{8,10}:[A-Za-z0-9_-]{30,}/<скрыто>/g' | tail -40 | sed 's/^/   /' | tee -a "$LOG"
fi
# RT-11: бот (brainbot) пишет inbox, синк (brain) читает и переносит его заметку в .synced (rename по group-write)
syn="$(RSSH root 'find /home/brain/memory/inbox/.synced -name "*_tg*.md" -user brainbot 2>/dev/null | head -3 | wc -l; find /home/brain/memory/inbox -maxdepth 1 -name "*_tg*.md" 2>/dev/null | wc -l')"
set -- $syn
[ "${1:-0}" -ge 1 ] && ok "синк (brain) перенёс заметку бота (владелец brainbot) из inbox в .synced" \
  || bad "в inbox/.synced нет заметок бота (владелец brainbot): $syn"

# ---------------------------------------------------------------- 10. lockdown: откат на испорченном ключе
# Проверка «brain по ключу» идёт с чужим (настоящим, но не авторизованным) ключом → обязана провалиться → откат.
rm -f "$WORK/bogus_key" "$WORK/bogus_key.pub"; ssh-keygen -q -t ed25519 -N "" -f "$WORK/bogus_key"
LINK --lockdown-bad-key "$WORK/bogus_key" -- lockdown --confirm --confirm-again; lrc=$?
say "lockdown rc=$lrc"
if echo "$LAST_JSON" | grep -q 'только после зелёного verify'; then
  bad "lockdown не запускался (verify не зелёный) — откат на битом ключе НЕ проверен"
else
  lk="$(RSSH root 'test -f /etc/ssh/sshd_config.d/00-brain.conf && echo on || echo off')"
  [ "$lk" = off ] && ok "lockdown с битым ключом откатился (00-brain.conf не активен, root-вход как был)" \
                  || bad "lockdown не откатился: 00-brain.conf=$lk"
  [ "$lrc" != 0 ] && ok "lockdown с битым ключом вернул ошибку (rc=$lrc)" || bad "lockdown с битым ключом вернул rc=0"
fi

say "----"
say "server-e2e: $PASS PASS, $FAIL FAIL"
# прибраться
# sshd и фейковый Telegram НЕ гасим: следующий шаг job (security_checks.sh) работает по тому же «серверу»
echo "$TG_PID" > "$WORK/tg.pid"
[ "$FAIL" -eq 0 ]
