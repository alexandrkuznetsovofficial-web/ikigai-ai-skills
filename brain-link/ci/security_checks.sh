#!/usr/bin/env bash
# security_checks.sh — защитные регресс-проверки связки brain-link (RT-6…RT-16).
# Каждая проверка УТВЕРЖДАЕТ, что защита сработала: отказ, ничего не записано, ничего не утекло.
# Запускается ПОСЛЕ server_e2e.sh в том же job (сервер brain уже поднят на 127.0.0.1:2222).
# Только локальное тестовое окружение раннера. Для TOCTOU — временная приманка в $RUNNER_TEMP,
# НИКОГДА реальные системные пути (/etc/shadow и т.п.) как цели.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="${REPO:-$(cd "$HERE/../.." && pwd)}"
WORK="${WORK:-${RUNNER_TEMP:-/tmp}/brain-lab}"
PORT=2222
PY="$(command -v python3)"
PASS=0; FAIL=0
LOG="$WORK/security_checks.log"
mkdir -p "$WORK"; : > "$LOG"

ok()  { PASS=$((PASS+1)); echo "PASS $*" | tee -a "$LOG"; }
bad() { FAIL=$((FAIL+1)); echo "FAIL $*" | tee -a "$LOG"; }
note(){ echo "   · $*" | tee -a "$LOG"; }

ADMINKEY="$WORK/laphome/.ssh/id_ed25519"
SYNCKEY="$WORK/laphome/.ssh/brain_sync_ed25519"
KH="-o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p $PORT"
RBRAIN() { ssh -i "$ADMINKEY" $KH "brain@127.0.0.1" "$1" 2>>"$LOG"; }     # обычный вход brain (admin-ключ)
RROOT()  { ssh -i "$ADMINKEY" $KH "root@127.0.0.1" "$1" 2>>"$LOG"; }
# вход ограниченным ключом синка: shell недоступен, работает только brain_sync_server.py
RSYNC()  { ssh -i "$SYNCKEY" $KH "brain@127.0.0.1" "$@" 2>>"$LOG"; }

# предусловие: e2e поднял сервер (sshd:2222 + пользователь brain + admin-ключ); иначе проверять нечего
if ! RROOT 'id brain' >/dev/null 2>&1; then
  bad "предусловие: нет входа root по ключу на 127.0.0.1:$PORT или нет пользователя brain — e2e не дошёл до harden"
  echo "security_checks: $PASS PASS, $FAIL FAIL" | tee -a "$LOG"; exit 1
fi

# RT-6 — brain → root через update-bot с подложенным json.py/ast.py в cwd
rt6() {
  RBRAIN 'printf "import os\nopen(os.path.expanduser(\"~/rt6_pwned\"),\"w\").write(\"x\")\n" > /home/brain/.local/share/brain-link/server/json.py; cp /home/brain/.local/share/brain-link/server/json.py /home/brain/.local/share/brain-link/server/ast.py'
  RBRAIN 'rm -f ~/rt6_pwned'
  RBRAIN 'sudo -n brain-admin update-bot >/dev/null 2>&1 || true'
  local pwned; pwned="$(RBRAIN 'test -f ~/rt6_pwned && echo yes || echo no')"
  RBRAIN 'rm -f /home/brain/.local/share/brain-link/server/json.py /home/brain/.local/share/brain-link/server/ast.py ~/rt6_pwned'
  [ "$pwned" = no ] && ok "RT-6 update-bot не выполнил подложенный json.py/ast.py из cwd" \
                    || bad "RT-6 подложенный модуль выполнился под root"
}

# RT-7 — TOCTOU в remove-private: симлинк на ПРИМАНКУ (не системный путь) не даёт удалить цель
rt7() {
  local decoy="$WORK/rt7_decoy"; mkdir -p "$decoy"; echo keep > "$decoy/important"
  # создаём «личную» зону и симлинк на приманку внутри memory от имени brain
  RBRAIN "mkdir -p /home/brain/memory/personal && ln -sfn '$decoy' /home/brain/memory/rt7_link"
  RROOT "yes YES | /usr/local/sbin/brain-admin remove-private >/dev/null 2>&1 || true"
  local alive; [ -f "$decoy/important" ] && alive=yes || alive=no
  RBRAIN 'rm -rf /home/brain/memory/personal /home/brain/memory/rt7_link'
  [ "$alive" = yes ] && ok "RT-7 remove-private не прошёл по симлинку в приманку (цель цела)" \
                     || bad "RT-7 содержимое приманки удалено через симлинк"
}

