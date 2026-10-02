#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
brain_sync.py — синк «компьютер — мастерская, сервер — база» (kit 2.1, KIT_CONVENTIONS §8).

Команды (Mac: python3, Windows: py -3 / pythonw для расписания):
  run [--dry-run] [--allow-mass-delete]   обычный прогон (его запускает расписание каждые 5 минут)
  status                                  последний успех, ошибки подряд, пауза — без сети
  pause [--reason "…"] / resume           пауза перед массовой правкой памяти и снятие паузы
  init [--yes] [--force]                  первая выгрузка на чистый сервер (без --yes — только отчёт)
  adopt [--yes] [--pull-private]          переход со старой модели «истина на сервере» (без --yes — отчёт)
Общие флаги: --root <рабочая папка> · --skills-dir <папка скиллов> · --transport ssh | local:<папка>
Без команды — run.

Зоны: компьютер владеет CLAUDE.md, memory/** (кроме inbox/ и dialogues/) и ~/.claude/skills/**;
бот владеет memory/inbox/ и memory/dialogues/ (только забираем). Решения — по sha содержимого.
Вывод — один JSON с полем human. Коды: 0 ок · 1 конфиг/аргументы · 2 ssh не пустил / ключ сервера ·
3 нужно решение человека (массовое удаление, ветка B) · 4 сервер/сеть.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brainlib as bl  # noqa: E402

SERVER_SCRIPT = Path(__file__).resolve().parent.parent / "server" / "brain_sync_server.py"
LIST_CAP = 40


# ---------- служебные файлы ----------
def cfg_dir():
    d = bl.config_dir()
    d.mkdir(parents=True, exist_ok=True)
    if not bl.IS_WINDOWS:
        try:
            os.chmod(str(d), 0o700)
        except OSError:
            pass
    return d


def p_state():
    return cfg_dir() / "sync_state.json"


def p_status():
    return cfg_dir() / "sync_status.json"


def p_pause():
    return cfg_dir() / "sync.pause"


def p_lock():
    return cfg_dir() / "sync.lock"


# ---------- lock ----------
def acquire_lock():
    lock = p_lock()
    for attempt in (1, 2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, json.dumps({"pid": os.getpid(), "since": time.time()}).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                continue
            if age > bl.LOCK_STALE_SEC and attempt == 1:
                bl.get_logger().warning("снят протухший lock (%d с)", age)
                try:
                    lock.unlink()
                except OSError:
                    pass
                continue
            return False
    return False


def release_lock():
    try:
        p_lock().unlink()
    except OSError:
        pass


# ---------- транспорт ----------
class Transport:
    """ssh к brain_sync_server.py (ключ с command=) или local:<папка> — тот же сервер подпроцессом, для тестов."""

    def __init__(self, spec):
        spec = spec or "ssh"
        self.warnings = []
        if spec.startswith("local:"):
            self.kind = "local"
            self.root = Path(spec[len("local:"):]).expanduser().resolve()
            self.ident = "local:%s" % self.root
            self.shown = self.ident
        elif spec == "ssh":
            self.kind = "ssh"
            self.access, self.warnings = bl.read_access()
            a = self.access
            if not a.get("SERVER_IP"):
                raise bl.CliExit(bl.EXIT_CONFIG, "в файле доступа нет SERVER_IP")
            if not bl.sync_key_path().exists():
                raise bl.CliExit(bl.EXIT_CONFIG, "нет ключа синка %s — пройди шаг keys" % bl.sync_key_path())
            if not (bl.config_dir() / "known_hosts").exists():
                raise bl.CliExit(bl.EXIT_CONFIG, "ключ сервера не закреплён (нет ~/.config/brain/known_hosts) — пройди шаг keys")
            self.ident = "ssh:%s@%s:%s" % (a.get("SERVER_USER"), a.get("SERVER_IP"), a.get("SERVER_PORT"))
            self.shown = "ssh:%s@%s" % (a.get("SERVER_USER"), bl.mask_ip(a.get("SERVER_IP")))
        else:
            raise bl.CliExit(bl.EXIT_CONFIG, "--transport: ssh или local:<папка>")

    def argv(self, sub):
        if self.kind == "local":
            return [sys.executable, str(SERVER_SCRIPT), sub]
        # пользователь синка на сервере — brain (ключ синка стоит у него)
        a = dict(self.access)
        a["SERVER_USER"] = os.environ.get("BRAIN_SYNC_USER") or "brain"
        return bl.ssh_command(a, [sub])

    def call(self, sub, stdin_path, stdout_path, timeout):
        env = dict(os.environ)
        if self.kind == "local":
            env["BRAIN_ROOT"] = str(self.root)
            env.pop("SSH_ORIGINAL_COMMAND", None)
        with open(stdin_path, "rb") as fin, open(stdout_path, "wb") as fout:
            try:
                r = subprocess.run(self.argv(sub), stdin=fin, stdout=fout, stderr=subprocess.PIPE,
                                   timeout=timeout, env=env, creationflags=bl.no_window_flags())
            except subprocess.TimeoutExpired:
                raise bl.CliExit(bl.EXIT_PROVIDER, "сервер не ответил за %d с (%s) — синк повторится сам" % (timeout, sub))
            except OSError as ex:
                raise bl.CliExit(bl.EXIT_CONFIG, "не запустился ssh: %s" % ex)
        err = r.stderr.decode("utf-8", "replace").strip()
        if r.returncode != 0:
            if self.kind == "ssh" and r.returncode == 255:
                code, human = bl.classify_ssh_error(r.returncode, err)
                raise bl.CliExit(code, human, step=sub)
            if r.returncode == 3:
                raise bl.CliExit(bl.EXIT_PROVIDER, "сервер отказал (%s): %s" % (sub, err[-300:]), step=sub)
            raise bl.CliExit(bl.EXIT_PROVIDER, "ошибка на сервере (%s, код %d): %s" % (sub, r.returncode, err[-300:]),
                             step=sub)

    def json_call(self, sub, payload, tmp, timeout=180):
        src, dst = tmp / ("%s.in" % sub), tmp / ("%s.out" % sub)
        src.write_bytes(json.dumps(payload).encode("utf-8") if payload is not None else b"")
        self.call(sub, src, dst, timeout)
        try:
            return json.loads(dst.read_bytes().decode("utf-8"))
        except Exception:
            raise bl.CliExit(bl.EXIT_PROVIDER, "сервер ответил не JSON на %s — проверь версию brain_sync_server.py" % sub)


# ---------- локальные пути ----------
class Local:
    def __init__(self, ws, skills):
        self.ws, self.skills = Path(ws), Path(skills)
        self.paths = {}

    def path(self, rel):
        if rel in self.paths:
            return self.paths[rel]
        if rel in bl.ROOT_FILES or "/" not in rel:   # CLAUDE.md и его копии конфликта — в корне рабочей папки
            return self.ws / rel
        head, _, tail = rel.partition("/")
        return bl.join_rel(self.ws / "memory" if head == "memory" else self.skills, tail)

    def scan(self, cache):
        entries, skipped = bl.scan_root_files(self.ws)
        e, s = bl.scan_tree(self.ws / "memory", "memory")
        entries.update(e)
        skipped += s
        e, s = bl.scan_tree(self.skills, "skills")
        entries.update(e)
        skipped += s
        self.paths = {rel: v[0] for rel, v in entries.items()}
        sizes = {rel: v[1] for rel, v in entries.items()}
        shas, new_cache = bl.hash_entries(entries, cache)
        return shas, sizes, skipped, new_cache


def check_windows_names():
    return bl.IS_WINDOWS or os.environ.get("BRAIN_WINDOWS_NAMES") == "1"


# ---------- план ----------
def split(d, zone):
    return {k: v for k, v in d.items() if bl.zone_of(k) == zone}


def build_plan(mode, local, remote, base):
    """mode: run | init | adopt. Ничего не трогает — только решает."""
    P = {"uploads": {}, "deletes": {}, "fetch": {}, "acks": {}, "newbase": {}, "divergent": [], "conflicts": []}
    Lc, Rc, Bc = split(local, "computer"), split(remote, "computer"), split(base, "computer")
    for rel in sorted(set(Lc) | set(Rc) | set(Bc)):
        L, R, B = Lc.get(rel), Rc.get(rel), Bc.get(rel)
        if mode == "init":
            if L is not None and L == R:
                P["newbase"][rel] = L
            elif L is not None and R is None:
                P["uploads"][rel] = None
            elif R is not None:
                P["divergent"].append(rel)
            continue
        if mode == "adopt":   # первая сверка: серверная версия побеждает, локальная → .conflict-local
            if L is not None and L == R:
                P["newbase"][rel] = L
            elif R is None:
                P["uploads"][rel] = None
            elif L is None:
                P["fetch"][rel] = "download"
            else:
                P["fetch"][rel] = "replace-local"
                P["conflicts"].append({"rel": rel, "kind": "local"})
            continue
        if L is not None:
            if L == R:
                P["newbase"][rel] = L
                continue
            if R is not None and R != B:          # сервер правили относительно базы → копия домой
                P["fetch"][rel] = "conflict-server"
                P["conflicts"].append({"rel": rel, "kind": "server"})
            P["uploads"][rel] = R
        elif B is None:
            if R is not None:                     # новый файл на сервере, дома его не было и не удаляли
                P["fetch"][rel] = "download"
        elif R is None:
            pass                                  # удалён с обеих сторон
        elif R == B:
            P["deletes"][rel] = R                 # удалили на компьютере → корзина на сервере
        else:                                     # удалили дома, а на сервере правили: копию домой, потом в корзину
            P["fetch"][rel] = "conflict-server"
            P["conflicts"].append({"rel": rel, "kind": "server"})
            P["deletes"][rel] = R
    for rel, R in split(remote, "inbox").items():
        L = local.get(rel)
        if L == R:
            P["acks"][rel] = R
        elif L is None:
            P["fetch"][rel] = "inbox"
        else:
            P["fetch"][rel] = "inbox-conflict"
    Ld, Rd, Bd = split(local, "dialogues"), split(remote, "dialogues"), split(base, "dialogues")
    for rel in sorted(set(Ld) | set(Rd) | set(Bd)):
        L, R, B = Ld.get(rel), Rd.get(rel), Bd.get(rel)
        if R is None:
            continue
        if L == R:
            P["newbase"][rel] = R
        elif L is None:
            if B == R:
                P["newbase"][rel] = B             # стёрли дома, бот не дописывал — не воскрешаем
            else:
                P["fetch"][rel] = "download"
        elif L == B:
            P["fetch"][rel] = "download"
        else:
            P["fetch"][rel] = "replace-local"     # правили дома — это зона бота
            P["conflicts"].append({"rel": rel, "kind": "local"})
    return P


def mass_delete_hit(n_del, zone_size):
    if n_del > bl.MASS_DELETE_ABS:
        return True
    return n_del >= bl.MASS_DELETE_MIN and n_del > bl.MASS_DELETE_PCT * max(zone_size, 1)


def cap(lst):
    return lst[:LIST_CAP]


def mb(n):
    return "%.1f МБ" % (n / 1024.0 / 1024.0)


# ---------- исполнение ----------
def write_local(loc, rel, data, warnings, existing_ok=False):
    """Пишет файл на компьютер. Возвращает путь или None, если имя нельзя создать здесь."""
    if check_windows_names():
        prob = bl.windows_name_problem(rel)
        if prob:
            warnings.append("пропущен %s: %s" % (rel, prob))
            return None
    target = loc.path(rel)
    if not existing_ok and rel not in loc.paths and target.exists():
        # на Mac/Windows регистр в именах не различается: Notes.md и notes.md — один файл
        warnings.append("пропущен %s: на компьютере есть файл с тем же именем в другом регистре" % rel)
        return None
    bl.atomic_write_bytes(target, data)
    return target


def unique_local(path):
    if not path.exists():
        return path
    i = 2
    while True:
        cand = path.with_name("%s-%d%s" % (path.stem, i, path.suffix))
        if not cand.exists():
            return cand
        i += 1


def engine(args, mode):
    log = bl.get_logger()
    st = bl.read_json(p_state(), {})
    tr = Transport(args.transport)
    warnings = list(tr.warnings)
    ws = bl.resolve_workspace(args.root)
    skills = Path(args.skills_dir).expanduser() if args.skills_dir else bl.default_skills_dir()
    if mode == "run":
        if not st.get("initialized"):
            raise bl.CliExit(bl.EXIT_CONFIG, "связка ещё не включена: сначала brain-sync init (новый сервер) "
                                             "или adopt (сервер по старой модели)")
        if st.get("target") != tr.ident:
            raise bl.CliExit(bl.EXIT_CONFIG, "сервер в файле доступа не тот, с которым была первая синхронизация. "
                                             "Если сервер новый — brain-sync init")
    if mode == "init" and st.get("initialized") and st.get("target") == tr.ident and not args.force:
        return {"ok": True, "mode": mode, "human": "связка уже включена — дальше работает brain-sync run"}
    base = st.get("base", {}) if mode == "run" else {}
    loc = Local(ws, skills)
    local, sizes, skipped_local, new_cache = loc.scan(st.get("cache", {}) if st.get("target") == tr.ident else {})

    with tempfile.TemporaryDirectory(prefix="brain-sync-") as tmpd:
        tmp = Path(tmpd)
        t0 = time.time()
        man = tr.json_call("manifest", {"private_report": mode == "adopt"}, tmp)
        t1 = time.time()
        skew = None
        try:
            skew = float(man.get("server_time")) - (t0 + t1) / 2.0
        except (TypeError, ValueError):
            pass
        if skew is not None and abs(skew) > bl.CLOCK_WARN_SEC:
            warnings.append("часы сервера и компьютера расходятся на %d с — включи синхронизацию времени "
                            "(на решения синка это не влияет)" % int(skew))
        remote = {}
        for rel, sha in (man.get("files") or {}).items():
            rel = bl.nfc(rel)
            if bl.is_safe_rel(rel) and not bl.excluded_reason(rel) and isinstance(sha, str):
                remote[rel] = sha

        P = build_plan(mode, local, remote, base)
        zone_size = len(split(base, "computer"))
        priv = man.get("private") or {}
        report = {
            "mode": mode, "transport": tr.shown, "workspace": str(ws),
            "upload": len(P["uploads"]), "upload_bytes": sum(sizes.get(r, 0) for r in P["uploads"]),
            "delete": len(P["deletes"]), "fetch": len(P["fetch"]), "conflicts": cap(P["conflicts"]),
            "excluded_local": cap(skipped_local), "excluded_local_count": len(skipped_local),
            "clock_skew_sec": round(skew, 1) if skew is not None else None,
        }
        if mode == "init" and P["divergent"]:
            raise bl.CliExit(bl.EXIT_CONFIRM,
                             "на сервере уже есть %d файлов памяти/скиллов, которых нет на компьютере или они другие — "
                             "это сервер по старой модели: запусти brain-sync adopt" % len(P["divergent"]),
                             divergent=cap(P["divergent"]), **report)
        mass = mode == "run" and not args.allow_mass_delete and mass_delete_hit(len(P["deletes"]), zone_size)
        report["mass_delete"] = mass
        if mass and not args.dry_run:
            raise bl.CliExit(bl.EXIT_CONFIRM,
                             "стоп: за один прогон удаляется %d файлов из %d. Если так и задумано — "
                             "brain-sync run --allow-mass-delete; если нет — верни файлы (корзина ОС или git)"
                             % (len(P["deletes"]), zone_size),
                             deletes=cap(sorted(P["deletes"])), mass_delete=True)
        if mode == "adopt":
            report["private_on_server"] = {"count": priv.get("count", 0), "bytes": priv.get("bytes", 0),
                                           "files": cap(sorted((priv.get("files") or {}).keys()))}
        preview = args.dry_run or (mode in ("init", "adopt") and not args.yes)
        if preview:
            report.update({"ok": True, "dry_run": True,
                           "uploads": cap(sorted(P["uploads"])), "deletes": cap(sorted(P["deletes"])),
                           "fetches": cap(sorted(P["fetch"])), "warnings": warnings})
            h = "предпросмотр (%s): на сервер %d файлов (%s), в корзину сервера %d, с сервера %d, конфликтов %d" % (
                mode, len(P["uploads"]), mb(report["upload_bytes"]), len(P["deletes"]), len(P["fetch"]),
                len(P["conflicts"]))
            if mode == "adopt" and priv.get("count"):
                h += "; на сервере лежат личные файлы: %d (%s) — не трогаю, забрать домой: --pull-private" % (
                    priv["count"], mb(priv.get("bytes", 0)))
            if mode in ("init", "adopt") and not args.dry_run:
                h += ". Выполнить: brain-sync %s --yes" % mode
            report["human"] = h
            return report

        # ---- fetch: забрать бот-зоны, новые файлы и копии конфликтов ----
        got, saved, conflict_saved, acks = {}, [], [], dict(P["acks"])
        private_paths = []
        private_dest = None
        if mode == "adopt" and args.pull_private and priv.get("files"):
            private_paths = sorted(priv["files"].keys())
            private_dest = Path.home() / ("brain-from-server-private-%s" % time.strftime("%Y%m%d"))
        if P["fetch"] or private_paths:
            req = {"paths": sorted(P["fetch"]), "private_paths": private_paths}
            (tmp / "fetch.in").write_bytes(json.dumps(req).encode("utf-8"))
            tr.call("fetch", tmp / "fetch.in", tmp / "fetch.out", timeout=900)
            wanted = set(P["fetch"]) | set(private_paths)
            with open(str(tmp / "fetch.out"), "rb") as f:
                try:
                    for rel, data in bl.iter_tar(f):
                        if rel not in wanted:
                            raise bl.TarSafetyError("сервер прислал лишний файл: %s" % rel[:120])
                        sha = bl.sha256_bytes(data)
                        if rel in private_paths and rel not in P["fetch"]:
                            prob = bl.windows_name_problem(rel) if check_windows_names() else None
                            if prob:
                                warnings.append("пропущен %s: %s" % (rel, prob))
                                continue
                            bl.atomic_write_bytes(bl.join_rel(private_dest, rel), data)
                            saved.append(rel)
                            continue
                        action = P["fetch"][rel]
                        if action in ("download", "inbox"):
                            if write_local(loc, rel, data, warnings):
                                got[rel] = sha
                                if action == "inbox":
                                    acks[rel] = sha
                        elif action in ("conflict-server", "inbox-conflict"):
                            crel = bl.conflict_name(rel, "server")
                            if check_windows_names() and bl.windows_name_problem(crel):
                                warnings.append("пропущен %s: имя не годится для Windows" % rel)
                                continue
                            bl.atomic_write_bytes(unique_local(loc.path(crel)), data)
                            conflict_saved.append(rel)
                            if action == "inbox-conflict":
                                acks[rel] = sha
                        elif action == "replace-local":
                            cur = loc.path(rel)
                            if cur.exists():
                                cname = bl.conflict_name(cur.name, "local")
                                os.replace(str(cur), str(unique_local(cur.with_name(cname))))
                            bl.atomic_write_bytes(cur, data)
                            got[rel] = sha
                except bl.TarSafetyError as ex:
                    raise bl.CliExit(bl.EXIT_PROVIDER, "ответ сервера отклонён: %s" % ex)
        # без сохранённой копии сервера ничего на сервере не перезаписываем и не удаляем
        for rel, action in P["fetch"].items():
            if action == "conflict-server" and rel not in conflict_saved:
                P["uploads"].pop(rel, None)
                P["deletes"].pop(rel, None)

        # ---- apply: загрузки, удаления, подтверждение inbox, heartbeat ----
        plan = {"uploads": {rel: {"sha": local[rel], "expected": exp} for rel, exp in P["uploads"].items()},
                "deletes": P["deletes"], "inbox_ack": acks, "heartbeat": True,
                "client": "brain-sync %s %s" % (bl.KIT_VERSION, bl.detect_os())}
        items = [(bl.PLAN_MEMBER, json.dumps(plan, ensure_ascii=False).encode("utf-8"))]
        items += [(rel, loc.paths[rel]) for rel in sorted(P["uploads"])]
        with open(str(tmp / "apply.in"), "wb") as f:
            bl.write_tar(f, items)
        tr.call("apply", tmp / "apply.in", tmp / "apply.out", timeout=900)
        try:
            res = json.loads((tmp / "apply.out").read_bytes().decode("utf-8"))
        except Exception:
            raise bl.CliExit(bl.EXIT_PROVIDER, "сервер ответил не JSON на apply")

    written, deleted = set(res.get("written") or []), set(res.get("deleted") or [])
    acked = set(res.get("acked") or [])
    skipped_srv = res.get("skipped") or []

    # ---- новая база ----
    nb = dict(P["newbase"])
    old = base
    for rel in P["uploads"]:
        if rel in written:
            nb[rel] = local[rel]
        elif rel in old:
            nb[rel] = old[rel]
    for rel in P["deletes"]:
        if rel not in deleted and rel in old:
            nb[rel] = old[rel]
    for rel, sha in got.items():
        if bl.zone_of(rel) in ("computer", "dialogues"):
            nb[rel] = sha
    st_new = {"version": 1, "target": tr.ident, "initialized": True,
              "mode_done": st.get("mode_done") if mode == "run" else mode,
              "base": nb, "cache": new_cache, "updated": bl.now_iso()}
    # кэш: только что записанные файлы пересчитаются по sha в следующий раз — это дёшево
    bl.atomic_write_json(p_state(), st_new)

    for w in warnings:
        log.warning(w)
    result = {
        "ok": True, "mode": mode, "transport": tr.shown,
        "uploaded": cap(sorted(written)), "uploaded_count": len(written),
        "deleted": cap(sorted(deleted)), "deleted_count": len(deleted),
        "downloaded": cap(sorted(got)), "downloaded_count": len(got),
        "inbox_acked": len(acked), "conflicts": cap(P["conflicts"]),
        "server_skipped": cap(skipped_srv), "warnings": cap(warnings),
        "clock_skew_sec": round(skew, 1) if skew is not None else None,
    }
    if saved:
        result["private_saved_to"] = str(private_dest)
        result["private_saved"] = len(saved)
    h = "синк %s: ↑%d ↓%d в корзину %d" % (time.strftime("%H:%M"), len(written), len(got), len(deleted))
    if P["conflicts"]:
        h += " · конфликтов %d (копии *.conflict-* рядом с файлами)" % len(P["conflicts"])
    if skipped_srv:
        h += " · %d файлов поменялись во время синка — доедут в следующий раз" % len(skipped_srv)
    if saved:
        h += " · личное с сервера (%d файлов) сохранено в %s, на сервере не тронуто" % (len(saved), private_dest)
    if warnings:
        h += " · предупреждений %d" % len(warnings)
    result["human"] = h
    log.info("%s %s", mode, h)
    if P["conflicts"]:
        bl.notify("brain-sync: конфликт", "%d файл(ов): копии *.conflict-* рядом с оригиналом" % len(P["conflicts"]))
    return result


# ---------- статус ----------
def record(ok, code=0, human=""):
    s = bl.read_json(p_status(), {})
    now = time.time()
    s["last_attempt"] = bl.now_iso(now)
    s["version"] = bl.KIT_VERSION
    prev_code = s.get("last_error_code")
    if ok:
        s.update({"last_success": bl.now_iso(now), "last_success_epoch": now, "consecutive_failures": 0,
                  "last_error": None, "last_error_code": None, "last_result": human})
    else:
        n = int(s.get("consecutive_failures") or 0) + 1
        s.update({"consecutive_failures": n, "last_error": human, "last_error_code": code})
        if n == 3 or (n > 3 and n % 36 == 0) or (code == bl.EXIT_CONFIRM and prev_code != bl.EXIT_CONFIRM):
            bl.notify("brain-sync не работает", human[:200])
            s["last_notified"] = bl.now_iso(now)
    try:
        bl.atomic_write_json(p_status(), s)
    except OSError:
        pass


def cmd_sync(args, mode):
    log = bl.get_logger()
    pause = p_pause()
    if pause.exists():
        info = bl.read_json(pause, {})
        bl.out({"ok": True, "paused": True, "reason": info.get("reason"),
                "human": "пауза: %s" % (info.get("reason") or "без причины")})
    if not acquire_lock():
        bl.out({"ok": True, "busy": True, "human": "синк уже идёт в другом окне — этот прогон пропущен"})
    counted = mode == "run" and not args.dry_run
    try:
        try:
            res = engine(args, mode)
        except bl.CliExit as ex:
            log.error("%s: %s", mode, ex.human)
            if counted:
                record(False, ex.code, ex.human)
            bl.fail(ex.code, ex.human, **ex.extra)
        except Exception as ex:
            human = "неожиданная ошибка (%s): %s" % (type(ex).__name__, str(ex)[:200])
            log.exception("%s", human)
            if counted:
                record(False, bl.EXIT_PROVIDER, human)
            bl.fail(bl.EXIT_PROVIDER, human)
        if not res.get("dry_run"):
            record(True, 0, res.get("human", ""))
        bl.out(res)
    finally:
        release_lock()


def ago(epoch):
    if not epoch:
        return "никогда"
    d = int(time.time() - float(epoch))
    if d < 120:
        return "%d с назад" % d
    if d < 7200:
        return "%d мин назад" % (d // 60)
    if d < 172800:
        return "%d ч назад" % (d // 3600)
    return "%d дн назад" % (d // 86400)


def cmd_status(args):
    s = bl.read_json(p_status(), {})
    st = bl.read_json(p_state(), {})
    res = {"ok": True, "config_dir": str(bl.config_dir()),
           "last_success": s.get("last_success"), "consecutive_failures": s.get("consecutive_failures", 0),
           "last_error": s.get("last_error"), "last_result": s.get("last_result"),
           "initialized": bool(st.get("initialized")), "mode_done": st.get("mode_done"),
           "tracked_files": len(st.get("base") or {})}
    pause = bl.read_json(p_pause(), None) if p_pause().exists() else None
    res["paused"] = bool(pause) or p_pause().exists()
    res["pause_reason"] = (pause or {}).get("reason")
    if p_lock().exists():
        try:
            res["lock_age_sec"] = int(time.time() - p_lock().stat().st_mtime)
        except OSError:
            pass
    try:
        acc, warns = bl.read_access()
        res["access"] = bl.access_public_view(acc)
        res["access_warnings"] = warns
    except bl.CliExit:
        res["access"] = None
    parts = ["последний успешный синк: %s" % ago(s.get("last_success_epoch"))]
    if res["consecutive_failures"]:
        parts.append("ошибок подряд %d (%s)" % (res["consecutive_failures"], (s.get("last_error") or "")[:120]))
    if res["paused"]:
        parts.append("ПАУЗА: %s — снять: brain-sync resume" % (res["pause_reason"] or "без причины"))
    if not res["initialized"]:
        parts.append("связка не включена (init / adopt)")
    res["human"] = " · ".join(parts)
    bl.out(res)


def cmd_pause(args):
    reason = (args.reason or "ручная пауза").strip()[:200]
    bl.atomic_write_json(p_pause(), {"reason": reason, "since": bl.now_iso()})
    bl.get_logger().info("pause: %s", reason)
    bl.out({"ok": True, "paused": True, "reason": reason,
            "human": "синк на паузе: %s. Вернуть: brain-sync resume, затем brain-sync run" % reason})


def cmd_resume(args):
    existed = p_pause().exists()
    try:
        p_pause().unlink()
    except OSError:
        pass
    bl.get_logger().info("resume")
    bl.out({"ok": True, "paused": False,
            "human": "пауза снята — следующий прогон по расписанию (или сразу: brain-sync run)" if existed
            else "паузы и не было"})


# ---------- CLI ----------
def add_common(p, suppress):
    d = (lambda v: {"default": argparse.SUPPRESS}) if suppress else (lambda v: {"default": v})
    p.add_argument("--root", **d(None))
    p.add_argument("--skills-dir", dest="skills_dir", **d(None))
    p.add_argument("--transport", **d("ssh"))
    p.add_argument("--dry-run", dest="dry_run", action="store_true", **d(False))
    p.add_argument("--allow-mass-delete", dest="allow_mass_delete", action="store_true", **d(False))
    p.add_argument("--yes", action="store_true", **d(False))


def main():
    p = bl.JsonArgumentParser(prog="brain-sync", description="синк компьютер ↔ сервер (kit 2.1)")
    add_common(p, False)
    sub = p.add_subparsers(dest="cmd")
    for name in ("run", "status", "resume"):
        add_common(sub.add_parser(name), True)
    sp = sub.add_parser("pause")
    add_common(sp, True)
    sp.add_argument("--reason")
    si = sub.add_parser("init")
    add_common(si, True)
    si.add_argument("--force", action="store_true")
    sa = sub.add_parser("adopt")
    add_common(sa, True)
    sa.add_argument("--pull-private", dest="pull_private", action="store_true")
    args = p.parse_args()
    for k, v in (("force", False), ("pull_private", False), ("reason", None)):
        if not hasattr(args, k):
            setattr(args, k, v)
    cmd = args.cmd or "run"
    if cmd == "status":
        cmd_status(args)
    elif cmd == "pause":
        cmd_pause(args)
    elif cmd == "resume":
        cmd_resume(args)
    else:
        cmd_sync(args, cmd)


if __name__ == "__main__":
    bl.run_cli(main)
