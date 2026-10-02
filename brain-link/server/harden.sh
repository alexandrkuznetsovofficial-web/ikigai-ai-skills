#!/usr/bin/env bash
# harden.sh — kit 2.1 (brain-link). Подготовка чистого Ubuntu 24.04 под «базу» второго мозга.
# Запуск от root (до lockdown), идемпотентно: повторный прогон ничего не ломает, только досоздаёт.
#
#   ADMIN_PUBKEY="ssh-ed25519 AAAA… you@laptop" \
#   SYNC_PUBKEY="ssh-ed25519 AAAA… brain-sync"  \
#   SERVER_PORT=22 OWNER_ID=123456789 bash harden.sh
#
# Что НЕ делает (сознательно): не меняет порт SSH, не ставит белый список IP, не выключает
# вход по паролю — sshd_00-brain.conf кладётся выключенным (*.disabled), включает его
# только `brain-link lockdown` после зелёного verify. Node.js не ставит: Claude Code
# ставится официальным установщиком под brain (шаг `brain-link claude`).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

HERE=$(cd "$(dirname "$0")" && pwd)
BRAIN=brain
BH=/home/brain
PORT=${SERVER_PORT:-22}
FAIL=0

ok()   { echo "✅ $*"; }
warn() { echo "🟡 $*"; }
bad()  { echo "❌ $*"; FAIL=1; }
stamp() { date +%Y%m%d_%H%M%S; }
# put SRC DST MODE OWNER — ставит файл, если отличается; старую версию — в .bak
put() {
  local src=$1 dst=$2 mode=$3 own=$4
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then chmod "$mode" "$dst"; chown "$own" "$dst"; return 0; fi
  [ -f "$dst" ] && cp -p "$dst" "$dst.bak.$(stamp)"
  install -m "$mode" -o "${own%%:*}" -g "${own##*:}" "$src" "$dst"
}

[ "$(id -u)" -eq 0 ] || { echo "❌ запускать от root"; exit 1; }
[[ "$PORT" =~ ^[0-9]{1,5}$ ]] || { echo "❌ SERVER_PORT — число"; exit 1; }
. /etc/os-release 2>/dev/null || true
[ "${ID:-}" = ubuntu ] && ok "ОС: ${PRETTY_NAME:-Ubuntu}" || warn "ОС не Ubuntu (${PRETTY_NAME:-?}) — кит проверен на Ubuntu 24.04"

# 1. Пользователь brain: без пароля, без полного sudo
if id "$BRAIN" >/dev/null 2>&1; then ok "пользователь brain уже есть"
else adduser --disabled-password --gecos "" "$BRAIN" >/dev/null && ok "пользователь brain создан"; fi
passwd -l "$BRAIN" >/dev/null 2>&1 || true
if id -nG "$BRAIN" | tr ' ' '\n' | grep -qxE 'sudo|admin|wheel'; then
  gpasswd -d "$BRAIN" sudo >/dev/null 2>&1 || true; warn "brain убран из группы sudo (полного sudo у него быть не должно)"
fi

# 2. Swap 2G (4 ГБ RAM: claude + голос) и vm.swappiness=10
if [ -n "$(swapon --show --noheadings 2>/dev/null)" ]; then ok "swap уже есть: $(swapon --show --noheadings | awk '{print $3}' | head -1)"
else
  if [ ! -f /swapfile ]; then fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none; fi
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null 2>&1 || true
  swapon /swapfile && ok "swap 2G включён" || bad "swap не включился"
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
echo 'vm.swappiness=10' > /etc/sysctl.d/99-brain.conf
sysctl -q -p /etc/sysctl.d/99-brain.conf && ok "vm.swappiness=10"

# 3. Пакеты
if apt-get update -qq && apt-get install -y -qq ufw fail2ban unattended-upgrades python3 python3-venv \
     curl ca-certificates systemd-timesyncd >/dev/null; then
  ok "пакеты: ufw fail2ban unattended-upgrades python3-venv curl"
