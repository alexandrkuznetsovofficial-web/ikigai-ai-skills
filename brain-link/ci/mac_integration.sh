#!/usr/bin/env bash
# mac_integration.sh — расписание brain-sync на macOS через настоящий шаблон plist и launchd (лаборатория).
# schedule → launchctl bootstrap gui/$UID → kickstart → ждём sync_status.json → bootout. Транспорт — local
# (через sync_shim.py: у schedule нет сквозной передачи транспорта, см. ci/README.md). Только для Actions.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="${REPO:-$(cd "$HERE/../.." && pwd)}"
WORK="${WORK:-${TMPDIR:-/tmp}/brain-lab}"
PY="$(command -v python3)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "PASS $*"; }
bad() { FAIL=$((FAIL+1)); echo "FAIL $*"; }

mkdir -p "$WORK"
export HOME="$WORK/machome"; export BRAIN_CONFIG_DIR="$WORK/cfg"; export BRAIN_IKIGAI_ENV="$WORK/env.json"
WS="$WORK/workspace"; SRV="$WORK/server"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs" "$BRAIN_CONFIG_DIR" \
         "$WS/memory/inbox" "$WS/memory/dialogues" "$HOME/.claude/skills/brain-link" \
         "$SRV/memory/inbox" "$SRV/memory/dialogues"
printf '# CLAUDE\n' > "$WS/CLAUDE.md"
printf '# MEMORY\nmac lab %s\n' "$(date +%s)" > "$WS/memory/MEMORY.md"
printf 'skill\n' > "$HOME/.claude/skills/brain-link/SKILL.md"
printf '{"workspace":"%s"}\n' "$WS" > "$BRAIN_IKIGAI_ENV"
echo "local:$SRV" > "$BRAIN_CONFIG_DIR/ci_transport.txt"

# 1. рендер настоящего шаблона plist напрямую из модуля — читается ли plist
"$PY" - <<PY || { bad "render_plist уронился на настоящем шаблоне"; }
import sys; sys.path.insert(0, "$REPO/brain-link/scripts")
import brain_link, plistlib
t = brain_link.render_plist("$PY", "$HERE/sync_shim.py", "$HOME", "$(dirname "$PY"):/usr/bin:/bin")
plistlib.loads(t.encode("utf-8")); print("render_plist ok")
PY
[ $? -eq 0 ] && ok "настоящий шаблон plist рендерится и парсится"

# 2. init через local-транспорт (шим), затем schedule настоящим brain_link (plist → sync_shim)
"$PY" "$HERE/drive_link.py" --sync-shim -- init --yes --root "$WS" \
      --skills-dir "$HOME/.claude/skills" --transport "local:$SRV" >/dev/null 2>&1 \
  && ok "init (local) прошёл" || bad "init (local) не прошёл"

LABEL="com.ikigai.brain-sync"
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
out="$("$PY" "$HERE/drive_link.py" --sync-shim -- schedule --root "$WS" --skills-dir "$HOME/.claude/skills" --wait 150 2>&1)"
rc=$?
echo "$out" | "$PY" -c 'import sys,json;d=json.loads([l for l in sys.stdin if l.strip()][-1]);print("  ",d.get("human","")[:200])' 2>/dev/null || echo "$out" | tail -2
[ $rc -eq 0 ] && ok "schedule: launchd принял задачу, пробный синк прошёл" || bad "schedule не прошёл (rc=$rc)"

# 3. launchd знает задачу + kickstart ещё раз → обновление sync_status.json
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then ok "launchd видит $LABEL"; else bad "launchd не видит $LABEL"; fi
before=$(stat -f %m "$BRAIN_CONFIG_DIR/sync_status.json" 2>/dev/null || echo 0)
launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
upd=no
for _ in $(seq 1 40); do
  now=$(stat -f %m "$BRAIN_CONFIG_DIR/sync_status.json" 2>/dev/null || echo 0)
  if [ "$now" -gt "$before" ]; then upd=yes; break; fi
  sleep 3
done
[ "$upd" = yes ] && ok "kickstart обновил sync_status.json (≤2 мин)" || bad "sync_status.json не обновился после kickstart"
fails=$("$PY" -c "import json;print(json.load(open('$BRAIN_CONFIG_DIR/sync_status.json')).get('consecutive_failures',0))" 2>/dev/null || echo 0)
[ "${fails:-0}" = 0 ] && ok "синк по расписанию без ошибок" || bad "синк по расписанию падает (ошибок подряд: $fails)"

# 4. bootout — снять задачу
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 && bad "задача осталась после bootout" || ok "bootout снял задачу"

echo "----"; echo "mac-integration: $PASS PASS, $FAIL FAIL"
[ "$FAIL" -eq 0 ]
