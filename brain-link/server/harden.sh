#!/usr/bin/env bash
# harden.sh — kit 2.3 (brain-link). Подготовка чистого Ubuntu 24.04 под «базу» второго мозга.
# Запуск от root (до lockdown), идемпотентно: повторный прогон ничего не ломает, только досоздаёт.
#
#   ADMIN_PUBKEY="ssh-ed25519 AAAA… you@laptop" \
#   SYNC_PUBKEY="ssh-ed25519 AAAA… brain-sync"  \
#   SERVER_PORT=22 OWNER_ID=123456789 BOT_TZ=Europe/Moscow bash harden.sh
#
# BOT_TZ (по умолчанию Europe/Moscow) — часовой пояс владельца: брифинг приходит в 08:00 по нему.
# BRAIN_LAB_SKIP_UFW_ENABLE=1 — ТОЛЬКО ДЛЯ ТЕСТОВ (лаборатория CI): правила ufw кладутся, `ufw enable` — нет.
# На контейнерных VPS (OpenVZ/LXC) ufw/swap могут быть недоступны: harden не обрывается,
# помечает шаг ❌ и доделывает остальное; итог тогда ❌.
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
TZ_NAME=${BOT_TZ:-Europe/Moscow}
BAK_DIR=/var/backups/brain-link
# kit 2.1 (RT-11): бот — системный пользователь brainbot (группа brain, nologin), состояние — /var/lib/brain-bot
BOT=brainbot
BOT_STATE=/var/lib/brain-bot
CLAUDE_CFG=$BOT_STATE/claude-config
FAIL=0

ok()   { echo "✅ $*"; }
warn() { echo "🟡 $*"; }
bad()  { echo "❌ $*"; FAIL=1; }
stamp() { date +%Y%m%d_%H%M%S; }
# put SRC DST MODE OWNER — ставит файл, если отличается. Старую версию — в /var/backups/brain-link/,
# а НЕ рядом: apt.conf.d, sudoers.d, sshd_config.d и systemd читают «соседей» (.bak рядом — мусор или вред).
put() {
  local src=$1 dst=$2 mode=$3 own=$4
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then chmod "$mode" "$dst"; chown "$own" "$dst"; return 0; fi
  if [ -f "$dst" ]; then
    install -d -m 0700 -o root -g root "$BAK_DIR"
    cp -p "$dst" "$BAK_DIR/$(echo "${dst#/}" | tr '/' '_').$(stamp)"
  fi
  install -m "$mode" -o "${own%%:*}" -g "${own##*:}" "$src" "$dst"
}

[ "$(id -u)" -eq 0 ] || { echo "❌ запускать от root"; exit 1; }
[[ "$PORT" =~ ^[0-9]{1,5}$ ]] || { echo "❌ SERVER_PORT — число"; exit 1; }
if [[ ! "$TZ_NAME" =~ ^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+){0,2}$ ]] || [ ! -f "/usr/share/zoneinfo/$TZ_NAME" ]; then
  echo "❌ BOT_TZ=$TZ_NAME — нет такого часового пояса (пример: Europe/Moscow, Asia/Almaty)"; exit 1
fi
# Ключ админа и ключ синка обязаны различаться: ключ синка ограничен command=, и если это тот же
# ключ — либо админ теряет вход, либо синк получает полный shell под brain.
key_body() { echo "$1" | awk '{print $2}'; }
if [ -n "${ADMIN_PUBKEY:-}" ] && [ -n "${SYNC_PUBKEY:-}" ] && [ "$(key_body "$ADMIN_PUBKEY")" = "$(key_body "$SYNC_PUBKEY")" ]; then
  echo "❌ ADMIN_PUBKEY и SYNC_PUBKEY — один и тот же ключ. Для синка нужен отдельный ключ (brain-link keys)"; exit 1
fi
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
  if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none 2>/dev/null || rm -f /swapfile
  fi
  if [ -f /swapfile ]; then
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null 2>&1 || true
    if swapon /swapfile 2>/dev/null; then
      ok "swap 2G включён"
      grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    else bad "swap не включился (контейнерный VPS? тогда swap даёт провайдер)"; fi
  else bad "не удалось создать /swapfile"; fi
fi
echo 'vm.swappiness=10' > /etc/sysctl.d/99-brain.conf
sysctl -q -p /etc/sysctl.d/99-brain.conf 2>/dev/null && ok "vm.swappiness=10" || warn "vm.swappiness не применился (контейнерный VPS?)"

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
# Каждый вызов ufw — с `|| bad`: в контейнере (нет iptables/модулей) ufw падает, а harden обязан доделать остальное.
SSHD_PORTS=$( (sshd -T 2>/dev/null || true) | awk '$1=="port"{print $2}' | sort -u | tr '\n' ' ')
if ! command -v ufw >/dev/null 2>&1; then
  bad "ufw недоступен (не установился) — файрвол не включён"
elif ! echo " $SSHD_PORTS " | grep -q " $PORT "; then
  bad "sshd слушает порт(ы) [${SSHD_PORTS:-?}], а SERVER_PORT=$PORT — ufw НЕ включаю, чтобы не запереть вход"