else
  # systemd-timesyncd может конфликтовать с chrony — пробуем без него
  apt-get install -y -qq ufw fail2ban unattended-upgrades python3 python3-venv curl ca-certificates >/dev/null \
    && warn "пакеты стоят, systemd-timesyncd — нет (часы держит другой сервис?)" || bad "apt-get install упал"
fi

# 4. Файрвол: всё входящее закрыто, кроме SSH. Порт сверяем с тем, что реально слушает sshd.
SSHD_PORTS=$(sshd -T 2>/dev/null | awk '$1=="port"{print $2}' | sort -u | tr '\n' ' ')
if ! echo " $SSHD_PORTS " | grep -q " $PORT "; then
  bad "sshd слушает порт(ы) [${SSHD_PORTS:-?}], а SERVER_PORT=$PORT — ufw НЕ включаю, чтобы не запереть вход"
else
  ufw default deny incoming >/dev/null
  ufw default allow outgoing >/dev/null
  ufw allow "$PORT/tcp" comment 'ssh (brain-link)' >/dev/null
  ufw --force enable >/dev/null && ok "ufw: deny incoming, открыт только $PORT/tcp" || bad "ufw не включился"
fi

# 5. fail2ban: sshd, бан 1 ч после 5 попыток
TMPJ=$(mktemp); sed "s/__SSH_PORT__/$PORT/" "$HERE/jail.local" > "$TMPJ"
put "$TMPJ" /etc/fail2ban/jail.local 0644 root:root; rm -f "$TMPJ"
systemctl enable --now fail2ban >/dev/null 2>&1 || true
systemctl restart fail2ban >/dev/null 2>&1 || true
sleep 2
fail2ban-client status sshd >/dev/null 2>&1 && ok "fail2ban: jail sshd работает" || bad "fail2ban: jail sshd не поднялся (journalctl -u fail2ban)"

# 6. Автообновления безопасности
put "$HERE/20auto-upgrades" /etc/apt/apt.conf.d/20auto-upgrades 0644 root:root
systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true
ok "unattended-upgrades включены"

# 7. Часы
timedatectl set-ntp true >/dev/null 2>&1 || true
for _ in 1 2 3 4 5 6; do
  [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = yes ] && break; sleep 5
done
[ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = yes ] && ok "часы синхронизированы (NTP)" \
  || warn "NTP включён, но ещё не синхронизирован — проверь через пару минут: timedatectl"

# 8. Папки brain
install -d -m 0750 -o "$BRAIN" -g "$BRAIN" "$BH"
chmod 0750 "$BH"
for d in memory memory/inbox memory/dialogues .claude .claude/skills .cache .local .local/bin .local/share \
         .local/share/brain-link .local/state .local/state/brain-bot .brain-sync .config; do
  install -d -m 0750 -o "$BRAIN" -g "$BRAIN" "$BH/$d"
done
install -d -m 0700 -o "$BRAIN" -g "$BRAIN" "$BH/.local/state/brain-bot"
ok "папки /home/brain (0750) готовы"

# 9. SSH-ключи brain: ключ админа + ключ синка с ограничением command=
install -d -m 0700 -o "$BRAIN" -g "$BRAIN" "$BH/.ssh"
AK=$BH/.ssh/authorized_keys
[ -f "$AK" ] || install -m 0600 -o "$BRAIN" -g "$BRAIN" /dev/null "$AK"
add_key() { # opts key label
  local opts=$1 key=$2 label=$3 body
  echo "$key" | ssh-keygen -l -f - >/dev/null 2>&1 || { bad "$label: это не публичный ключ"; return; }
  body=$(echo "$key" | awk '{print $2}')
  if grep -qF "$body" "$AK"; then ok "$label уже в authorized_keys"
  else echo "${opts:+$opts }$key" >> "$AK"; ok "$label добавлен"; fi
}
[ -n "${ADMIN_PUBKEY:-}" ] && add_key "" "$ADMIN_PUBKEY" "ключ админа" || warn "ADMIN_PUBKEY не задан — ключ админа не добавлен"
[ -n "${SYNC_PUBKEY:-}" ] && add_key 'restrict,command="/home/brain/.local/bin/brain_sync_server.py"' "$SYNC_PUBKEY" "ключ синка (restrict)" \
  || warn "SYNC_PUBKEY не задан — ключ синка не добавлен"