# RT-8 — одна строка sudo -l, инъекция в аргумент отклонена, симлинк на «shadow-приманку» в update-bot отклонён
rt8() {
  local lines; lines="$(RBRAIN "sudo -n -l 2>/dev/null | grep -cE '/usr/local/sbin/brain-admin'")"
  local allall; allall="$(RBRAIN "sudo -n -l 2>/dev/null | grep -cE '\(ALL( : ALL)?\) (NOPASSWD: )?ALL'")"
  { [ "$lines" -ge 1 ] && [ "$allall" = 0 ]; } && ok "RT-8 sudo у brain — только brain-admin, без ALL" \
    || bad "RT-8 sudo у brain шире одной строки (brain-admin=$lines, ALL=$allall)"
  local inj; inj="$(RBRAIN "sudo -n brain-admin 'logs;id' >/dev/null 2>&1 && echo ran || echo refused")"
  [ "$inj" = refused ] && ok "RT-8 brain-admin отклонил инъекцию в аргумент (logs;id)" \
                       || bad "RT-8 инъекция в аргумент brain-admin прошла"
  # «shadow-приманка»: НЕ /etc/shadow, а наш файл; подменяем код бота симлинком — safe_install читает от brain
  local decoy="$WORK/rt8_secret"; echo "lab-secret-$RANDOM" > "$decoy"; chmod 600 "$decoy"
  RBRAIN "ln -sfn '$decoy' /home/brain/.local/share/brain-link/server/brain_bot.py"
  local before; before="$(RROOT 'cat /usr/local/lib/brain-bot/brain_bot.py 2>/dev/null | head -c 40')"
  RBRAIN 'sudo -n brain-admin update-bot >/dev/null 2>&1 || true'
  local leaked; leaked="$(RROOT "grep -l lab-secret /usr/local/lib/brain-bot/brain_bot.py 2>/dev/null")"
  # вернуть настоящий код бота в копию кита brain
  cat "$REPO/brain-link/server/brain_bot.py" | RBRAIN 'cat > /home/brain/.local/share/brain-link/server/brain_bot.py'
  [ -z "$leaked" ] && ok "RT-8 update-bot по симлинку на приманку не подставил чужой файл" \
                   || bad "RT-8 содержимое приманки уехало в код бота"
}

# RT-9 — ограниченный ключ синка: shell нет, «manifest;id» нет, port-forward нет, SetEnv BRAIN_ROOT игнор
rt9() {
  local sh; sh="$(RSYNC 'id' 2>/dev/null)"
  [ -z "$sh" ] && ok "RT-9 ключ синка не даёт shell (id пуст)" || bad "RT-9 ключ синка выполнил id: $sh"
  local inj; RSYNC 'manifest;id' >/dev/null 2>&1 && inj=ran || inj=refused
  [ "$inj" = refused ] && ok "RT-9 'manifest;id' отклонён (command= фиксирован)" || bad "RT-9 'manifest;id' прошёл"
  # проброс порта запрещён (restrict → no-port-forwarding)
  if timeout 10 ssh -i "$SYNCKEY" $KH -N -L "127.0.0.1:0:127.0.0.1:22" "brain@127.0.0.1" >/dev/null 2>&1; then
    bad "RT-9 проброс порта удался"; else ok "RT-9 проброс порта запрещён"; fi
  # SetEnv BRAIN_ROOT игнорируется: manifest отвечает про /home/brain, а не про приманку
  local decoy="$WORK/rt9_fakeroot"; mkdir -p "$decoy/memory"; echo evil > "$decoy/memory/evil.md"
  local out; out="$(printf '{}' | ssh -i "$SYNCKEY" $KH -o SetEnv="BRAIN_ROOT=$decoy" "brain@127.0.0.1" manifest 2>>"$LOG")"
  echo "$out" | grep -q evil.md && bad "RT-9 SetEnv BRAIN_ROOT увёл manifest на приманку" \
    || ok "RT-9 SetEnv BRAIN_ROOT проигнорирован (manifest не про приманку)"
}

# RT-10 — враждебные архивы: apply отказывает, ничего не записано (honest control — принимается)
rt10() {
  local tars="$WORK/rt10"; "$PY" "$HERE/hostile_tar.py" "$tars" >/dev/null
  local allok=1
  while read -r name expect; do
    local rc out
    out="$(RSYNC apply < "$tars/$name.tgz" 2>>"$LOG")"; rc=$?
    if [ "$expect" = refuse ]; then
      [ "$rc" = 3 ] || { bad "RT-10 $name: ждали отказ, rc=$rc"; allok=0; }
    else
      [ "$rc" = 0 ] || { bad "RT-10 $name(control): ждали приём, rc=$rc"; allok=0; }
    fi
  done < <("$PY" -c "import json,sys;[print(c['name'],c['expect']) for c in json.load(open('$tars/index.json'))]")
  # ничего враждебного не записано на сервер
  local escaped; escaped="$(RBRAIN 'ls /home/brain/rt10_escape.md /tmp/rt10_abs.md /home/brain/memory/personal/rt10.md /home/brain/.ssh/authorized_keys.rt10 2>/dev/null')"
  [ -z "$escaped" ] || { bad "RT-10 на сервере появились враждебные файлы: $escaped"; allok=0; }
  [ "$allok" = 1 ] && ok "RT-10 все враждебные архивы отклонены, записи нет; честный — принят"
  RBRAIN 'rm -f /home/brain/memory/rt10_good.md /home/brain/memory/rt10_control.md' >/dev/null 2>&1 || true
}