elif [ "${BRAIN_LAB_SKIP_UFW_ENABLE:-0}" = 1 ]; then
  # ТОЛЬКО ДЛЯ ТЕСТОВ (лаборатория CI в контейнере): правила кладём, файрвол не включаем
  if ufw default deny incoming >/dev/null 2>&1 && ufw default allow outgoing >/dev/null 2>&1 \
     && ufw allow "$PORT/tcp" comment 'ssh (brain-link)' >/dev/null 2>&1; then
    warn "ufw: правила добавлены, ufw enable пропущено: лаборатория (BRAIN_LAB_SKIP_UFW_ENABLE=1)"
  else bad "ufw: правила не добавились (лаборатория)"; fi
elif ufw default deny incoming >/dev/null 2>&1 \
     && ufw default allow outgoing >/dev/null 2>&1 \
     && ufw allow "$PORT/tcp" comment 'ssh (brain-link)' >/dev/null 2>&1 \
     && ufw --force enable >/dev/null 2>&1; then
  ok "ufw: deny incoming, открыт только $PORT/tcp"
else
  bad "ufw недоступен (контейнерный VPS?) — файрвол не включён, закрой порты в панели провайдера"
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
for d in memory .claude .claude/skills .cache .local .local/bin .local/share \
         .local/share/brain-link .local/state .brain-sync .config; do
  install -d -m 0750 -o "$BRAIN" -g "$BRAIN" "$BH/$d"
done
# inbox и dialogues пишет бот (brainbot, группа brain), читает и переносит в .synced синк (brain): 2770, setgid
for d in memory/inbox memory/dialogues; do install -d -m 2770 -o "$BRAIN" -g "$BRAIN" "$BH/$d"; done
ok "папки /home/brain (0750, inbox и dialogues 2770) готовы"
# Пользователь бота, его состояние (/var/lib/brain-bot 0700 brainbot: конфиг Claude Code бота — CLAUDE_CONFIG_DIR,
# безопасный режим, итоги самопроверки), права памяти и перенос с ранних установок — шаг 11б (brain-admin bot-user).

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

# 11б. Пользователь бота brainbot: токены LoadCredential и состояние бота недоступны brain (RT-11)
if /usr/local/sbin/brain-admin bot-user >/tmp/brain-botuser.$$ 2>&1; then ok "пользователь бота $BOT, $BOT_STATE (0700), права памяти"
else bad "пользователь бота: $(grep -E '❌|🟡' /tmp/brain-botuser.$$ | head -2 | tr '\n' ' ')"; fi
rm -f /tmp/brain-botuser.$$

# 12. Код бота, настройки claude, юниты (бот не включаем: ещё нет токенов — это шаг `brain-link bot`)
# kit 2.3: brain-bot.service может быть ЧУЖИМ (мост claude-code-telegram, бот июльского кита, «настроил свой
# Claude»). Свой — только если ExecStart запускает /usr/local/lib/brain-bot/brain_bot.py. Чужой harden не
# перезаписывает и не перезапускает: его выключит шаг `brain-link bot` по «да» человека (копия юнита — в $BAK_DIR).
FOREIGN_BOT=0
if [ "$(systemctl show -p LoadState --value brain-bot.service 2>/dev/null)" = loaded ] \
   && ! systemctl show -p ExecStart --value brain-bot.service 2>/dev/null | grep -qF /usr/local/lib/brain-bot/brain_bot.py; then
  FOREIGN_BOT=1
elif [ -f /etc/systemd/system/brain-bot.service ] && ! grep -qF /usr/local/lib/brain-bot/brain_bot.py /etc/systemd/system/brain-bot.service; then
  FOREIGN_BOT=1
fi
install -d -m 0755 -o root -g root /usr/local/lib/brain-bot "$BH/.config/brain-bot"
chown root:root "$BH/.config/brain-bot"
put "$HERE/brain_bot.py" /usr/local/lib/brain-bot/brain_bot.py 0755 root:root
put "$HERE/claude_settings.json" "/etc/brain-bot/claude_settings.json" 0644 root:root
for u in brain-bot.service brain-brief.service brain-brief.timer brain-watch.service brain-watch.timer; do
  if [ "$u" = brain-bot.service ] && [ "$FOREIGN_BOT" = 1 ]; then
    warn "brain-bot.service — чужой бот ($(systemctl show -p ExecStart --value brain-bot.service 2>/dev/null | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -1)): не трогаю, его выключит шаг bot по «да»"
    continue
  fi
  TMPU=$(mktemp)
  # Часовой пояс: в юнитах по умолчанию Europe/Moscow (Environment=BOT_TZ и OnCalendar таймера)
  if [[ "${OWNER_ID:-}" =~ ^[0-9]+$ ]]; then sed -e "s/__OWNER_ID__/$OWNER_ID/" -e "s#Europe/Moscow#$TZ_NAME#g" "$HERE/systemd/$u" > "$TMPU"
  elif [ -f "/etc/systemd/system/$u" ] && grep -qE '^Environment=OWNER_ID=[0-9]+$' "/etc/systemd/system/$u"; then
    oid=$(sed -n 's/^Environment=OWNER_ID=//p' "/etc/systemd/system/$u"); sed -e "s/__OWNER_ID__/$oid/" -e "s#Europe/Moscow#$TZ_NAME#g" "$HERE/systemd/$u" > "$TMPU"
  else sed "s#Europe/Moscow#$TZ_NAME#g" "$HERE/systemd/$u" > "$TMPU"; fi
  put "$TMPU" "/etc/systemd/system/$u" 0644 root:root; rm -f "$TMPU"