chown "$BRAIN:$BRAIN" "$AK"; chmod 0600 "$AK"
if [ -f "$HERE/brain_sync_server.py" ]; then
  put "$HERE/brain_sync_server.py" "$BH/.local/bin/brain_sync_server.py" 0755 root:root && ok "brain_sync_server.py установлен"
else warn "brain_sync_server.py рядом нет — поставит brain-link init"; fi

# 10. Секреты бота: только root
install -d -m 0755 -o root -g root /etc/brain-bot
install -d -m 0700 -o root -g root /etc/brain-bot/credentials
chmod 0700 /etc/brain-bot/credentials
ok "/etc/brain-bot/credentials 0700 root"

# 11. brain-admin + sudoers (через visudo -cf)
put "$HERE/brain-admin" /usr/local/sbin/brain-admin 0755 root:root
if visudo -cf "$HERE/sudoers-brain" >/dev/null; then
  put "$HERE/sudoers-brain" /etc/sudoers.d/brain 0440 root:root
  visudo -c >/dev/null && ok "sudoers: brain → только brain-admin" || bad "visudo -c ругается — проверь /etc/sudoers.d/brain"
else bad "sudoers-brain не прошёл visudo -cf — не установлен"; fi

# 12. Код бота, настройки claude, юниты (бот не включаем: ещё нет токенов — это шаг `brain-link bot`)
install -d -m 0755 -o root -g root /usr/local/lib/brain-bot "$BH/.config/brain-bot"
chown root:root "$BH/.config/brain-bot"
put "$HERE/brain_bot.py" /usr/local/lib/brain-bot/brain_bot.py 0755 root:root
put "$HERE/claude_settings.json" "/etc/brain-bot/claude_settings.json" 0644 root:root
for u in brain-bot.service brain-brief.service brain-brief.timer brain-watch.service brain-watch.timer; do
  TMPU=$(mktemp)
  if [[ "${OWNER_ID:-}" =~ ^[0-9]+$ ]]; then sed "s/__OWNER_ID__/$OWNER_ID/" "$HERE/systemd/$u" > "$TMPU"
  elif [ -f "/etc/systemd/system/$u" ] && grep -qE '^Environment=OWNER_ID=[0-9]+$' "/etc/systemd/system/$u"; then
    oid=$(sed -n 's/^Environment=OWNER_ID=//p' "/etc/systemd/system/$u"); sed "s/__OWNER_ID__/$oid/" "$HERE/systemd/$u" > "$TMPU"
  else cp "$HERE/systemd/$u" "$TMPU"; fi
  put "$TMPU" "/etc/systemd/system/$u" 0644 root:root; rm -f "$TMPU"
done
systemctl daemon-reload
grep -q '__OWNER_ID__' /etc/systemd/system/brain-bot.service \
  && warn "OWNER_ID не задан — бот не стартует, пока его не подставит brain-link bot (fail-closed)" \
  || ok "юниты brain-bot / brief / watch установлены"

# 13. Вход только по ключам — кладём ВЫКЛЮЧЕННЫМ, включает lockdown
put "$HERE/sshd_00-brain.conf" /etc/ssh/sshd_config.d/00-brain.conf.disabled 0644 root:root
ok "sshd 00-brain.conf.disabled положен (включит brain-link lockdown)"

# Итог
if [ "$FAIL" -eq 0 ]; then echo "ИТОГ: ✅ harden прошёл"; else echo "ИТОГ: ❌ есть ошибки — смотри строки с ❌"; fi
exit "$FAIL"