# RT-11 — /run/credentials/brain-bot.service/* не читается от brain вне юнита
rt11() {
  local r; r="$(RBRAIN 'cat /run/credentials/brain-bot.service/claude_token 2>&1 | head -c 20; echo')"
  echo "$r" | grep -qiE 'sk-ant|[0-9]{8}:' && bad "RT-11 brain прочитал credentials вне юнита: ${r:0:12}…" \
    || ok "RT-11 /run/credentials недоступен brain вне юнита"
}

# RT-12 — токен не в /proc/*/cmdline во время verify/audit (сторож на хосте, от root)
rt12() {
  if [ ! -s "$WORK/tok_claude" ] || [ ! -s "$WORK/tok_bot" ]; then
    bad "RT-12 не проверено: e2e не дошёл до put-token (нет сгенерированных токенов)"; return 0; fi
  local stop="$WORK/rt12.stop" out="$WORK/rt12.json"
  rm -f "$stop" "$out"
  sudo "$PY" "$HERE/cmdline_watch.py" --secret-file "$WORK/tok_claude" --secret-file "$WORK/tok_bot" \
       --stop "$stop" --out "$out" --interval 0.02 &
  local wpid=$!
  sleep 0.3
  # нагрузка: несколько вызовов audit/verify/selftest, под которыми не должно быть токена в cmdline
  RROOT '/usr/local/sbin/brain-admin selftest >/dev/null 2>&1 || true'
  RROOT '/usr/local/sbin/brain-admin status >/dev/null 2>&1 || true'
  "$PY" "$HERE/bot_scenario.py" say --tg http://127.0.0.1:18081 --owner 111111111 "лабораторный вопрос для cmdline" >/dev/null 2>&1 || true
  sleep 1
  sudo touch "$stop"; wait "$wpid" 2>/dev/null || true
  local hits; hits="$("$PY" -c "import json;d=json.load(open('$out'));print(len(d.get('hits',[])),d.get('scans'))" 2>/dev/null)"
  case "$hits" in
    0\ *) ok "RT-12 токен не встречался в /proc/*/cmdline (сканов: ${hits#0 })" ;;
    *)    bad "RT-12 токен найден в cmdline: $hits" ;;
  esac
}

# RT-15 — журналы бота без токенов
rt15() {
  local n; n="$(RROOT "journalctl -u brain-bot -u brain-brief -u brain-watch -n 2000 --no-pager 2>/dev/null | grep -cE 'sk-ant-[A-Za-z0-9_-]{10,}|[0-9]{8,10}:[A-Za-z0-9_-]{30,}'")"
  [ "${n:-0}" = 0 ] && ok "RT-15 в журналах бота токенов нет" || bad "RT-15 в журналах бота найдено токенов: $n"
}

# RT-16 — новый skills/evil «на сервере» не попадает на компьютер после прогона синка
rt16() {
  RBRAIN 'mkdir -p /home/brain/.claude/skills/evil && echo evil > /home/brain/.claude/skills/evil/SKILL.md'
  # прогон синка с компьютера (local-транспорт шима смотрит в настоящий /home/brain? нет —
  # используем настоящий ssh-синк: brain_sync через ключ синка). Запускаем обычный run.
  BRAIN_CONFIG_DIR="$WORK/cfg-brain" HOME="$WORK/laphome" BRAIN_IKIGAI_ENV="$WORK/ikigai_env.json" \
    "$PY" "$REPO/brain-link/scripts/brain_sync.py" run --root "$WORK/workspace" \
    --skills-dir "$WORK/laphome/.claude/skills" >/dev/null 2>>"$LOG" || true
  local leaked; [ -e "$WORK/laphome/.claude/skills/evil/SKILL.md" ] && leaked=yes || leaked=no
  RBRAIN 'rm -rf /home/brain/.claude/skills/evil'
  [ "$leaked" = no ] && ok "RT-16 чужой скилл с сервера не прилетел на компьютер (сервер→компьютер только inbox/dialogues)" \
    || bad "RT-16 чужой скилл с сервера оказался на компьютере"
}

# Доп.: личное/.env/.session не уехали на сервер (проверка исключений синка)
extra_private() {
  RBRAIN 'ls -d /home/brain/memory/personal /home/brain/*.session /home/brain/memory/*.env 2>/dev/null' > "$WORK/priv.out" 2>/dev/null || true
  [ -s "$WORK/priv.out" ] && bad "личное/секреты на сервере: $(cat "$WORK/priv.out" | tr '\n' ' ')" \
    || ok "личного/.env/.session на сервере нет"
}

for fn in rt6 rt7 rt8 rt9 rt10 rt11 rt12 rt15 rt16 extra_private; do
  echo "=== $fn ===" | tee -a "$LOG"
  "$fn" || true
done

echo "----" | tee -a "$LOG"
echo "security_checks: $PASS PASS, $FAIL FAIL" | tee -a "$LOG"
[ "$FAIL" -eq 0 ]
