#!/usr/bin/env bash
# mac_integration.sh — расписание brain-sync на macOS через настоящий шаблон plist и launchd (лаборатория).
# schedule → launchctl bootstrap gui/$UID → kickstart → ждём sync_status.json → bootout.
# Транспорт local передаётся штатным хуком лаборатории: BRAIN_SYNC_TRANSPORT=local:<папка> перед schedule —
# brain_link.py кладёт его в EnvironmentVariables plist и в аргументы (--transport). Запускается НАСТОЯЩИЙ
# scripts/brain_sync.py (шим не нужен). Только для GitHub Actions.
#
# Важно: launchd не наследует окружение этого скрипта, у фоновой задачи есть только HOME из plist.
# Поэтому BRAIN_CONFIG_DIR / BRAIN_IKIGAI_ENV НЕ переопределяем — всё живёт в штатных местах под
# фейковым HOME ($HOME/.config/brain, $HOME/.claude/ikigai_env.json), как у ученика.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="${REPO:-$(cd "$HERE/../.." && pwd)}"
WORK="${WORK:-${TMPDIR:-/tmp}/brain-lab}"
PY="$(command -v python3)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "PASS $*"; }
bad() { FAIL=$((FAIL+1)); echo "FAIL $*"; }

mkdir -p "$WORK"
export HOME="$WORK/machome"
unset BRAIN_CONFIG_DIR BRAIN_IKIGAI_ENV
CFG="$HOME/.config/brain"
WS="$WORK/workspace"; SRV="$WORK/server"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs" "$CFG" "$HOME/.claude/skills/brain-link" \
         "$WS/memory/inbox" "$WS/memory/dialogues" "$SRV/memory/inbox" "$SRV/memory/dialogues"
printf '# CLAUDE\n' > "$WS/CLAUDE.md"
printf '# MEMORY\nmac lab %s\n' "$(date +%s)" > "$WS/memory/MEMORY.md"
printf 'skill\n' > "$HOME/.claude/skills/brain-link/SKILL.md"
printf '{"workspace":"%s"}\n' "$WS" > "$HOME/.claude/ikigai_env.json"
export BRAIN_SYNC_TRANSPORT="local:$SRV"

mtime() { "$PY" -c 'import os,sys
try: print(repr(os.stat(sys.argv[1]).st_mtime))
except OSError: print(0)' "$1"; }
newer() { "$PY" -c 'import sys; sys.exit(0 if float(sys.argv[1]) > float(sys.argv[2]) else 1)' "$1" "$2"; }

# 1. рендер настоящего шаблона plist с лабораторным транспортом — читается ли plist, есть ли транспорт
"$PY" - "$REPO/brain-link/scripts" "$PY" "$HOME" "$SRV" <<'PY' && ok "настоящий шаблон plist рендерится, транспорт в env и argv" || bad "render_plist с транспортом"
import sys, plistlib
scripts, py, home, srv = sys.argv[1:5]
sys.path.insert(0, scripts)
import brain_link
t = brain_link.render_plist(py, scripts + "/brain_sync.py", home, "/usr/bin:/bin",
                            ["--transport", "local:" + srv], {"BRAIN_SYNC_TRANSPORT": "local:" + srv})
d = plistlib.loads(t.encode("utf-8"))
assert d["EnvironmentVariables"]["BRAIN_SYNC_TRANSPORT"] == "local:" + srv, d["EnvironmentVariables"]
assert d["ProgramArguments"][-2:] == ["--transport", "local:" + srv], d["ProgramArguments"]
assert d["EnvironmentVariables"]["HOME"] == home
print("render_plist ok")
PY

# 2. init через local-транспорт, затем schedule настоящим brain_link (plist → настоящий brain_sync.py)
"$PY" "$HERE/drive_link.py" -- init --yes --root "$WS" \
      --skills-dir "$HOME/.claude/skills" --transport "local:$SRV" >"$WORK/mac_init.json" 2>&1 \
  && ok "init (local) прошёл" || { bad "init (local) не прошёл"; tail -c 600 "$WORK/mac_init.json"; }
[ -f "$SRV/memory/MEMORY.md" ] && ok "init выгрузил MEMORY.md в «сервер»" || bad "MEMORY.md в «сервер» не доехал"

LABEL="com.ikigai.brain-sync"
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
out="$("$PY" "$HERE/drive_link.py" -- schedule --replace --root "$WS" --skills-dir "$HOME/.claude/skills" --wait 150 2>&1)"
rc=$?
echo "$out" | "$PY" -c 'import sys,json;d=json.loads([l for l in sys.stdin if l.strip()][-1]);print("  ",d.get("human","")[:300]);print("   lab_transport:",d.get("lab_transport"))' 2>/dev/null || echo "$out" | tail -3
[ $rc -eq 0 ] && ok "schedule: launchd принял задачу, пробный синк прошёл" || bad "schedule не прошёл (rc=$rc)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
if plutil -lint "$PLIST" >/dev/null 2>&1; then ok "plist проходит plutil -lint"; else bad "plist не проходит plutil -lint"; fi
"$PY" - "$PLIST" "$SRV" <<'PY' && ok "в установленном plist транспорт local (env + --transport)" || bad "в установленном plist нет лабораторного транспорта"
import sys, plistlib
d = plistlib.load(open(sys.argv[1], "rb"))
want = "local:" + sys.argv[2]
sys.exit(0 if d.get("EnvironmentVariables", {}).get("BRAIN_SYNC_TRANSPORT") == want
         and "--transport" in d["ProgramArguments"] else 1)
PY

# 3. launchd знает задачу + kickstart ещё раз → обновление sync_status.json
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then ok "launchd видит $LABEL"; else bad "launchd не видит $LABEL"; fi
STATUS="$CFG/sync_status.json"
before="$(mtime "$STATUS")"
printf '# MEMORY\nmac lab kickstart %s\n' "$(date +%s)" > "$WS/memory/MEMORY.md"
sleep 1
launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
upd=no
for _ in $(seq 1 40); do
  if newer "$(mtime "$STATUS")" "$before"; then upd=yes; break; fi
  sleep 3
done
[ "$upd" = yes ] && ok "kickstart обновил sync_status.json (≤2 мин)" || bad "sync_status.json не обновился после kickstart"
if [ -f "$STATUS" ]; then
  fails=$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1])).get('consecutive_failures',0))" "$STATUS" 2>/dev/null || echo "?")
  [ "$fails" = 0 ] && ok "синк по расписанию без ошибок" || { bad "синк по расписанию падает (ошибок подряд: $fails)"; cat "$STATUS"; }
else
  bad "sync_status.json нет вовсе"
fi
grep -q "kickstart" "$SRV/memory/MEMORY.md" 2>/dev/null && ok "правка памяти доехала до «сервера» фоновым синком" \
  || bad "правка памяти не доехала до «сервера» фоновым синком"
echo "--- журнал launchd (хвост)"; tail -n 5 "$HOME/Library/Logs/brain-sync.log" 2>/dev/null | cut -c1-300 || true

# 4. bootout — снять задачу
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
sleep 1
launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 && bad "задача осталась после bootout" || ok "bootout снял задачу"

echo "----"; echo "mac-integration: $PASS PASS, $FAIL FAIL"
[ "$FAIL" -eq 0 ]
