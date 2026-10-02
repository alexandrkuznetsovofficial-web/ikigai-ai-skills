#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты brain-sync (kit 2.1): python3 -m unittest brain-link/tests/test_sync.py -v
Только stdlib. «Сервер» — локальная папка (--transport local:<папка>), brain_sync_server.py запускается подпроцессом,
ssh не нужен. Каждый тест — своя временная папка: рабочая папка, скиллы, сервер, ~/.config/brain.
"""
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
import unittest
from pathlib import Path, PureWindowsPath

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
SCRIPTS = KIT / "scripts"
SYNC = SCRIPTS / "brain_sync.py"
SERVER = KIT / "server" / "brain_sync_server.py"
CONVENTIONS = KIT.parent / "KIT_CONVENTIONS.md"

sys.path.insert(0, str(SCRIPTS))
import brainlib as bl  # noqa: E402
import brain_sync  # noqa: E402


def load_server_module():
    spec = importlib.util.spec_from_file_location("brain_sync_server", str(SERVER))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Rig:
    """Одна «установка»: компьютер (ws + skills + cfg + home) и сервер (srv)."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="brain-sync-test-"))
        self.home = self.tmp / "home"
        self.ws = self.tmp / "ws"
        self.skills = self.home / ".claude" / "skills"
        self.srv = self.tmp / "srv"
        self.cfg = self.home / ".config" / "brain"
        for d in (self.ws / "memory", self.skills, self.srv, self.home):
            d.mkdir(parents=True, exist_ok=True)

    def close(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def env(self, extra=None):
        e = dict(os.environ)
        e.update({"BRAIN_CONFIG_DIR": str(self.cfg), "BRAIN_NO_NOTIFY": "1", "HOME": str(self.home),
                  "USERPROFILE": str(self.home)})
        e.pop("SSH_ORIGINAL_COMMAND", None)
        e.pop("BRAIN_TEST_CLOCK_SHIFT", None)
        e.pop("BRAIN_WINDOWS_NAMES", None)
        if extra:
            e.update(extra)
        return e

    def sync(self, *args, extra_env=None, transport=None):
        cmd = [sys.executable, str(SYNC)] + list(args) + [
            "--root", str(self.ws), "--skills-dir", str(self.skills),
            "--transport", transport or ("local:%s" % self.srv)]
        r = subprocess.run(cmd, capture_output=True, timeout=120, env=self.env(extra_env))
        out = r.stdout.decode("utf-8").strip()
        lines = out.splitlines()
        assert len(lines) == 1, "ожидался один JSON, получено: %r / stderr %r" % (out, r.stderr[-500:])
        return r.returncode, json.loads(lines[0])

    def ok(self, *args, **kw):
        rc, res = self.sync(*args, **kw)
        assert rc == 0, "rc=%s %s" % (rc, res)
        return res

    # компьютер
    def lw(self, rel, text):
        p = self.lpath(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def lpath(self, rel):
        if rel == "CLAUDE.md":
            return self.ws / rel
        head, _, tail = rel.partition("/")
        return (self.ws / "memory" if head == "memory" else self.skills) / tail

    def lr(self, rel):
        return self.lpath(rel).read_text(encoding="utf-8")

    # сервер
    def spath(self, rel):
        if rel == "CLAUDE.md":
            return self.srv / rel
        head, _, tail = rel.partition("/")
        return (self.srv / "memory" if head == "memory" else self.srv / ".claude" / "skills") / tail

    def sw(self, rel, text):
        p = self.spath(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def sr(self, rel):
        return self.spath(rel).read_text(encoding="utf-8")

    def conflicts(self, folder, kind):
        return sorted(p for p in Path(folder).iterdir() if (".conflict-%s-" % kind) in p.name)

    def base_setup(self):
        self.lw("CLAUDE.md", "# правила\n")
        self.lw("memory/MEMORY.md", "индекс\n")
        self.lw("memory/tasks/task_2026-10-02_a.md", "задача\n")
        self.lw("skills/os/SKILL.md", "---\nname: os\n---\n")
        return self.ok("init", "--yes")


class SyncCase(unittest.TestCase):
    def setUp(self):
        self.r = Rig()

    def tearDown(self):
        self.r.close()


# ---------------------------------------------------------------- основные сценарии
class TestBasics(SyncCase):
    def test_first_sync_init(self):
        r = self.r
        r.lw("CLAUDE.md", "# правила\n")
        r.lw("memory/MEMORY.md", "индекс\n")
        r.lw("skills/os/SKILL.md", "скилл\n")
        (r.ws / "notes_root.md").write_text("в корне — не синкаем\n", encoding="utf-8")
        prev = r.ok("init")                              # без --yes — только отчёт
        self.assertTrue(prev["dry_run"])
        self.assertEqual(prev["upload"], 3)
        self.assertFalse(r.spath("memory/MEMORY.md").exists())
        res = r.ok("init", "--yes")
        self.assertEqual(res["uploaded_count"], 3)
        self.assertEqual(r.sr("CLAUDE.md"), "# правила\n")
        self.assertEqual(r.sr("memory/MEMORY.md"), "индекс\n")
        self.assertEqual(r.sr("skills/os/SKILL.md"), "скилл\n")
        self.assertFalse((r.srv / "notes_root.md").exists(), "из корня рабочей папки едет только CLAUDE.md")
        self.assertTrue((r.srv / ".brain-sync" / "heartbeat").exists())
        if os.name == "posix":
            self.assertEqual(oct(r.spath("memory/MEMORY.md").stat().st_mode & 0o777), "0o640")
        st = json.loads((r.cfg / "sync_state.json").read_text())
        self.assertTrue(st["initialized"])
        self.assertIn("CLAUDE.md", st["base"])

    def test_run_before_init_refuses(self):
        self.r.lw("memory/MEMORY.md", "x")
        rc, res = self.r.sync("run")
        self.assertEqual(rc, 1)
        self.assertIn("init", res["human"])

    def test_edit_propagates_and_repeat_is_noop(self):
        r = self.r
        r.base_setup()
        r.lw("memory/MEMORY.md", "индекс v2\n")
        r.lw("memory/new.md", "новый\n")
        res = r.ok("run")
        self.assertEqual(res["uploaded_count"], 2)
        self.assertEqual(r.sr("memory/MEMORY.md"), "индекс v2\n")
        self.assertEqual(r.sr("memory/new.md"), "новый\n")
        again = r.ok("run")
        self.assertEqual((again["uploaded_count"], again["downloaded_count"], again["deleted_count"]), (0, 0, 0))
        self.assertEqual(again["conflicts"], [])

    def test_dry_run_changes_nothing(self):
        r = self.r
        r.base_setup()
        r.lw("memory/MEMORY.md", "v2\n")
        res = r.ok("run", "--dry-run")
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["upload"], 1)
        self.assertEqual(r.sr("memory/MEMORY.md"), "индекс\n")

    def test_inbox_pulled_and_moved_to_synced(self):
        r = self.r
        r.base_setup()
        name = "2026-10-02_120000_tg.md"
        r.sw("memory/inbox/" + name, "запомни: позвонить\n")
        res = r.ok("run")
        self.assertEqual(res["inbox_acked"], 1)
        self.assertEqual(r.lr("memory/inbox/" + name), "запомни: позвонить\n")
        self.assertFalse(r.spath("memory/inbox/" + name).exists())
        moved = r.srv / "memory" / "inbox" / ".synced" / time.strftime("%Y-%m") / name
        self.assertTrue(moved.exists())
        # Claude разобрал inbox дома — на сервере ничего не воскресает и не ломается
        r.lpath("memory/inbox/" + name).unlink()
        again = r.ok("run")
        self.assertEqual(again["downloaded_count"], 0)
        self.assertFalse(r.lpath("memory/inbox/" + name).exists())

    def test_new_file_created_on_server_comes_home(self):
        r = self.r
        r.base_setup()
        r.sw("memory/from_server.md", "сервер\n")
        res = r.ok("run")
        self.assertIn("memory/from_server.md", res["downloaded"])
        self.assertEqual(r.lr("memory/from_server.md"), "сервер\n")
        self.assertEqual(r.ok("run")["downloaded_count"], 0)


# ---------------------------------------------------------------- конфликты
class TestConflicts(SyncCase):
    def test_server_edit_saved_as_conflict_server_and_overwritten(self):
        r = self.r
        r.base_setup()
        r.sw("memory/MEMORY.md", "правка на сервере\n")
        r.lw("memory/MEMORY.md", "правка дома\n")
        res = r.ok("run")
        self.assertEqual(len(res["conflicts"]), 1)
        self.assertEqual(r.sr("memory/MEMORY.md"), "правка дома\n")
        copies = r.conflicts(r.ws / "memory", "server")
        self.assertEqual(len(copies), 1)
        self.assertRegex(copies[0].name, r"^MEMORY\.conflict-server-\d{8}-\d{4}\.md$")
        self.assertEqual(copies[0].read_text(encoding="utf-8"), "правка на сервере\n")
        # копия конфликта сама не синкается и второй раз не появляется
        again = r.ok("run")
        self.assertEqual((again["uploaded_count"], len(again["conflicts"])), (0, 0))
        self.assertFalse(r.spath("memory/" + copies[0].name).exists())

    def test_server_edit_only_also_restored(self):
        r = self.r
        r.base_setup()
        r.sw("memory/tasks/task_2026-10-02_a.md", "кто-то правил на сервере\n")
        r.ok("run")
        self.assertEqual(r.sr("memory/tasks/task_2026-10-02_a.md"), "задача\n")
        self.assertEqual(len(r.conflicts(r.ws / "memory" / "tasks", "server")), 1)

    def test_claude_md_conflict_same_rules(self):
        r = self.r
        r.base_setup()
        r.sw("CLAUDE.md", "серверная правка правил\n")
        r.lw("CLAUDE.md", "# правила v2\n")
        r.ok("run")
        self.assertEqual(r.sr("CLAUDE.md"), "# правила v2\n")
        copies = r.conflicts(r.ws, "server")
        self.assertEqual([p.name[:25] for p in copies], ["CLAUDE.conflict-server-20"])
        self.assertEqual(copies[0].read_text(encoding="utf-8"), "серверная правка правил\n")

    def test_dialogues_local_edit_becomes_conflict_local(self):
        r = self.r
        r.base_setup()
        r.sw("memory/dialogues/2026-10-02.md", "бот: привет\n")
        r.ok("run")
        self.assertEqual(r.lr("memory/dialogues/2026-10-02.md"), "бот: привет\n")
        r.lw("memory/dialogues/2026-10-02.md", "правлю журнал дома\n")
        r.sw("memory/dialogues/2026-10-02.md", "бот: привет\nбот: ещё\n")
        res = r.ok("run")
        self.assertEqual(r.lr("memory/dialogues/2026-10-02.md"), "бот: привет\nбот: ещё\n")
        loc = r.conflicts(r.ws / "memory" / "dialogues", "local")
        self.assertEqual(len(loc), 1)
        self.assertEqual(loc[0].read_text(encoding="utf-8"), "правлю журнал дома\n")
        self.assertEqual(r.sr("memory/dialogues/2026-10-02.md"), "бот: привет\nбот: ещё\n", "зону бота не трогаем")
        self.assertEqual(len(res["conflicts"]), 1)

    def test_dialogues_append_on_server_just_downloads(self):
        r = self.r
        r.base_setup()
        r.sw("memory/dialogues/d.md", "1\n")
        r.ok("run")
        r.sw("memory/dialogues/d.md", "1\n2\n")
        res = r.ok("run")
        self.assertEqual(r.lr("memory/dialogues/d.md"), "1\n2\n")
        self.assertEqual(res["conflicts"], [])


# ---------------------------------------------------------------- удаления
class TestDeletes(SyncCase):
    def test_local_delete_goes_to_server_trash(self):
        r = self.r
        r.base_setup()
        r.lpath("memory/tasks/task_2026-10-02_a.md").unlink()
        res = r.ok("run")
        self.assertEqual(res["deleted"], ["memory/tasks/task_2026-10-02_a.md"])
        self.assertFalse(r.spath("memory/tasks/task_2026-10-02_a.md").exists())
        trashed = r.srv / ".brain-trash" / time.strftime("%Y-%m-%d") / "memory" / "tasks" / "task_2026-10-02_a.md"
        self.assertEqual(trashed.read_text(encoding="utf-8"), "задача\n")
        self.assertTrue((r.srv / "memory").is_dir(), "корень зоны не удаляется вместе с пустыми папками")
        again = r.ok("run")
        self.assertEqual(again["downloaded_count"], 0, "удалённое не воскресает")
        self.assertFalse(r.lpath("memory/tasks/task_2026-10-02_a.md").exists())

    def test_delete_at_home_but_edited_on_server_keeps_copy(self):
        r = self.r
        r.base_setup()
        r.lpath("memory/MEMORY.md").unlink()
        r.sw("memory/MEMORY.md", "сервер успел дописать\n")
        r.ok("run")
        copies = r.conflicts(r.ws / "memory", "server")
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_text(encoding="utf-8"), "сервер успел дописать\n")
        self.assertFalse(r.spath("memory/MEMORY.md").exists())

    def test_mass_delete_stops_until_flag(self):
        r = self.r
        for i in range(40):
            r.lw("memory/notes/n%02d.md" % i, "n%d\n" % i)
        r.ok("init", "--yes")
        for i in range(26):
            r.lpath("memory/notes/n%02d.md" % i).unlink()
        rc, res = r.sync("run")
        self.assertEqual(rc, 3)
        self.assertTrue(res.get("mass_delete"))
        self.assertTrue(r.spath("memory/notes/n00.md").exists(), "до флага на сервере ничего не удалено")
        status = r.ok("status")
        self.assertEqual(status["consecutive_failures"], 1)
        res = r.ok("run", "--allow-mass-delete")
        self.assertEqual(res["deleted_count"], 26)
        self.assertFalse(r.spath("memory/notes/n00.md").exists())
        self.assertEqual(r.ok("status")["consecutive_failures"], 0)

    def test_mass_delete_by_percent(self):
        r = self.r
        for i in range(20):
            r.lw("memory/n%02d.md" % i, "x%d" % i)
        r.ok("init", "--yes")
        for i in range(3):                 # 3 из 20 = 15 % > 10 %
            r.lpath("memory/n%02d.md" % i).unlink()
        rc, _ = r.sync("run")
        self.assertEqual(rc, 3)
        # одно удаление в маленькой папке — не стоп
        r2 = Rig()
        try:
            for i in range(5):
                r2.lw("memory/m%d.md" % i, "y%d" % i)
            r2.ok("init", "--yes")
            r2.lpath("memory/m0.md").unlink()
            self.assertEqual(r2.ok("run")["deleted_count"], 1)
        finally:
            r2.close()


# ---------------------------------------------------------------- исключения, имена, часы
class TestExcludesAndNames(SyncCase):
    def test_excludes_both_directions(self):
        r = self.r
        r.lw("memory/MEMORY.md", "ok\n")
        r.lw("memory/personal/health.md", "личное\n")
        r.lw("memory/private/x.md", "x\n")
        r.lw("memory/secret_stuff/x.md", "x\n")
        r.lw("memory/sessions/s.md", "x\n")
        r.lw("memory/.secrets/token", "x\n")
        r.lw("memory/.env", "TOKEN=1\n")
        r.lw("memory/bot.env", "TOKEN=1\n")
        r.lw("memory/tg.session", "x\n")
        r.lw("memory/a.md.bak.20261002", "x\n")
        r.lw("memory/a.conflict-server-20261002-1200.md", "x\n")
        r.lw("memory/.DS_Store", "x\n")
        r.lw("memory/node_modules/m.js", "x\n")
        r.lw("skills/os/__pycache__/x.pyc", "x\n")
        r.lw("skills/os/.git/HEAD", "x\n")
        big = r.lpath("memory/big.bin")
        with open(str(big), "wb") as f:
            f.truncate(bl.MAX_FILE_BYTES + 1)
        res = r.ok("init", "--yes")
        self.assertEqual(res["uploaded"], ["memory/MEMORY.md"])
        for rel in ("memory/personal/health.md", "memory/.env", "memory/tg.session", "memory/big.bin",
                    "memory/.secrets/token", "memory/bot.env", "skills/os/.git/HEAD"):
            self.assertFalse(r.spath(rel).exists(), rel)
        # обратная сторона: на сервере личное/секреты в зонах бота и компьютера — домой не едут
        r.sw("memory/personal/server_only.md", "личное с сервера\n")
        r.sw("memory/inbox/.env", "SECRET=1\n")
        r.sw("memory/inbox/acc.session", "x\n")
        r.sw("memory/dialogues/sessions/x.md", "x\n")
        r.sw("memory/inbox/2026-10-02_130000_tg.md", "норм\n")
        with open(str(r.spath("memory/inbox/huge.md")), "wb") as f:
            f.truncate(bl.MAX_FILE_BYTES + 5)
        res = r.ok("run")
        self.assertEqual(res["downloaded"], ["memory/inbox/2026-10-02_130000_tg.md"])
        self.assertFalse(r.lpath("memory/personal/server_only.md").exists())
        self.assertFalse(r.lpath("memory/inbox/.env").exists())
        self.assertFalse(r.lpath("memory/inbox/huge.md").exists())
        self.assertTrue(r.spath("memory/personal/server_only.md").exists(), "чужое на сервере не трогаем")

    def test_excludes_single_source_of_truth(self):
        srv = load_server_module()
        for name in ("EXCLUDES", "MAX_FILE_BYTES", "PRIVATE_DIRS", "ROOT_FILES", "ZONE_PREFIXES", "INBOX_PREFIX",
                     "DIALOGUES_PREFIX", "SYNCED_DIRNAME", "TMP_SUFFIX", "PLAN_MEMBER"):
            self.assertEqual(getattr(srv, name), getattr(bl, name), "brain_sync_server.%s ≠ brainlib" % name)
        if CONVENTIONS.exists():
            text = CONVENTIONS.read_text(encoding="utf-8")
            m = re.search(r"\*\*Исключено в обе стороны:\*\*(.*?)любой файл больше 20", text, re.S)
            self.assertIsNotNone(m, "в KIT_CONVENTIONS §8 нет строки «Исключено в обе стороны»")
            tokens = set()
            for chunk in re.findall(r"`([^`]+)`", m.group(1)):
                tokens.update(chunk.split())
            self.assertEqual(tokens, set(bl.EXCLUDES), "EXCLUDES расходится с KIT_CONVENTIONS §8")

    def test_nfc_nfd_names(self):
        r = self.r
        nfd = unicodedata.normalize("NFD", "заметка_йод.md")
        nfc = unicodedata.normalize("NFC", "заметка_йод.md")
        self.assertNotEqual(nfd, nfc)
        p = r.ws / "memory" / nfd
        p.write_text("юникод\n", encoding="utf-8")
        res = r.ok("init", "--yes")
        self.assertEqual(res["uploaded"], ["memory/" + nfc])
        names = os.listdir(str(r.srv / "memory"))
        self.assertIn(nfc, names, "на сервере имя в NFC")
        again = r.ok("run")
        self.assertEqual((again["uploaded_count"], again["downloaded_count"], again["deleted_count"]), (0, 0, 0))

    def test_clock_shift_2h21m_does_not_matter(self):
        r = self.r
        r.base_setup()
        shift = 2 * 3600 + 21 * 60
        env = {"BRAIN_TEST_CLOCK_SHIFT": str(shift)}
        res = r.ok("run", extra_env=env)
        self.assertTrue(any("часы" in w for w in res["warnings"]), res["warnings"])
        self.assertAlmostEqual(res["clock_skew_sec"], shift, delta=30)
        self.assertEqual(res["uploaded_count"], 0)
        # время файлов врёт в обе стороны — решения всё равно по содержимому
        lp = r.lpath("memory/MEMORY.md")
        sp = r.spath("memory/MEMORY.md")
        past = time.time() - shift
        os.utime(str(lp), (past, past))
        os.utime(str(sp), (time.time() + shift, time.time() + shift))
        res = r.ok("run", extra_env=env)
        self.assertEqual((res["uploaded_count"], len(res["conflicts"])), (0, 0), "одно время без правки — не изменение")
        lp.write_text("индекс в прошлом\n", encoding="utf-8")
        os.utime(str(lp), (past - 100, past - 100))     # правка «старше» серверной версии
        res = r.ok("run", extra_env=env)
        self.assertEqual(res["uploaded"], ["memory/MEMORY.md"])
        self.assertEqual(r.sr("memory/MEMORY.md"), "индекс в прошлом\n")

    def test_windows_names_skipped(self):
        r = self.r
        r.base_setup()
        r.sw("memory/inbox/2026-10-02_140000_tg.md", "норм\n")
        r.sw("memory/inbox/a:b.md", "двоеточие\n")
        r.sw("memory/inbox/aux.md", "зарезервировано\n")
        res = r.ok("run", extra_env={"BRAIN_WINDOWS_NAMES": "1"})
        self.assertEqual(res["downloaded"], ["memory/inbox/2026-10-02_140000_tg.md"])
        self.assertEqual(len([w for w in res["warnings"] if "пропущен" in w]), 2)
        self.assertTrue(r.spath("memory/inbox/a:b.md").exists(), "непринятое не подтверждаем — остаётся на сервере")
        self.assertEqual(res["inbox_acked"], 1)


class TestWindowsPaths(unittest.TestCase):
    def test_problems(self):
        self.assertIsNone(bl.windows_name_problem("memory/заметки/план 2026.md"))
        self.assertIsNotNone(bl.windows_name_problem("memory/a:b.md"))
        self.assertIsNotNone(bl.windows_name_problem("memory/what?.md"))
        self.assertIsNotNone(bl.windows_name_problem("memory/CON"))
        self.assertIsNotNone(bl.windows_name_problem("memory/com1.txt"))
        self.assertIsNotNone(bl.windows_name_problem("memory/dir./x.md"))
        self.assertIsNotNone(bl.windows_name_problem("memory/trailing /x.md"))
        self.assertIsNone(bl.windows_name_problem("memory/console.md"))

    def test_join_rel_windows(self):
        root = PureWindowsPath(r"C:\Users\Иван Петров\brain")
        got = bl.join_rel(root / "memory", "a b/заметка.md")
        self.assertEqual(got, PureWindowsPath(r"C:\Users\Иван Петров\brain\memory\a b\заметка.md"))
        self.assertEqual(str(bl.join_rel(PureWindowsPath(r"C:\x"), "CLAUDE.md")), r"C:\x\CLAUDE.md")

    def test_safe_rel(self):
        for bad in ("../x.md", "memory/../../etc/passwd", "/etc/passwd", "memory\\..\\x", "C:/x.md", "other/x.md",
                    "memory", "memory//x", "memory/./x", ""):
            self.assertFalse(bl.is_safe_rel(bad), bad)
        for good in ("CLAUDE.md", "memory/a.md", "skills/os/SKILL.md", "memory/inbox/2026-10-02_120000_tg.md"):
            self.assertTrue(bl.is_safe_rel(good), good)

    def test_conflict_name(self):
        t = time.mktime((2026, 10, 2, 14, 5, 0, 0, 0, -1))
        self.assertEqual(bl.conflict_name("memory/notes.md", "server", t), "memory/notes.conflict-server-20261002-1405.md")
        self.assertEqual(bl.conflict_name("CLAUDE.md", "server", t), "CLAUDE.conflict-server-20261002-1405.md")
        self.assertEqual(bl.conflict_name("memory/README", "local", t), "memory/README.conflict-local-20261002-1405")
        self.assertTrue(bl.is_excluded_file("notes.conflict-server-20261002-1405.md"))

    def test_ssh_command(self):
        access = {"SERVER_IP": "203.0.113.10", "SERVER_USER": "brain", "SERVER_PORT": "2222"}
        cmd = bl.ssh_command(access, ["manifest"], key_path=PureWindowsPath(r"C:\Users\Иван Петров\.ssh\brain_sync_ed25519"),
                             known_hosts=r"C:\Users\Иван Петров\.config\brain\known_hosts", ssh_bin="ssh.exe")
        joined = " ".join(cmd)
        for opt in ("BatchMode=yes", "IdentitiesOnly=yes", "ConnectTimeout=15", "StrictHostKeyChecking=yes"):
            self.assertIn(opt, cmd)
        self.assertIn('UserKnownHostsFile="C:\\Users\\Иван Петров\\.config\\brain\\known_hosts"', cmd)
        self.assertEqual(cmd[-2:], ["brain@203.0.113.10", "manifest"])
        self.assertIn("-p 2222", joined)
        self.assertNotIn("StrictHostKeyChecking=no", joined)


class TestAccessFile(unittest.TestCase):
    def test_new_and_legacy_keys(self):
        d = Path(tempfile.mkdtemp())
        try:
            p = d / "server_access"
            p.write_text("# доступ\nIP=203.0.113.7\nLOGIN=root\nPORT=22\nCLAUDE_TOKEN=sk-ant-oat01-xxxxxxxx\n"
                         "BOT_TOKEN=123456:ABCDEFGHIJ\nUSER_ID=42\n", encoding="utf-8")
            acc, warns = bl.read_access(p)
            self.assertEqual(acc["SERVER_IP"], "203.0.113.7")
            self.assertEqual(acc["SERVER_USER"], "root")
            self.assertEqual(len(warns), 4)
            view = bl.access_public_view(acc)
            self.assertEqual(view["SERVER_IP"], "203.x.x.x")
            self.assertNotIn("ABCDEFGHIJ", json.dumps(view, ensure_ascii=False))
            p.write_text("SERVER_IP=203.0.113.8\nSERVER_USER=brain\n", encoding="utf-8")
            acc, warns = bl.read_access(p)
            self.assertEqual((acc["SERVER_IP"], acc["SERVER_PORT"], warns), ("203.0.113.8", "22", []))
        finally:
            shutil.rmtree(str(d), ignore_errors=True)


# ---------------------------------------------------------------- пауза, lock, статус
class TestControl(SyncCase):
    def test_pause_and_resume(self):
        r = self.r
        r.base_setup()
        res = r.ok("pause", "--reason", "memory-upgrade")
        self.assertTrue(res["paused"])
        r.lw("memory/MEMORY.md", "во время паузы\n")
        res = r.ok("run")
        self.assertEqual(res["human"], "пауза: memory-upgrade")
        self.assertEqual(r.sr("memory/MEMORY.md"), "индекс\n")
        self.assertTrue(r.ok("status")["paused"])
        r.ok("resume")
        r.ok("run")
        self.assertEqual(r.sr("memory/MEMORY.md"), "во время паузы\n")

    def test_stale_lock_removed_fresh_lock_respected(self):
        r = self.r
        r.base_setup()
        lock = r.cfg / "sync.lock"
        lock.write_text("{}")
        res = r.ok("run")
        self.assertTrue(res.get("busy"), "свежий lock — прогон пропущен")
        old = time.time() - 11 * 60
        os.utime(str(lock), (old, old))
        r.lw("memory/MEMORY.md", "после lock\n")
        res = r.ok("run")
        self.assertFalse(res.get("busy"))
        self.assertEqual(r.sr("memory/MEMORY.md"), "после lock\n")
        self.assertFalse(lock.exists())

    def test_failures_counted_and_notified(self):
        r = self.r
        r.base_setup()
        other = r.tmp / "other_srv"
        other.mkdir()
        for _ in range(3):
            rc, _ = r.sync("run", transport="local:%s" % other)
            self.assertEqual(rc, 1)
        st = json.loads((r.cfg / "sync_status.json").read_text(encoding="utf-8"))
        self.assertEqual(st["consecutive_failures"], 3)
        self.assertIn("last_notified", st)
        r.ok("run")
        st = json.loads((r.cfg / "sync_status.json").read_text(encoding="utf-8"))
        self.assertEqual(st["consecutive_failures"], 0)
        self.assertTrue((r.cfg / "logs" / "sync.log").exists())


# ---------------------------------------------------------------- adopt (ветка B)
class TestAdopt(SyncCase):
    def old_model_server(self):
        r = self.r
        r.sw("CLAUDE.md", "правила с сервера\n")
        r.sw("memory/MEMORY.md", "индекс с сервера\n")
        r.sw("memory/server_only.md", "только на сервере\n")
        r.sw("memory/personal/health.md", "личное\n")
        r.sw("memory/sessions/2026-09-01.md", "сессия\n")
        r.sw("skills/os/SKILL.md", "скилл сервера\n")
        r.lw("CLAUDE.md", "правила с сервера\n")          # совпадает — не конфликт
        r.lw("memory/MEMORY.md", "индекс дома (старое зеркало)\n")
        r.lw("memory/local_only.md", "только дома\n")

    def test_init_on_old_server_refuses(self):
        self.old_model_server()
        rc, res = self.r.sync("init", "--yes")
        self.assertEqual(rc, 3)
        self.assertIn("adopt", res["human"])

    def test_adopt_preview_then_apply(self):
        r = self.r
        self.old_model_server()
        prev = r.ok("adopt")
        self.assertTrue(prev["dry_run"])
        self.assertEqual(prev["private_on_server"]["count"], 2)
        self.assertEqual(r.lr("memory/MEMORY.md"), "индекс дома (старое зеркало)\n")
        res = r.ok("adopt", "--yes")
        self.assertEqual(r.lr("memory/MEMORY.md"), "индекс с сервера\n", "в первой сверке побеждает сервер")
        loc = r.conflicts(r.ws / "memory", "local")
        self.assertEqual(len(loc), 1)
        self.assertEqual(loc[0].read_text(encoding="utf-8"), "индекс дома (старое зеркало)\n")
        self.assertEqual(r.lr("memory/server_only.md"), "только на сервере\n")
        self.assertEqual(r.lr("skills/os/SKILL.md"), "скилл сервера\n")
        self.assertEqual(r.sr("memory/local_only.md"), "только дома\n")
        self.assertFalse(r.lpath("memory/personal/health.md").exists(), "личное без флага не забираем")
        self.assertTrue(r.spath("memory/personal/health.md").exists())
        self.assertNotIn("private_saved_to", res)
        # дальше обычный режим: компьютер — хозяин
        r.lw("memory/MEMORY.md", "индекс v3\n")
        r.ok("run")
        self.assertEqual(r.sr("memory/MEMORY.md"), "индекс v3\n")

    def test_adopt_pull_private(self):
        r = self.r
        self.old_model_server()
        res = r.ok("adopt", "--yes", "--pull-private")
        dest = Path(res["private_saved_to"])
        self.assertTrue(str(dest).startswith(str(r.home)))
        self.assertEqual((dest / "memory" / "personal" / "health.md").read_text(encoding="utf-8"), "личное\n")
        self.assertTrue((dest / "memory" / "sessions" / "2026-09-01.md").exists())
        self.assertTrue(r.spath("memory/personal/health.md").exists(), "на сервере личное не удаляем")
        self.assertFalse(r.lpath("memory/personal/health.md").exists(), "в рабочую папку личное с сервера не кладём")


# ---------------------------------------------------------------- безопасность сервера и tar
class TestServerSecurity(SyncCase):
    def server(self, cmd, stdin=b"", ssh_original=None):
        env = dict(os.environ, BRAIN_ROOT=str(self.r.srv))
        argv = [sys.executable, str(SERVER)]
        if ssh_original is not None:
            env["SSH_ORIGINAL_COMMAND"] = ssh_original
        else:
            env.pop("SSH_ORIGINAL_COMMAND", None)
            argv.append(cmd)
        return subprocess.run(argv, input=stdin, capture_output=True, env=env, timeout=60)

    def crafted(self, members, plan=None):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            pl = json.dumps(plan or {"uploads": {}}).encode()
            ti = tarfile.TarInfo(bl.PLAN_MEMBER)
            ti.size = len(pl)
            tf.addfile(ti, io.BytesIO(pl))
            for m in members:
                tf.addfile(*m) if isinstance(m, tuple) else tf.addfile(m)
        return buf.getvalue()

    def file_member(self, name, data=b"evil"):
        ti = tarfile.TarInfo(name)
        ti.size = len(data)
        return (ti, io.BytesIO(data))

    def test_whitelist(self):
        self.assertEqual(self.server(None, ssh_original="bash -i").returncode, 1)
        self.assertEqual(self.server(None, ssh_original="manifest; rm -rf /").returncode, 1)
        r = self.server(None, ssh_original="version")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["version"], "2.1")
        r = self.server(None, ssh_original="heartbeat")
        self.assertEqual(r.returncode, 0)

    def test_dotdot_rejected(self):
        for name in ("../evil.md", "memory/../../evil.md", "/tmp/evil.md", "memory/../evil.md"):
            data = self.crafted([self.file_member(name)], {"uploads": {name: {"sha": "x", "expected": None}}})
            r = self.server("apply", data)
            self.assertNotEqual(r.returncode, 0, name)
        self.assertFalse((self.r.tmp / "evil.md").exists())
        self.assertFalse((self.r.srv / "evil.md").exists())

    def test_symlink_member_rejected(self):
        ti = tarfile.TarInfo("memory/link.md")
        ti.type = tarfile.SYMTYPE
        ti.linkname = "/etc/passwd"
        data = self.crafted([ti], {"uploads": {"memory/link.md": {"sha": "x", "expected": None}}})
        self.assertNotEqual(self.server("apply", data).returncode, 0)
        self.assertFalse(os.path.lexists(str(self.r.srv / "memory" / "link.md")))

    def test_upload_outside_computer_zone_rejected(self):
        body = b"fake note"
        sha = bl.sha256_bytes(body)
        rel = "memory/inbox/2026-10-02_000000_tg.md"
        data = self.crafted([self.file_member(rel, body)], {"uploads": {rel: {"sha": sha, "expected": None}}})
        self.assertNotEqual(self.server("apply", data).returncode, 0)
        rel = "memory/personal/x.md"
        data = self.crafted([self.file_member(rel, body)], {"uploads": {rel: {"sha": sha, "expected": None}}})
        self.assertNotEqual(self.server("apply", data).returncode, 0)
        self.assertFalse((self.r.srv / "memory" / "personal").exists())

    def test_write_through_symlinked_dir_rejected(self):
        outside = self.r.tmp / "outside"
        outside.mkdir()
        (self.r.srv / "memory").mkdir(parents=True, exist_ok=True)
        os.symlink(str(outside), str(self.r.srv / "memory" / "tasks"))
        body = b"x"
        rel = "memory/tasks/a.md"
        data = self.crafted([self.file_member(rel, body)],
                            {"uploads": {rel: {"sha": bl.sha256_bytes(body), "expected": None}}})
        self.assertNotEqual(self.server("apply", data).returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    def test_fetch_refuses_excluded(self):
        (self.r.srv / "memory" / "personal").mkdir(parents=True)
        (self.r.srv / "memory" / "personal" / "x.md").write_text("x")
        r = self.server("fetch", json.dumps({"paths": ["memory/personal/x.md"]}).encode())
        self.assertNotEqual(r.returncode, 0)
        r = self.server("fetch", json.dumps({"paths": ["../../etc/passwd"]}).encode())
        self.assertNotEqual(r.returncode, 0)

    def test_client_tar_reader_rejects(self):
        for name in ("../x.md", "/abs.md", "memory/../../x.md"):
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tf:
                tf.addfile(*self.file_member(name))
            buf.seek(0)
            with self.assertRaises(bl.TarSafetyError):
                list(bl.iter_tar(buf))
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            ti = tarfile.TarInfo("memory/big.md")
            ti.size = 30
            tf.addfile(ti, io.BytesIO(b"x" * 30))
        buf.seek(0)
        with self.assertRaises(bl.TarSafetyError):
            list(bl.iter_tar(buf, max_size=10))

    def test_trash_and_synced_cleanup_after_30_days(self):
        r = self.r
        r.base_setup()
        old_trash = r.srv / ".brain-trash" / "2020-01-01" / "memory"
        old_trash.mkdir(parents=True)
        (old_trash / "x.md").write_text("x")
        synced = r.srv / "memory" / "inbox" / ".synced" / "2020-01"
        synced.mkdir(parents=True)
        f = synced / "old.md"
        f.write_text("x")
        t = time.time() - 31 * 86400
        os.utime(str(f), (t, t))
        r.ok("run")
        self.assertFalse((r.srv / ".brain-trash" / "2020-01-01").exists())
        self.assertFalse(f.exists())


class TestPlanUnit(unittest.TestCase):
    """build_plan — чистая функция: решения только по sha."""

    def test_matrix(self):
        P = brain_sync.build_plan("run",
                                  local={"memory/a": "A1", "memory/b": "B0", "memory/n": "N"},
                                  remote={"memory/a": "A0", "memory/b": "B2", "memory/c": "C0", "memory/s": "S"},
                                  base={"memory/a": "A0", "memory/b": "B0", "memory/c": "C0"})
        self.assertEqual(P["uploads"], {"memory/a": "A0", "memory/b": "B2", "memory/n": None})
        self.assertEqual(P["fetch"], {"memory/b": "conflict-server", "memory/s": "download"})
        self.assertEqual(P["deletes"], {"memory/c": "C0"})

    def test_mass_delete_rule(self):
        self.assertTrue(brain_sync.mass_delete_hit(26, 1000))
        self.assertFalse(brain_sync.mass_delete_hit(25, 1000))
        self.assertTrue(brain_sync.mass_delete_hit(3, 20))
        self.assertFalse(brain_sync.mass_delete_hit(2, 10))
        self.assertFalse(brain_sync.mass_delete_hit(5, 100))


if __name__ == "__main__":
    unittest.main()