done
systemctl daemon-reload
# повторный harden на ранней установке: работающий бот ещё под brain — перезапуск переводит его на brainbot
if [ "$FOREIGN_BOT" = 0 ] && systemctl is-active --quiet brain-bot.service 2>/dev/null; then
  systemctl restart brain-bot.service >/dev/null 2>&1 && ok "бот перезапущен под $(systemctl show -p User --value brain-bot.service)" \
    || bad "бот не перезапустился: journalctl -u brain-bot -n 50"
fi
if command -v systemd-analyze >/dev/null 2>&1; then
  systemd-analyze calendar "*-*-* 08:00:00 $TZ_NAME" >/dev/null 2>&1 && ok "брифинг в 08:00 по $TZ_NAME" \
    || bad "systemd не понимает OnCalendar с поясом $TZ_NAME (нужен systemd ≥ 235)"
fi
# Юниты бота запрещают сеть к localhost (IPAddressDeny=localhost), кроме 127.0.0.53 — stub systemd-resolved.
# Если DNS на сервере идёт через другой локальный адрес (dnsmasq 127.0.0.1 и т.п.), бот не резолвит имена.
NS=$(awk '$1=="nameserver"{print $2}' /etc/resolv.conf 2>/dev/null | tr '\n' ' ')
case " $NS " in
  *" 127.0.0.53 "*) ok "DNS через systemd-resolved (127.0.0.53) — бот его видит" ;;
  *" 127."*|*" ::1 "*) bad "DNS через локальный адрес [$NS], не 127.0.0.53: бот (IPAddressDeny=localhost) не сможет резолвить имена — добавь адрес в IPAddressAllow юнитов" ;;
  *) ok "DNS: [$NS] (не loopback) — IPAddressDeny=localhost не мешает" ;;
esac
if [ "$FOREIGN_BOT" = 1 ]; then ok "юниты brain-brief / brain-watch установлены (brain-bot поставит шаг bot)"
else grep -q '__OWNER_ID__' /etc/systemd/system/brain-bot.service \
  && warn "OWNER_ID не задан — бот не стартует, пока его не подставит brain-link bot (fail-closed)" \
  || ok "юниты brain-bot / brief / watch установлены"
fi

# 12б. Приманки самопроверки безопасности: ФАЛЬШИВЫЕ уникальные CANARY-значения (настоящие токены — никогда).
# /etc/brain-bot/canary (root 0600), ~/.config/brain-canary и ~/.claude/.canary-credentials.json (brain 0600),
# список значений — /etc/brain-bot/canary.list (root 0600, боту его отдаёт LoadCredential=canary_list).
if /usr/local/sbin/brain-admin canary-init >/tmp/brain-canary.$$ 2>&1; then ok "приманки самопроверки на месте"
else bad "приманки самопроверки не легли: $(grep -E '❌|🟡' /tmp/brain-canary.$$ | head -2 | tr '\n' ' ')"; fi
rm -f /tmp/brain-canary.$$

# 13. Вход только по ключам — кладём ВЫКЛЮЧЕННЫМ, включает lockdown
put "$HERE/sshd_00-brain.conf" /etc/ssh/sshd_config.d/00-brain.conf.disabled 0644 root:root
ok "sshd 00-brain.conf.disabled положен (включит brain-link lockdown)"

# 14. Старые .bak, которые прошлые версии кита клали рядом с конфигами, — переносим в $BAK_DIR
for f in /etc/apt/apt.conf.d/20auto-upgrades.bak.* /etc/sudoers.d/brain.bak.* /etc/fail2ban/jail.local.bak.* \
         /etc/ssh/sshd_config.d/00-brain.conf.disabled.bak.* /etc/systemd/system/brain-*.bak.* \
         /etc/brain-bot/claude_settings.json.bak.* /usr/local/lib/brain-bot/brain_bot.py.bak.*; do
  [ -f "$f" ] || continue
  install -d -m 0700 -o root -g root "$BAK_DIR"
  mv -f "$f" "$BAK_DIR/$(echo "${f#/}" | tr '/' '_')" && warn "старая копия $f перенесена в $BAK_DIR"
done

# Итог
if [ "$FAIL" -eq 0 ]; then echo "ИТОГ: ✅ harden прошёл"; else echo "ИТОГ: ❌ есть ошибки — смотри строки с ❌"; fi
exit "$FAIL"
