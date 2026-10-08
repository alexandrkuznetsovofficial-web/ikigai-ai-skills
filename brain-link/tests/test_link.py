#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты установщика brain-link (kit 2.1): python3 -m unittest brain-link/tests/test_link.py -v
Только stdlib. Сеть и ssh не нужны: вызовы внешних команд идут через внедряемую функцию RUNNER
(подменяем фейком), скрытый ввод — через GETPASS. Каждый тест — своя временная «домашняя папка».
"""
import io
import json
import os
import plistlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
sys.path.insert(0, str(KIT / "scripts"))
import brain_link as bk  # noqa: E402

FAKE_CLAUDE_TOKEN = "sk-ant-oat01-" + "Q" * 40 + "-test"
FAKE_BOT_TOKEN = "1234567:" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
FAKE_PW = "S3cret" + "Passw0rd"   # собираем на лету: в исходнике не должно быть «пароля значением»


class FakeRunner:
    """Записывает вызовы; отвечает по первому совпавшему правилу (подстрока argv → код, stdout, stderr)."""

    def __init__(self, rules=None, default=(1, b"", b"")):
        self.calls = []
        self.rules = rules or []
        self.default = default

    def __call__(self, argv, input=None, timeout=120, env=None, cwd=None):
        line = " ".join(str(a) for a in argv)
        self.calls.append({"argv": [str(a) for a in argv], "input": input, "line": line})
        for needle, answer in self.rules:
            if needle in line:
                return answer
        return self.default


class Base(unittest.TestCase):
    os_name = "mac"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="brain-link-test-"))
        self.home = self.tmp / "home"
        self.cfg = self.home / ".config" / "brain"
        self.ws = self.tmp / "ws"
        (self.ws / "memory").mkdir(parents=True)
        self.cfg.mkdir(parents=True)
        (self.home / ".ssh").mkdir(parents=True)
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home), "BRAIN_CONFIG_DIR": str(self.cfg),
               "BRAIN_IKIGAI_ENV": str(self.home / ".claude" / "ikigai_env.json"), "BRAIN_NO_NOTIFY": "1",
               "BRAIN_LINK_OS": self.os_name}
        self.env_patch = mock.patch.dict(os.environ, env)
        self.env_patch.start()
        self.runner = FakeRunner()
        self.patches = [mock.patch.object(bk, "RUNNER", self.runner),
                        mock.patch.object(bk, "SLEEP", lambda s: None),
                        mock.patch.object(bk, "find_tool", lambda name: "/usr/bin/" + name)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.env_patch.stop()
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def access(self, text):
        (self.cfg / "server_access").write_text(text, encoding="utf-8")

    def ready_keys(self):
        (self.home / ".ssh" / "id_ed25519").write_text("fake", encoding="utf-8")
        (self.cfg / "known_hosts").write_text("[h]:22 ssh-ed25519 AAAA\n", encoding="utf-8")

    def call(self, argv):
        buf = io.StringIO()
        code = None
        with mock.patch.object(sys, "stdout", buf), mock.patch.object(sys, "stderr", io.StringIO()):
            try:
                bk.main(argv)
            except SystemExit as ex:
                code = ex.code
        raw = buf.getvalue()
        lines = [l for l in raw.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, "stdout — ровно один JSON: %r" % raw)
        return code, json.loads(lines[0]), raw


class TestDetect(Base):
    def test_no_access_file_is_config_error(self):
        code, res, _ = self.call(["detect"])
        self.assertEqual(code, 4)
        self.assertFalse(res["ok"])
        self.assertIn("файла доступа", res["human"])

    def test_old_keys_warn_and_no_secrets_printed(self):
        self.access("IP=10.20.30.40\nLOGIN=root\nPASSWORD=%s\nCLAUDE_TOKEN=%s\nUSER_ID=123456789\n"
                    % (FAKE_PW, FAKE_CLAUDE_TOKEN))
        code, res, raw = self.call(["detect"])
        self.assertEqual(code, 0, res)
        warns = " ".join(res["warnings"])
        self.assertIn("старый ключ IP", warns)
        self.assertIn("старый ключ LOGIN", warns)
        self.assertIn("CLAUDE_TOKEN", warns)
        self.assertEqual(res["next_step"], "keys")          # ключей нет → ssh даже не пробуем
        self.assertNotIn(FAKE_CLAUDE_TOKEN, raw)
        self.assertNotIn(FAKE_PW, raw)
        self.assertNotIn("10.20.30.40", raw)                # IP целиком не показываем
        self.assertFalse(any("ssh" in c["argv"][0] for c in self.runner.calls))

    def test_branch_a_from_server_probe(self):
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\n")
        self.ready_keys()
        probe = ("OS=Ubuntu 24.04 LTS\nWHO=root\nNOW=%d\nNTP=yes\nBRAIN=0\nCLAUDE=0\nHARDENED=0\nLOCKDOWN=0\n"
                 "HEARTBEAT=0\nBOT=inactive\nMEMFILES=0\nOLD_BOTS=\nUFW=inactive\nLEGACY_CRON=0\n"
                 "TOKEN_CLAUDE=0\nTOKEN_BOT=0\n" % int(__import__("time").time()))
        self.runner.rules = [("bash -s", (0, probe.encode(), b""))]
        code, res, _ = self.call(["detect"])
        self.assertEqual(code, 0, res)
        self.assertEqual(res["branch"], "A")
        self.assertEqual(res["next_step"], "harden")

    def test_branch_b_when_server_has_memory(self):
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\n")
        self.ready_keys()
        probe = ("WHO=root\nNOW=0\nNTP=yes\nBRAIN=1\nCLAUDE=1\nHARDENED=0\nHEARTBEAT=0\nBOT=active\n"
                 "MEMFILES=120\nOLD_BOTS=tg-bridge.service \nLEGACY_CRON=1\n")
        self.runner.rules = [("bash -s", (0, probe.encode(), b""))]
        code, res, _ = self.call(["detect"])
        self.assertEqual(res["branch"], "B")


class TestLockdown(Base):
    def test_without_confirmations_nothing_runs(self):
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\n")
        self.ready_keys()
        popen = mock.Mock(side_effect=AssertionError("POPEN не должен вызываться"))
        with mock.patch.object(bk, "POPEN", popen):
            for argv in (["lockdown"], ["lockdown", "--confirm"], ["lockdown", "--confirm-again"]):
                code, res, _ = self.call(argv)
                self.assertEqual(code, 3, argv)
                self.assertEqual(len(res["checklist"]), 3)
                self.assertFalse(any("окно" in x or "VNC" in x for x in res["checklist"]))
        self.assertEqual(self.runner.calls, [])
        popen.assert_not_called()

    def test_confirmed_but_verify_not_green_stops(self):
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\n")
        self.ready_keys()
        code, res, _ = self.call(["lockdown", "--confirm", "--confirm-again"])
        self.assertEqual(code, 1)
        self.assertIn("verify", res["human"])
        self.assertEqual(self.runner.calls, [])


class FakeSession:
    """Подмена POPEN для root-сессии lockdown: отвечает RELOADED, затем COMMITTED / ROLLEDBACK."""

    def __init__(self, *a, **k):
        import queue
        self.q = queue.Queue()
        self.sent = []
        outer = self

        class In:
            def write(self, data):
                outer.sent.append(data.decode())
                if b"brain_lockdown" in data:
                    outer.q.put(b"RELOADED\n")
                elif data == b"COMMIT\n":
                    outer.q.put(b"COMMITTED\n")
                elif data == b"ROLLBACK\n":
                    outer.q.put(b"ROLLEDBACK\n")

            def flush(self):
                pass

            def close(self):
                outer.q.put(b"")

        class Out:
            def readline(self):
                return outer.q.get(timeout=5)

        self.stdin, self.stdout = In(), Out()

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class TestLockdownFlow(Base):
    def setUp(self):
        super().setUp()
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\nPASSWORD=%s\n" % FAKE_PW)
        self.ready_keys()
        (self.cfg / "link_state.json").write_text('{"verify_green": true, "selfcheck": "pass"}', encoding="utf-8")
        self.sessions = []

        def popen(*a, **k):
            s = FakeSession()
            self.sessions.append(s)
            return s
        self.popen = mock.patch.object(bk, "POPEN", popen)
        self.popen.start()

    def tearDown(self):
        self.popen.stop()
        super().tearDown()

    def test_commit_and_offer_to_drop_password(self):
        self.runner.rules = [("PubkeyAuthentication=no", (255, b"", b"root@h: Permission denied (publickey).")),
                             ("root@", (255, b"", b"root@h: Permission denied (publickey).")),
                             ("brain@", (0, b"", b""))]
        code, res, raw = self.call(["lockdown", "--confirm", "--confirm-again"])
        self.assertEqual(code, 2, res)                    # готово, но предлагаем убрать PASSWORD
        self.assertIn("COMMIT\n", self.sessions[0].sent)
        self.assertTrue(json.loads((self.cfg / "link_state.json").read_text())["lockdown"])
        self.assertNotIn(FAKE_PW, raw)
        code, res, _ = self.call(["lockdown", "--drop-password"])
        self.assertEqual(code, 0)
        self.assertNotIn("PASSWORD", (self.cfg / "server_access").read_text())
        baks = list(self.cfg.glob("server_access.bak.*"))
        self.assertTrue(baks)
        for b in baks:
            self.assertNotIn(FAKE_PW, b.read_text())                   # копия без пароля

    def test_server_selfcheck_fail_refuses_even_with_accept_unverified(self):
        (self.cfg / "link_state.json").write_text('{"verify_green": true, "selfcheck": "unverified"}',
                                                  encoding="utf-8")
        for status in ("safe_mode: off\nselfcheck: fail\n", 'safe_mode: on\n{"reasons": {"canary-hit": {}}}\n'
                                                              "selfcheck: pass\n"):
            self.runner.rules = [("brain-admin status", (0, status.encode(), b"")), ("brain@", (0, b"", b""))]
            code, res, _ = self.call(["lockdown", "--confirm", "--confirm-again", "--accept-unverified"])
            self.assertEqual(code, 1, res)
            self.assertIn("НЕ ПРОШЛА", res["human"])
            self.assertEqual(self.sessions, [])               # root-сессию lockdown даже не открывали

    def test_rollback_when_password_still_accepted(self):
        self.runner.rules = [("PubkeyAuthentication=no",
                              (255, b"", b"root@h: Permission denied (publickey,password).")),
                             ("root@", (255, b"", b"denied")), ("brain@", (0, b"", b""))]
        code, res, _ = self.call(["lockdown", "--confirm", "--confirm-again"])
        self.assertEqual(code, 1)
        self.assertIn("ROLLBACK\n", self.sessions[0].sent)
        self.assertNotIn("COMMIT\n", self.sessions[0].sent)
        self.assertIn("автооткат", res["human"])
        self.assertFalse(json.loads((self.cfg / "link_state.json").read_text()).get("lockdown"))


class TestPutToken(Base):
    def setUp(self):
        super().setUp()
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\nBOT_TOKEN=%s\n" % FAKE_BOT_TOKEN)
        self.ready_keys()
        self.runner.rules = [("set-token", (0, "✅ токен записан\n".encode(), b""))]

    def test_claude_token_never_printed(self):
        with mock.patch.object(bk, "GETPASS", lambda prompt="": FAKE_CLAUDE_TOKEN):
            code, res, raw = self.call(["put-token", "claude", "--no-setup"])
        self.assertEqual(code, 0, res)
        self.assertNotIn(FAKE_CLAUDE_TOKEN, raw)
        self.assertNotIn(FAKE_CLAUDE_TOKEN[10:30], raw)
        sent = [c for c in self.runner.calls if "set-token claude" in c["line"]]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["input"], (FAKE_CLAUDE_TOKEN + "\n").encode())   # токен — только в stdin ssh
        self.assertNotIn(FAKE_CLAUDE_TOKEN, sent[0]["line"])                       # и не в argv

    def test_server_echo_is_scrubbed(self):
        self.runner.rules = [("set-token", (1, b"", ("bad " + FAKE_CLAUDE_TOKEN).encode()))]
        with mock.patch.object(bk, "GETPASS", lambda prompt="": FAKE_CLAUDE_TOKEN):
            code, res, raw = self.call(["put-token", "claude", "--no-setup"])
        self.assertEqual(code, 1)
        self.assertNotIn(FAKE_CLAUDE_TOKEN, raw)

    def test_bad_format_sends_nothing(self):
        with mock.patch.object(bk, "GETPASS", lambda prompt="": "sk-ant-" + "api03-not-a-subscription-token-xxxxxxxx"):
            code, res, raw = self.call(["put-token", "claude", "--no-setup"])
        self.assertEqual(code, 1)
        self.assertEqual([c for c in self.runner.calls if "set-token" in c["line"]], [])

    def test_bot_token_from_access_file_not_printed(self):
        code, res, raw = self.call(["put-token", "bot"])
        self.assertEqual(code, 0, res)
        self.assertNotIn(FAKE_BOT_TOKEN, raw)
        self.assertIn("файл доступа", res["human"])


class TestSchedule(Base):
    def setUp(self):
        super().setUp()
        self.runner.rules = [("launchctl", (0, b"", b""))]

    def test_plist_is_valid_and_escaped(self):
        text = bk.render_plist("/opt/py & co/bin/python3", "/Users/Иван Петров/brain_sync.py",
                               "/Users/Иван Петров", "/usr/bin:/bin")
        data = plistlib.loads(text.encode("utf-8"))
        self.assertEqual(data["Label"], "com.ikigai.brain-sync")
        self.assertEqual(data["ProgramArguments"],
                         ["/opt/py & co/bin/python3", "/Users/Иван Петров/brain_sync.py", "run"])
        self.assertEqual(data["StartInterval"], 300)
        self.assertEqual(data["EnvironmentVariables"]["HOME"], "/Users/Иван Петров")
        self.assertNotIn("{{", text)

    def test_plist_extra_args(self):
        text = bk.render_plist("/usr/bin/python3", "/k/brain_sync.py", "/h", "/usr/bin", ["--root", "/w s"])
        self.assertEqual(plistlib.loads(text.encode())["ProgramArguments"][-3:], ["run", "--root", "/w s"])

    def test_mac_schedule_writes_plist_and_bootstraps(self):
        code, res, _ = self.call(["schedule", "--wait", "0"])
        dest = self.home / "Library" / "LaunchAgents" / "com.ikigai.brain-sync.plist"
        self.assertTrue(dest.exists())
        data = plistlib.loads(dest.read_bytes())
        self.assertEqual(data["ProgramArguments"][1], str(bk.SYNC_PY))
        self.assertEqual(data["ProgramArguments"][2], "run")
        self.assertTrue(any("bootstrap" in c["line"] for c in self.runner.calls))
        self.assertEqual(code, 1)   # пробный синк за 0 с не отметился — честная ошибка, а не «готово»
        self.assertIn("не отметился", res["human"])
        # повтор: файл не тронут, без --replace чужой (изменённый) не перезаписывается
        dest.write_text(dest.read_text(encoding="utf-8").replace("300", "600"), encoding="utf-8")
        code, res, _ = self.call(["schedule", "--wait", "0"])
        self.assertEqual(code, 3)
        self.assertIn("600", dest.read_text(encoding="utf-8"))

    def test_tcc_hint(self):
        logs = self.home / "Library" / "Logs"
        logs.mkdir(parents=True)
        (logs / "brain-sync.log").write_text("PermissionError: [Errno 1] Operation not permitted: memory\n")
        code, res, _ = self.call(["schedule", "--wait", "0"])
        self.assertEqual(code, 2)
        self.assertIn("Полный доступ к диску", res["human"])


class TestScheduleWindows(Base):
    os_name = "windows"

    def test_ps1_has_bom_and_crlf(self):
        data = bk.render_ps1()
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        body = data[3:]
        self.assertNotIn(b"\xef\xbb\xbf", body)
        self.assertEqual(body.count(b"\n"), body.count(b"\r\n"))
        self.assertIn("Ikigai brain-sync".encode(), body)

    def test_windows_schedule_runs_powershell_file(self):
        self.runner.rules = [("schtasks /Query", (1, b"", b"")),
                             ("-ExecutionPolicy", (0, "Ikigai brain-sync | StartWhenAvailable=True".encode(), b""))]
        code, res, _ = self.call(["schedule", "--wait", "0"])
        ps1 = self.cfg / "install_task.ps1"
        self.assertTrue(ps1.read_bytes().startswith(b"\xef\xbb\xbf"))
        call = [c for c in self.runner.calls if "-ExecutionPolicy" in c["line"]][0]["argv"]
        self.assertIn("-File", call)
        self.assertEqual(call[call.index("-File") + 1], str(ps1))
        self.assertEqual(call[call.index("-Script") + 1], str(bk.SYNC_PY))


class TestInitPreview(Base):
    def test_init_without_yes_only_reports(self):
        bk_runner = bk.default_runner
        srv = self.tmp / "srv"
        srv.mkdir()
        (self.ws / "memory" / "a.md").write_text("привет", encoding="utf-8")
        (self.ws / "CLAUDE.md").write_text("# ядро", encoding="utf-8")
        skills = self.tmp / "skills"
        (skills / "demo").mkdir(parents=True, exist_ok=True)
        (skills / "demo" / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
        with mock.patch.object(bk, "RUNNER", bk_runner):
            code, res, _ = self.call(["init", "--root", str(self.ws), "--skills-dir", str(skills),
                                      "--transport", "local:%s" % srv])
        self.assertEqual(code, 3, res)
        self.assertTrue(res["report"]["dry_run"])
        self.assertEqual(res["report"]["upload"], 3)
        self.assertFalse((srv / "memory" / "a.md").exists())
        self.assertFalse((srv / "CLAUDE.md").exists())
        self.assertFalse((self.cfg / "sync_state.json").exists())


class TestCli(Base):
    def test_unknown_step_is_config(self):
        code, res, _ = self.call(["fly"])
        self.assertEqual(code, 4)

    def test_no_step(self):
        code, res, _ = self.call([])
        self.assertEqual(code, 4)
        self.assertIn("detect", res["human"])



FP = "SHA256:" + "k" * 43
FP_OTHER = "SHA256:" + "z" * 43
SCAN_LINE = b"10.20.30.40 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBrainLinkTestHostKey000000000000000000\n"


class TestKeys(Base):
    """keys: ключ сервера закрепляется при первом входе; --fingerprint — необязательная сверка.
    Здесь PASSWORD в файле доступа нет → запасной путь: команда для человека."""

    def setUp(self):
        super().setUp()
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\n")
        for k in (self.home / ".ssh" / "id_ed25519", self.home / ".ssh" / "brain_sync_ed25519"):
            k.write_text("fake", encoding="utf-8")
            Path(str(k) + ".pub").write_text("ssh-ed25519 " + "A" * 68 + " t\n", encoding="utf-8")
        self.login = (255, b"", b"root@h: Permission denied (publickey,password).")
        self.runner.rules = [("ssh-keyscan", (0, SCAN_LINE, b"")),
                             ("ssh-keygen -l", (0, ("256 %s no comment (ED25519)\n" % FP).encode(), b"")),
                             (" true", self.login)]

    def kh(self):
        return self.cfg / "known_hosts"

    def test_without_fingerprint_trusts_first_use(self):
        code, res, raw = self.call(["keys"])
        self.assertEqual(code, 2, res)                         # ключ закреплён, ждём ssh-copy-id от человека
        self.assertEqual(self.kh().read_bytes(), SCAN_LINE)   # как ssh accept-new: без VNC
        self.assertEqual(res["host_key_check"], "first_use")
        self.assertIn("ssh-copy-id", res["command"])
        self.assertIn("PASSWORD", res["human"])                # подсказка: впиши пароль — сделаю сам
        self.assertFalse(any("SSH_ASKPASS" in str(c) for c in self.runner.calls))

    def test_windows_keyscan_falls_back_to_git(self):
        git = self.home / "PF" / "Git" / "usr" / "bin"
        git.mkdir(parents=True)
        (git / "ssh-keyscan.exe").write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, {"BRAIN_LINK_OS": "windows", "ProgramFiles": str(self.home / "PF")}):
            tools = bk.keyscan_tools()
        self.assertIn(str(git / "ssh-keyscan.exe"), tools)

    def test_wrong_fingerprint_refused(self):
        code, res, _ = self.call(["keys", "--fingerprint", FP_OTHER])
        self.assertEqual(code, 1, res)
        self.assertFalse(self.kh().exists())
        self.assertNotIn("command", res)

    def test_confirmed_fingerprint_pins_then_gives_command(self):
        code, res, _ = self.call(["keys", "--fingerprint", "256 %s root@vps (ED25519)" % FP])
        self.assertEqual(code, 2, res)                         # ключ закреплён, ждём ssh-copy-id от человека
        self.assertEqual(self.kh().read_bytes(), SCAN_LINE)
        self.assertIn("ssh-copy-id", res["command"])
        self.assertEqual(res["host_key"], "created")
        self.assertEqual(res["host_key_check"], "fingerprint")
        # человек выполнил команду → повтор keys уже без --fingerprint: ключ подтверждён ранее
        self.runner.rules[-1] = (" true", (0, b"", b""))
        code, res, _ = self.call(["keys"])
        self.assertEqual(code, 0, res)
        self.assertEqual(res["host_key"], "kept")

    def test_pinned_without_confirmation_confirms_silently(self):
        self.kh().write_bytes(SCAN_LINE)                       # закреплён старой версией, тот же ключ
        code, res, _ = self.call(["keys"])
        self.assertEqual(code, 2, res)
        self.assertEqual(res["host_key"], "confirmed")

    def test_changed_server_key_needs_replace(self):
        self.kh().write_text("10.20.30.40 ssh-ed25519 AAAAOTHERKEY\n", encoding="utf-8")
        code, res, _ = self.call(["keys", "--fingerprint", FP])
        self.assertEqual(code, 2)
        self.assertEqual(res["next_step"], "keys --replace")
        self.assertIn("OTHERKEY", self.kh().read_text())

    def test_replace_without_fingerprint_shows_old_and_new(self):
        self.kh().write_text("10.20.30.40 ssh-ed25519 AAAAOTHERKEY\n", encoding="utf-8")
        code, res, _ = self.call(["keys", "--replace"])
        self.assertEqual(code, 2, res)
        self.assertEqual(res["host_key"], "replaced")
        self.assertEqual(res["host_key_check"], "first_use")
        self.assertIn("old_fingerprints", res)
        self.assertEqual(self.kh().read_bytes(), SCAN_LINE)

    def test_keyscan_tries_next_tool_when_first_empty(self):
        with mock.patch.object(bk, "keyscan_tools", return_value=["/bad/ssh-keyscan", "/git/ssh-keyscan"]):
            self.runner.rules = [("/bad/ssh-keyscan", (255, b"", b"choose_kex: unsupported KEX method sntrup761x25519-sha512@openssh.com")),
                                 ("/git/ssh-keyscan", (0, SCAN_LINE, b""))] + self.runner.rules[1:]
            code, res, _ = self.call(["keys"])
        self.assertEqual(code, 2, res)
        self.assertEqual(self.kh().read_bytes(), SCAN_LINE)

    def test_keyscan_kex_failure_explained(self):
        with mock.patch.object(bk, "keyscan_tools", return_value=["/bad/ssh-keyscan"]):
            self.runner.rules = [("/bad/ssh-keyscan", (255, b"", b"choose_kex: unsupported KEX method sntrup761x25519-sha512@openssh.com"))]
            code, res, raw = self.call(["keys"])
        self.assertEqual(code, 1, res)
        self.assertIn("Git for Windows", raw)

    def test_keyscan_kex_failure_with_git_already_tried_no_git_advice(self):
        with mock.patch.dict(os.environ, {"BRAIN_LINK_OS": "windows"}), \
                mock.patch.object(bk, "keyscan_tools", return_value=["/win/ssh-keyscan", "/git/ssh-keyscan"]):
            self.runner.rules = [("ssh-keyscan", (255, b"", b"choose_kex: unsupported KEX method x"))]
            code, res, raw = self.call(["keys"])
        self.assertEqual(code, 1, res)
        self.assertNotIn("Git for Windows", res["human"])
        self.assertIn("сервер не отдал свой ключ", res["human"])

    def test_windows_copy_id_quotes_path(self):
        with mock.patch.dict(os.environ, {"BRAIN_LINK_OS": "windows"}):
            cmd = bk.copy_id_command({"SERVER_IP": "10.20.30.40", "SERVER_PORT": "22"})
        self.assertTrue(cmd.startswith('type "$env:USERPROFILE\\.ssh\\id_ed25519.pub" | ssh -p 22 root@'), cmd)


class TestKeysByPassword(Base):
    """keys с PASSWORD в файле доступа: ключ кладёт сам через SSH_ASKPASS, человек терминал не открывает."""

    def setUp(self):
        super().setUp()
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\nPASSWORD=%s\n" % FAKE_PW)
        for k in (self.home / ".ssh" / "id_ed25519", self.home / ".ssh" / "brain_sync_ed25519"):
            k.write_text("fake", encoding="utf-8")
            Path(str(k) + ".pub").write_text("ssh-ed25519 " + "A" * 68 + " t\n", encoding="utf-8")
        self.envs, self.helpers, self.helper_out = [], [], []
        self.logged_in = False
        self.helper_runs = True          # «ssh» вызвал помощник (метка .used)
        self.real_helper = False         # запустить настоящий помощник (POSIX) и забрать пароль
        test = self

        class Runner(FakeRunner):
            def __call__(self, argv, input=None, timeout=120, env=None, cwd=None):
                line = " ".join(str(a) for a in argv)
                if "PubkeyAuthentication=no" in line and "authorized_keys" in line:
                    env = dict(env or {})
                    test.envs.append(env)
                    hp = Path(env.get("SSH_ASKPASS", ""))
                    test.helpers.append((hp, hp.exists(), hp.read_bytes() if hp.exists() else b""))
                    self.calls.append({"argv": [str(a) for a in argv], "input": input, "line": line})
                    if test.real_helper:
                        import subprocess
                        r = subprocess.run([str(hp), "root@10.20.30.40's password: "], capture_output=True, env=env)
                        test.helper_out.append(r.stdout.decode())
                    elif test.helper_runs:
                        (hp.parent / ".used").write_text("", encoding="utf-8")
                    ans = test.push_answer
                    if ans[0] == 0:
                        test.logged_in = True
                    return ans
                if line.endswith(" true"):
                    self.calls.append({"argv": [str(a) for a in argv], "input": input, "line": line})
                    return (0, b"", b"") if test.logged_in else \
                        (255, b"", b"root@h: Permission denied (publickey,password).")
                return super().__call__(argv, input=input, timeout=timeout, env=env, cwd=cwd)

        self.runner.__class__ = Runner
        self.runner.rules = [("ssh-keyscan", (0, SCAN_LINE, b"")),
                             ("ssh-keygen -l", (0, ("256 %s no comment (ED25519)\n" % FP).encode(), b""))]
        self.push_answer = (0, b"", b"")

    def push_calls(self):
        return [c for c in self.runner.calls if "authorized_keys" in c["line"]]

    def assert_no_password_leak(self, raw):
        self.assertNotIn(FAKE_PW, raw)
        for c in self.runner.calls:
            self.assertNotIn(FAKE_PW, c["line"])                       # ни в одном argv
        for env in self.envs:
            self.assertFalse(any(FAKE_PW in str(v) for v in env.values()))   # ни в окружении ssh
        for _, _, body in self.helpers:
            self.assertNotIn(FAKE_PW.encode(), body)                   # ни в файле помощника

    def test_password_path_installs_key_logs_in_and_drops_password(self):
        code, res, raw = self.call(["keys"])
        self.assertEqual(code, 0, res)
        self.assertEqual(res["key_installed"], "password")
        self.assertTrue(res["password_line_removed"])
        self.assertIn("менеджере паролей", res["human"])
        self.assertNotIn("PASSWORD", (self.cfg / "server_access").read_text())
        self.assertIn("SERVER_IP=", (self.cfg / "server_access").read_text())
        self.assertEqual(list(self.cfg.glob("server_access.bak*")), [])  # копии с паролем не осталось
        self.assertNotIn("command", res)
        pc = self.push_calls()
        self.assertEqual(len(pc), 1)                                   # одна попытка (fail2ban)
        argv = pc[0]["argv"]
        for opt in ("StrictHostKeyChecking=yes", "PubkeyAuthentication=no", "NumberOfPasswordPrompts=1",
                    "PreferredAuthentications=password", "ConnectTimeout=15"):
            self.assertIn(opt, argv)
        self.assertNotIn("keyboard-interactive", " ".join(argv))
        self.assertEqual(argv[1:3], ["-F", "none"])                   # чужой ~/.ssh/config не влияет
        self.assertTrue(any(a.startswith("UserKnownHostsFile=") and "known_hosts" in a for a in argv))
        self.assertIn("root@10.20.30.40", argv)
        self.assertIn("grep -qxF", argv[-1])                           # идемпотентно: ключ не дублируется
        self.assertIn("tail -c1", argv[-1])                            # файл без \n в конце — сначала \n
        self.assertEqual(pc[0]["input"], (self.home / ".ssh" / "id_ed25519.pub").read_bytes())
        env = self.envs[0]
        self.assertEqual(env["SSH_ASKPASS_REQUIRE"], "force")
        self.assertTrue(env.get("DISPLAY"))
        self.assertGreaterEqual(len(env.get(bk.ASKPASS_NONCE_ENV, "")), 40)
        hp, existed, body = self.helpers[0]
        self.assertTrue(existed)
        self.assertTrue(hp.parent.name.startswith("brain-askpass-"))
        self.assertIn(b"_askpass", body)
        self.assertNotIn(env[bk.ASKPASS_NONCE_ENV].encode(), body)    # нонс — только в окружении
        self.assertFalse(hp.parent.exists())                           # временная папка удалена
        self.assert_no_password_leak(raw)

    def test_real_posix_helper_gives_password_to_ssh_only(self):
        if os.name == "nt":
            self.skipTest("POSIX")
        self.real_helper = True
        code, res, raw = self.call(["keys"])
        self.assertEqual(code, 0, res)
        self.assertEqual(self.helper_out, [FAKE_PW + "\n"])
        self.assert_no_password_leak(raw)

    def test_wrong_password_is_human_without_secret(self):
        self.push_answer = (255, b"", ("root@10.20.30.40: Permission denied (publickey,password). %s" % FAKE_PW).encode())
        code, res, raw = self.call(["keys"])
        self.assertEqual(code, 2, res)
        self.assertIn("пароль root в файле доступа не подошёл", res["human"])
        self.assertIn("PASSWORD", res["human"])
        self.assertEqual(res["key_install"], "password_rejected")
        self.assertEqual(len(self.push_calls()), 1)                    # не долбим сервер повторами
        self.assertIn("PASSWORD", (self.cfg / "server_access").read_text())   # не подошёл — не трогаем
        self.assert_no_password_leak(raw)

    def test_askpass_not_called_is_askpass_failed_even_with_permission_denied(self):
        self.helper_runs = False
        self.push_answer = (255, b"", b"ssh_askpass: exec(/tmp/brain-askpass-x/askpass.sh): No such file or "
                                      b"directory\r\nroot@10.20.30.40: Permission denied (publickey,password).\r\n")
        code, res, raw = self.call(["keys"])
        self.assertEqual(code, 2, res)
        self.assertEqual(res["key_install"], "askpass_failed")
        self.assertIn("ssh-copy-id", res["command"])
        self.assert_no_password_leak(raw)

    def test_password_auth_disabled_on_server(self):
        self.helper_runs = False
        self.push_answer = (255, b"", b"root@10.20.30.40: Permission denied (publickey).\r\n")
        code, res, _ = self.call(["keys"])
        self.assertEqual(code, 2, res)
        self.assertEqual(res["key_install"], "password_auth_disabled")
        self.assertIn("не принимает вход по паролю", res["human"])
        self.assertIn("command", res)

    def test_network_error_is_not_turned_into_command(self):
        self.helper_runs = False
        self.push_answer = (255, b"", b"ssh: connect to host 10.20.30.40 port 22: Connection timed out")
        code, res, _ = self.call(["keys"])
        self.assertEqual(code, 1, res)
        self.assertNotIn("command", res)

    def test_after_lockdown_password_path_not_used(self):
        (self.cfg / "link_state.json").write_text('{"lockdown": true}', encoding="utf-8")
        code, res, _ = self.call(["keys"])
        self.assertEqual(code, 2, res)
        self.assertEqual(self.push_calls(), [])
        self.assertIn("command", res)

    def test_replaced_host_key_without_fingerprint_does_not_send_password(self):
        (self.cfg / "known_hosts").write_text("10.20.30.40 ssh-ed25519 AAAAOTHERKEY\n", encoding="utf-8")
        code, res, raw = self.call(["keys", "--replace"])
        self.assertEqual(code, 2, res)
        self.assertEqual(res["host_key"], "replaced")
        self.assertEqual(res["key_install"], "host_key_replaced")
        self.assertIn("пароль не отправляю", res["human"])
        self.assertIn("command", res)
        self.assertEqual(self.push_calls(), [])
        self.assert_no_password_leak(raw)

    def test_replace_then_plain_keys_still_does_not_send_password(self):
        (self.cfg / "known_hosts").write_text("10.20.30.40 ssh-ed25519 AAAAOTHERKEY\n", encoding="utf-8")
        code, res, _ = self.call(["keys", "--replace"])
        self.assertEqual(res["key_install"], "host_key_replaced")
        st = json.loads((self.cfg / "link_state.json").read_text())
        self.assertTrue(st["host_key_unverified"])
        self.assertFalse(st["host_key_confirmed"])
        for _ in range(2):                                             # флаг держится между запусками
            code, res, raw = self.call(["keys"])
            self.assertEqual(code, 2, res)
            self.assertEqual(res["key_install"], "host_key_replaced")
            self.assertNotIn("?", res["human"].split("было ")[1].split(",")[0][:1])   # старый отпечаток помним
        self.assertEqual(self.push_calls(), [])
        # совпавший --fingerprint снимает флаг — тогда пароль уходит
        code, res, _ = self.call(["keys", "--fingerprint", FP])
        self.assertEqual(code, 0, res)
        self.assertEqual(len(self.push_calls()), 1)
        st = json.loads((self.cfg / "link_state.json").read_text())
        self.assertFalse(st["host_key_unverified"])
        self.assertTrue(st["host_key_confirmed"])

    def test_state_deleted_after_replace_no_password(self):
        (self.cfg / "known_hosts").write_text("10.20.30.40 ssh-ed25519 AAAAOTHERKEY\n", encoding="utf-8")
        self.call(["keys", "--replace"])
        (self.cfg / "link_state.json").unlink()                        # состояние потеряно, known_hosts остался
        code, res, _ = self.call(["keys"])
        self.assertEqual(code, 2, res)
        self.assertEqual(res["key_install"], "host_key_replaced")
        self.assertIn("ED25519", res["human"])
        self.assertEqual(self.push_calls(), [])

    def test_state_corrupted_no_password(self):
        self.kh_pinned()
        (self.cfg / "link_state.json").write_text("{испорчено", encoding="utf-8")
        code, res, _ = self.call(["keys"])
        self.assertEqual(code, 2, res)
        self.assertEqual(res["key_install"], "host_key_replaced")
        self.assertEqual(self.push_calls(), [])

    def test_state_fingerprints_mismatch_no_password(self):
        self.kh_pinned()
        (self.cfg / "link_state.json").write_text(json.dumps(
            {"host_key_confirmed": True, "host_fingerprints": ["%s (ED25519)" % FP_OTHER]}), encoding="utf-8")
        code, res, _ = self.call(["keys"])
        self.assertEqual(res.get("key_install"), "host_key_replaced", res)
        self.assertEqual(self.push_calls(), [])

    def test_compat_state_from_f292f2d_sends_password(self):
        self.kh_pinned()
        (self.cfg / "link_state.json").write_text(json.dumps(
            {"host_key_confirmed": True, "host_fingerprints": ["%s (ED25519)" % FP]}), encoding="utf-8")
        code, res, _ = self.call(["keys"])
        self.assertEqual(code, 0, res)
        self.assertEqual(res["host_key"], "kept")
        self.assertEqual(len(self.push_calls()), 1)

    def test_unverified_but_key_login_works_says_so(self):
        self.kh_pinned()                                               # состояния нет — ключ не сверен
        self.logged_in = True
        code, res, _ = self.call(["keys"])
        self.assertEqual(code, 0, res)
        self.assertIn("не сверен", res["human"])
        self.assertEqual(self.push_calls(), [])

    def kh_pinned(self):
        (self.cfg / "known_hosts").write_bytes(SCAN_LINE)

    def test_wrong_fingerprint_keeps_flag(self):
        (self.cfg / "known_hosts").write_text("10.20.30.40 ssh-ed25519 AAAAOTHERKEY\n", encoding="utf-8")
        self.call(["keys", "--replace"])
        code, res, _ = self.call(["keys", "--fingerprint", FP_OTHER])
        self.assertEqual(code, 1, res)
        self.assertTrue(json.loads((self.cfg / "link_state.json").read_text())["host_key_unverified"])
        self.assertEqual(self.push_calls(), [])

    def test_reminder_about_password_manager_before_push(self):
        err = io.StringIO()
        buf = io.StringIO()
        with mock.patch.object(sys, "stdout", buf), mock.patch.object(sys, "stderr", err):
            with self.assertRaises(SystemExit):
                bk.main(["keys"])
        self.assertIn("менеджере паролей", err.getvalue())
        self.assertLess(err.getvalue().index("менеджере паролей"), err.getvalue().index("кладу твой ключ"))

    def test_replaced_host_key_with_matching_fingerprint_sends_password(self):
        (self.cfg / "known_hosts").write_text("10.20.30.40 ssh-ed25519 AAAAOTHERKEY\n", encoding="utf-8")
        code, res, _ = self.call(["keys", "--replace", "--fingerprint", FP])
        self.assertEqual(code, 0, res)
        self.assertEqual(len(self.push_calls()), 1)


class TestAskpassHelper(Base):
    """Внутренняя подкоманда _askpass: пароль — только ssh этого запуска (нонс), один раз, только на вопрос о пароле."""

    def setUp(self):
        super().setUp()
        self.access("SERVER_IP=10.20.30.40\nPASSWORD=%s\n" % FAKE_PW)
        self.d = Path(tempfile.mkdtemp(prefix="brain-askpass-", dir=tempfile.gettempdir()))
        self.nonce = "n" * 43
        (self.d / ".nonce").write_text(bk._sha256_hex(self.nonce), encoding="ascii")

    def tearDown(self):
        shutil.rmtree(str(self.d), ignore_errors=True)
        super().tearDown()

    def askpass(self, args, nonce="default", os_name=None):
        buf = io.BytesIO()

        class Out:
            buffer = buf

            def flush(self):
                pass

            def write(self, t):
                buf.write(t.encode())
        env = {bk.ASKPASS_NONCE_ENV: self.nonce if nonce == "default" else (nonce or "")}
        if os_name:
            env["BRAIN_LINK_OS"] = os_name
        with mock.patch.dict(os.environ, env), mock.patch.object(sys, "stdout", Out()):
            with self.assertRaises(SystemExit) as cm:
                bk.main(["_askpass"] + args)
        return cm.exception.code, buf.getvalue().decode()

    PROMPT = "root@10.20.30.40's password: "

    def test_prints_password_once(self):
        self.assertEqual(self.askpass([str(self.d), self.PROMPT]), (0, FAKE_PW + "\n"))
        self.assertEqual(self.askpass([str(self.d), self.PROMPT]), (1, ""))   # вторая попытка за запуск — нет

    def test_no_or_wrong_nonce_gives_nothing(self):
        self.assertEqual(self.askpass([str(self.d), self.PROMPT], nonce=None), (1, ""))
        self.assertEqual(self.askpass([str(self.d), self.PROMPT], nonce="x" * 43), (1, ""))
        (self.d / ".nonce").unlink()
        self.assertEqual(self.askpass([str(self.d), self.PROMPT]), (1, ""))
        self.assertFalse((self.d / ".used").exists())                  # чужой вызов не сжигает попытку

    def test_empty_or_foreign_prompt_gives_nothing(self):
        self.assertEqual(self.askpass([str(self.d)]), (1, ""))
        self.assertEqual(self.askpass([str(self.d), "  "]), (1, ""))
        self.assertEqual(self.askpass([str(self.d), "Are you sure you want to continue connecting (yes/no)?"]),
                         (1, ""))
        self.assertEqual(self.askpass([]), (1, ""))

    def test_split_prompt(self):
        self.assertEqual(self.askpass([str(self.d), "(root@h)", "Password:"]), (0, FAKE_PW + "\n"))

    def test_windows_needs_no_prompt_but_needs_nonce(self):
        self.assertEqual(self.askpass([str(self.d)], nonce=None, os_name="windows"), (1, ""))
        self.assertEqual(self.askpass([str(self.d)], os_name="windows"), (0, FAKE_PW + "\n"))

    def test_dir_must_be_brain_askpass_in_system_temp(self):
        other = self.tmp / "brain-askpass-fake"                        # не в системной временной папке
        other.mkdir()
        (other / ".nonce").write_text(bk._sha256_hex(self.nonce), encoding="ascii")
        self.assertEqual(self.askpass([str(other), self.PROMPT]), (1, ""))
        wrong = Path(tempfile.mkdtemp(prefix="other-", dir=tempfile.gettempdir()))
        try:
            (wrong / ".nonce").write_text(bk._sha256_hex(self.nonce), encoding="ascii")
            self.assertEqual(self.askpass([str(wrong), self.PROMPT]), (1, ""))
        finally:
            shutil.rmtree(str(wrong), ignore_errors=True)
        self.assertEqual(self.askpass([str(self.tmp / "nope"), self.PROMPT]), (1, ""))

    def test_no_password_in_file(self):
        self.access("SERVER_IP=10.20.30.40\n")
        self.assertEqual(self.askpass([str(self.d), self.PROMPT]), (1, ""))

    def test_posix_helper_runs_this_script(self):
        helper, extra = bk.make_askpass(str(self.d))
        body = helper.read_text(encoding="utf-8")
        self.assertTrue(body.startswith("#!/bin/sh\nexec "))
        self.assertIn("brain_link.py", body)
        self.assertIn(" _askpass ", body)
        self.assertNotIn(FAKE_PW, body)
        self.assertEqual(extra, {})
        if os.name != "nt":
            self.assertEqual(helper.stat().st_mode & 0o777, 0o700)

    def test_windows_helper_is_ascii_cmd_without_prompt(self):
        weird = self.tmp / "Анна Ли" / "tmp dir"
        weird.mkdir(parents=True)
        with mock.patch.dict(os.environ, {"BRAIN_LINK_OS": "windows"}):
            helper, extra = bk.make_askpass(str(weird))
        self.assertEqual(helper.suffix, ".cmd")
        body = helper.read_bytes()
        body.decode("ascii")                                           # только ASCII: cmd читает в cp866
        self.assertIn(b'"%BRAIN_ASKPASS_PY%" "%BRAIN_ASKPASS_SCRIPT%" _askpass "%BRAIN_ASKPASS_DIR%"\r\n', body)
        self.assertNotIn(b"%*", body)                                  # подсказку сервера в cmd не передаём
        self.assertEqual(extra["BRAIN_ASKPASS_DIR"], str(weird))
        self.assertTrue(extra["BRAIN_ASKPASS_SCRIPT"].endswith("brain_link.py"))

    def test_run_askpass_ssh_end_to_end(self):
        """Общая функция (её же зовёт лаборатория CI): «ssh» — настоящий процесс, который зовёт SSH_ASKPASS."""
        if os.name == "nt":
            self.skipTest("POSIX")
        fake_ssh = self.tmp / "fake_ssh.sh"
        fake_ssh.write_text('#!/bin/sh\npw=$("$SSH_ASKPASS" "root@h\'s password: ")\n'
                            '[ -n "$pw" ] && echo "got-password" && echo "len=${#pw}" >&2 && echo "$pw" >&2\n',
                            encoding="utf-8")
        os.chmod(str(fake_ssh), 0o700)
        before = set(Path(tempfile.gettempdir()).glob("brain-askpass-*"))
        with mock.patch.object(bk, "RUNNER", bk.default_runner):
            r = bk.run_askpass_ssh([str(fake_ssh)], input_bytes=b"")
        self.assertEqual(r["rc"], 0, r)
        self.assertTrue(r["askpass_called"])
        self.assertEqual(r["stdout"].strip(), "got-password")
        self.assertNotIn(FAKE_PW, r["stderr"])                        # stderr маскируется (точное значение)
        self.assertIn("•••", r["stderr"])
        self.assertFalse(set(Path(tempfile.gettempdir()).glob("brain-askpass-*")) - before)  # своя папка убрана

    def test_run_askpass_ssh_custom_access_path(self):
        if os.name == "nt":
            self.skipTest("POSIX")
        alt = self.tmp / "alt_access"
        alt.write_text("SERVER_IP=10.20.30.40\nPASSWORD=Alt%s\n" % FAKE_PW, encoding="utf-8")
        fake_ssh = self.tmp / "fake_ssh.sh"
        fake_ssh.write_text('#!/bin/sh\n"$SSH_ASKPASS" "Password:"\n', encoding="utf-8")
        os.chmod(str(fake_ssh), 0o700)
        with mock.patch.object(bk, "RUNNER", bk.default_runner):
            r = bk.run_askpass_ssh([str(fake_ssh)], access_path=alt)
        self.assertEqual(r["rc"], 0, r)
        self.assertNotIn(FAKE_PW, r["stdout"])                         # и альтернативный пароль маскируется
        self.assertTrue(r["askpass_called"])


class TestOldBots(Base):
    def test_name_rules(self):
        # kit 2.3: brain-bot.service по имени — тоже бот; свой ли он, решает серверный скан по ExecStart
        for u in ("tg-bridge.service", "my_bot.service", "telegram@main.service", "bot.service", "old.tg.service",
                  "brain-bot.service"):
            self.assertTrue(bk.looks_like_bot_unit(u), u)
        for u in ("postgresql.service", "postgresql@16-main.service", "robot-vacuum.service", "nginx.service",
                  "abbotsford.service", "systemd-tg.service", "brain-brief.service"):
            self.assertFalse(bk.looks_like_bot_unit(u), u)

    def test_protected_never_offered(self):
        text = ("OLD=postgresql.service\nOLD=mysql.service nginx.service\nOLD=ssh.service\nOLD=docker.service\n"
                "OLD=systemd-resolved.service\nOLD=cron.service\nOLD=ufw.service\nOLD=fail2ban.service\n"
                "OLD=apache2.service\nOLD=brain-bot.service\nOLD=tg-bridge.service\nOLD=bad;rm.service\n")
        # brain-bot.service в списке OLD= уже прошёл серверную проверку «не наш ExecStart» — его можно предлагать
        self.assertEqual(bk.old_bot_units(text), ["brain-bot.service", "tg-bridge.service"])

    def test_bot_step_offers_only_real_bots(self):
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\n")
        self.ready_keys()
        self.runner.rules = [("bash -s", (0, b"OLD=postgresql.service\nOLD=tg-bridge.service\n", b""))]
        code, res, _ = self.call(["bot"])
        self.assertEqual(code, 3, res)
        self.assertEqual(res["old_bots"], ["tg-bridge.service"])
        self.assertNotIn("postgresql", res["human"])

    @unittest.skipUnless(shutil.which("bash") and os.name != "nt",
                         "shell-скан исполняется на Linux-сервере (на Windows bash раннера — WSL/MSYS без PATH-подмены)")
    def test_shell_scan_with_fake_systemctl(self):
        import subprocess
        fake = self.tmp / "bin"
        fake.mkdir()
        (fake / "systemctl").write_text(r"""#!/bin/sh
case "$1" in
  list-units) printf '%s\n' 'postgresql.service loaded active running PG' 'postgresql@16-main.service loaded active running PG' \
      'tg-bridge.service loaded active running X' 'notgood.service loaded active running X' \
      'worker.service loaded active running X' 'nginx.service loaded active running X' \
      'brain-bot.service loaded active running X' 'cron.service loaded active running X' ;;
  is-active) echo active ;;
  is-enabled) echo enabled ;;
  show) case "$*" in *worker.service*) echo 'Environment=BOT_TOKEN=x' ;;
                     *nginx.service*) echo 'Environment=TELEGRAM=1' ;;
                     *brain-bot.service*) echo '{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 /usr/local/lib/brain-bot/brain_bot.py run ; }' ;;
                     *) echo 'ExecStart=/usr/bin/x' ;; esac ;;
esac
""", encoding="utf-8")
        os.chmod(str(fake / "systemctl"), 0o755)
        env = dict(os.environ, PATH=str(fake) + os.pathsep + os.environ.get("PATH", ""))
        for script, needle in ((bk.OLD_BOTS_SH, "OLD="), (bk.PROBE_SH, "OLD_BOTS=")):
            r = subprocess.run(["bash", "-c", script], capture_output=True, env=env, timeout=60)
            out = r.stdout.decode("utf-8", "replace")
            found = " ".join(l for l in out.splitlines() if l.startswith(needle))
            self.assertIn("tg-bridge.service", found)
            self.assertIn("worker.service", found)          # по BOT_TOKEN в окружении юнита
            for bad in ("postgresql", "notgood", "nginx", "brain-bot", "cron"):
                self.assertNotIn(bad, found, script[:40])


# ---------------------------------------------------------------------------------------------------------
# kit 2.3: апгрейд уже настроенного сервера — чужой brain-bot, перенос токена, sshd -T в lockdown
# ---------------------------------------------------------------------------------------------------------
FAKE_SYSTEMCTL_PY = r"""#!/usr/bin/env python3
import json, os, sys
units = json.load(open(os.environ["FAKE_SYSTEMD"], encoding="utf-8"))
a = sys.argv[1:]
cmd = a[0] if a else ""
if cmd == "list-units":
    for u in units:
        print("%s loaded active running X" % u)
elif cmd in ("is-active", "is-enabled"):
    print("active" if cmd == "is-active" else "enabled")
elif cmd == "show":
    props, value, unit = [], "--value" in a, a[-1]
    for i, x in enumerate(a):
        if x == "-p":
            props.append(a[i + 1])
    d = units.get(unit, {})
    for pr in props:
        v = d.get(pr, "")
        if pr == "ExecStart" and v:
            v = "{ path=%s ; argv[]=%s ; ignore_errors=no ; }" % (v.split()[0], v)
        if pr == "LoadState":
            v = "loaded" if unit in units else "not-found"
        print(v if value else "%s=%s" % (pr, v))
"""


class UpgradeShellBase(Base):
    """Серверный скан (OLD_SCAN) на настоящем bash с фейковым systemctl (python), данные юнитов — JSON."""

    def fake_server(self, units):
        fake = self.tmp / "bin"
        fake.mkdir(exist_ok=True)
        (fake / "systemctl").write_text(FAKE_SYSTEMCTL_PY, encoding="utf-8")
        os.chmod(str(fake / "systemctl"), 0o755)
        data = self.tmp / "units.json"
        data.write_text(json.dumps(units), encoding="utf-8")
        return dict(os.environ, PATH=str(fake) + os.pathsep + os.environ.get("PATH", ""), FAKE_SYSTEMD=str(data))

    def bash(self, script, env):
        import subprocess
        r = subprocess.run(["bash", "-c", script], capture_output=True, env=env, timeout=60)
        return r.stdout.decode("utf-8", "replace")


BRIDGE_TOKEN = "7712345:" + "BrIdGe" * 6 + "x"          # фейк, формат как у @BotFather
JULY_TOKEN = "6654321:" + "JuLyKiT" * 5 + "q"


@unittest.skipUnless(shutil.which("bash") and os.name != "nt", "серверный скан исполняется на Linux-сервере")
class TestForeignBrainBot(UpgradeShellBase):
    def bridge(self):
        proj = self.tmp / "bridge"
        (proj / "venv" / "bin").mkdir(parents=True)
        (proj / ".env").write_text("TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_BOT_USERNAME=my_brain_bot\n"
                                   "ALLOWED_USERS=[123456789]\nAPPROVED_DIRECTORY=/home/brain\n" % BRIDGE_TOKEN,
                                   encoding="utf-8")
        return {"brain-bot.service": {"ExecStart": str(proj / "venv" / "bin" / "claude-telegram-bot"),
                                      "WorkingDirectory": str(proj), "User": "brain",
                                      "FragmentPath": "/etc/systemd/system/brain-bot.service"}}

    def july(self):
        envf = self.tmp / "tgbot.env"
        envf.write_text('export BOT_TOKEN="%s"\nOWNER_ID=987654321  # владелец\n' % JULY_TOKEN, encoding="utf-8")
        return {"brain-bot.service": {"ExecStart": "/usr/bin/python3 %s/tgbot/bot.py" % self.tmp,
                                      "EnvironmentFiles": "%s (ignore_errors=no)" % envf, "User": "brain",
                                      "FragmentPath": "/etc/systemd/system/brain-bot.service"}}

    def ours(self):
        return {"brain-bot.service": {"ExecStart": "/usr/bin/python3 /usr/local/lib/brain-bot/brain_bot.py run",
                                      "Environment": "OWNER_ID=111 TELEGRAM_API_BASE=http://127.0.0.1:18081",
                                      "User": "brainbot"},
                "brain-brief.service": {"ExecStart": "/usr/bin/python3 /usr/local/lib/brain-bot/brain_bot.py brief"}}

    def scan(self, units):
        env = self.fake_server(units)
        out = self.bash(bk.OLD_BOTS_SH, env)
        probe = self.bash(bk.PROBE_SH, env)
        return env, out, probe

    def test_bridge_named_brain_bot_is_old_bot(self):
        env, out, probe = self.scan(self.bridge())
        self.assertEqual(bk.old_bot_units(out), ["brain-bot.service"])
        self.assertIn("OLD_BOTS=brain-bot.service", probe)
        self.assertIn("BOT_OURS=0", probe)
        info = bk.parse_old_bots(out)[0]
        self.assertEqual(info["user"], "brain")
        self.assertIn("claude-telegram-bot", info["exec"])
        # токен и владелец — из .env проекта (WorkingDirectory); наружу — только маска
        tok = self.bash(bk.OLD_SCAN + '\nbl_old_token brain-bot.service', env).strip()
        self.assertEqual(tok, BRIDGE_TOKEN)
        mask = self.bash(bk.OLD_SCAN + '\nbl_old_token brain-bot.service | bl_tok_mask', env).strip()
        self.assertEqual(mask, "77…45:•••")
        own = self.bash(bk.OLD_SCAN + '\nbl_old_owners brain-bot.service', env).split()
        self.assertEqual(own, ["123456789"])
        self.assertNotIn(BRIDGE_TOKEN, out + probe)

    def test_july_bot_with_environment_file(self):
        env, out, probe = self.scan(self.july())
        self.assertEqual(bk.old_bot_units(out), ["brain-bot.service"])
        self.assertEqual(self.bash(bk.OLD_SCAN + '\nbl_old_token brain-bot.service', env).strip(), JULY_TOKEN)
        self.assertEqual(self.bash(bk.OLD_SCAN + '\nbl_old_owners brain-bot.service', env).split(), ["987654321"])

    def test_our_brain_bot_is_not_old(self):
        env, out, probe = self.scan(self.ours())
        self.assertEqual(bk.old_bot_units(out), [])
        self.assertIn("OLD_BOTS=\n", probe)
        self.assertIn("BOT_OURS=1", probe)

    def test_symlinked_env_is_not_read(self):
        units = self.bridge()
        proj = self.tmp / "bridge"
        (proj / ".env").unlink()
        (self.tmp / "elsewhere.env").write_text("BOT_TOKEN=%s\n" % BRIDGE_TOKEN, encoding="utf-8")
        os.symlink(str(self.tmp / "elsewhere.env"), str(proj / ".env"))
        env = self.fake_server(units)
        self.assertEqual(self.bash(bk.OLD_SCAN + '\nbl_old_token brain-bot.service', env).strip(), "")

    def test_two_owners_counted(self):
        units = self.bridge()
        (self.tmp / "bridge" / ".env").write_text("TOKEN=%s\nALLOWED_USERS=111222333,444555666\n" % BRIDGE_TOKEN,
                                                  encoding="utf-8")
        env = self.fake_server(units)
        self.assertEqual(len(self.bash(bk.OLD_SCAN + '\nbl_old_owners brain-bot.service', env).split()), 2)


class InputRunner(FakeRunner):
    """Как FakeRunner, но правила смотрят и в stdin (серверные скрипты идут через bash -s)."""

    def __call__(self, argv, input=None, timeout=120, env=None, cwd=None):
        line = " ".join(str(a) for a in argv)
        body = (input or b"").decode("utf-8", "replace") if isinstance(input, (bytes, bytearray)) else ""
        self.calls.append({"argv": [str(a) for a in argv], "input": input, "line": line, "body": body})
        for needle, answer in self.rules:
            if needle in line or needle in body:
                return answer
        return self.default


class TestUpgradeFlow(KeysMixin if False else Base):
    def setUp(self):
        super().setUp()
        self.runner = InputRunner()
        self.patches.append(mock.patch.object(bk, "RUNNER", self.runner))
        self.patches[-1].start()
        self.ready_keys()

    def test_detect_sees_foreign_brain_bot_and_maps(self):
        self.access("SERVER_IP=10.20.30.40\n")
        probe = ("WHO=root\nNOW=%d\nNTP=yes\nBRAIN=1\nCLAUDE=1\nCLAUDE_BOT=1\nHARDENED=1\nLOCKDOWN=0\nHEARTBEAT=0\n"
                 "BOT=active\nBOT_OURS=0\nMEMFILES=3\nOLD_BOTS=brain-bot.service \n"
                 "OLDINFO=brain-bot.service|brain|/home/brain/bridge/venv/bin/claude-telegram-bot|/etc/systemd/system/brain-bot.service\n"
                 "OLDTOK=brain-bot.service|1|77…45:•••\nOLDOWN=brain-bot.service|1\nUFW=inactive\nF2B=none\n"
                 "SSHD_PW=open\nSSHD_ROOT=yes\nLEGACY_CRON=0\nTOKEN_CLAUDE=1\nTOKEN_BOT=1\n" % int(__import__("time").time()))
        (self.cfg / "sync_state.json").write_text('{"initialized": true, "target": "ssh:root@10.20.30.40:22"}')
        with mock.patch.object(bk, "local_schedule_present", lambda: True):
            self.runner.rules = [("bash -s", (0, probe.encode(), b""))]
            code, res, raw = self.call(["detect"])
        self.assertEqual(code, 0, res)
        self.assertEqual(res["next_step"], "bot")            # BOT=active, но чужой → шаг bot
        up = res["upgrade"]
        self.assertEqual(up["old_token"], "one")
        self.assertEqual(up["old_owner"], "one")
        self.assertEqual(up["ssh_password_login"], "open")
        self.assertEqual(up["old_bots"][0]["user"], "brain")
        self.assertIn("brain-bot.service", res["map"]["old_bot"])
        self.assertIn("токен перенесём", res["map"]["old_bot"])
        self.assertIn("открыт", res["map"]["ssh_password"])
        self.assertIn("Opus", res["map"]["bot_model"])
        self.assertIn("IT-команда", res["map"]["it_team"])
        self.assertIn("по твоему «да»", res["human"])
        self.assertNotIn("10.20.30.40", raw)

    def test_it_team_status(self):
        sk = self.tmp / "skills"
        (sk / "cto").mkdir(parents=True)
        (sk / "cto" / "SKILL.md").write_text("---\nname: cto\nauthor: ikigai\nkit_version: 2.3\n---\n", encoding="utf-8")
        (sk / "devops").mkdir()
        (sk / "devops" / "SKILL.md").write_text("---\nname: devops\ndescription: мой\n---\n", encoding="utf-8")
        st = bk.it_team_status(sk)
        self.assertEqual(st, {"cto": "kit", "devops": "own", "secops": "missing", "code-reviewer": "missing"})

    SCAN_ONE = b"UNITS=brain-bot.service\nCOUNT=1\nMASK=77\xe2\x80\xa645:\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2\nOWNERS=1\n"

    def test_put_token_bot_offers_migration_without_token_in_output(self):
        self.access("SERVER_IP=10.20.30.40\n")
        self.runner.rules = [("bl_old_token", (0, self.SCAN_ONE, b""))]
        code, res, raw = self.call(["put-token", "bot"])
        self.assertEqual(code, 3, res)
        self.assertEqual(res["token_mask"], "77…45:•••")
        self.assertIn("не покидает сервер", res["human"])
        self.assertIn("ALLOWED_USERS", res["human"])
        self.assertEqual([c for c in self.runner.calls if "__MODE__" in c["body"] or 'apply" = apply' in c["body"]], [])
        self.assertTrue(all('"scan" = apply' in c["body"] for c in self.runner.calls if "bl_old_token" in c["body"]))

    def test_put_token_bot_yes_migrates_and_owner_goes_to_server(self):
        self.access("SERVER_IP=10.20.30.40\n")
        applied = self.SCAN_ONE + "✅ перенесён\nMIGRATED=1\nOWNER=1\n".encode()
        self.runner.rules = [('"apply" = apply', (0, applied, b"")), ("bl_old_token", (0, self.SCAN_ONE, b""))]
        code, res, raw = self.call(["put-token", "bot", "--yes"])
        self.assertEqual(code, 0, res)
        self.assertTrue(res["owner_moved"])
        st = json.loads((self.cfg / "link_state.json").read_text())
        self.assertTrue(st["owner_on_server"])
        self.assertEqual(st["token_bot_source"], "old_bot")
        apply_body = [c["body"] for c in self.runner.calls if '"apply" = apply' in c["body"]][0]
        self.assertIn("brain-admin set-token bot", apply_body)
        self.assertIn('"1" = 1', apply_body)                      # владельца просим: USER_ID в файле нет
        # шаг bot теперь берёт владельца на сервере
        self.assertEqual(bk.owner_id({}, allow_server=True), "server")
        with self.assertRaises(bk.LinkExit):
            bk.owner_id({})

    def test_put_token_bot_many_tokens_falls_back(self):
        self.access("SERVER_IP=10.20.30.40\n")
        self.runner.rules = [("bl_old_token", (0, b"UNITS=a-bot.service b-bot.service\nCOUNT=2\nMASK=11\xe2\x80\xa622:\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2\nOWNERS=1\n", b""))]
        with mock.patch.object(bk.sys.stdin, "isatty", lambda: False):
            code, res, raw = self.call(["put-token", "bot"])
        self.assertEqual(code, 2, res)
        self.assertIn("несколько разных токенов", " ".join(res.get("warnings") or []))

    def test_access_file_token_wins_over_old_bot(self):
        self.access("SERVER_IP=10.20.30.40\nBOT_TOKEN=%s\n" % FAKE_BOT_TOKEN)
        self.runner.rules = [("set-token", (0, b"ok\n", b"")), ("bl_old_token", (0, self.SCAN_ONE, b""))]
        code, res, raw = self.call(["put-token", "bot"])
        self.assertEqual(code, 0, res)
        self.assertFalse(any("bl_old_token" in c["body"] for c in self.runner.calls))

    def test_bot_step_foreign_brain_bot_stop_point_then_backup(self):
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\n")
        old = ("OLD=brain-bot.service\nOLDINFO=brain-bot.service|brain|/home/brain/bridge/venv/bin/claude-telegram-bot|"
               "/etc/systemd/system/brain-bot.service\n").encode()
        self.runner.rules = [("old_bots all", (0, old, b""))]
        code, res, _ = self.call(["bot"])
        self.assertEqual(code, 3, res)
        self.assertIn("называется так же", res["human"])
        self.assertIn("claude-telegram-bot", res["human"])
        self.assertIn("/var/backups/brain-link", res["human"])
        self.runner.rules = [("old_bots all", (0, old, b"")),
                             ("tar xzf", (0, b"", b"")), ("BOT_TZ=", (0, "✅ ok\nOLD_BACKUP=brain-bot.service|/var/backups/brain-link/old-bot.x\n".encode(), b""))]
        code, res, _ = self.call(["bot", "--yes"])
        self.assertEqual(code, 0, res)
        body = [c["body"] for c in self.runner.calls if "BOT_TZ=" in c["body"]][0]
        self.assertIn("for s in brain-bot.service; do", body)
        # копия юнита и drop-in'ов — ДО установки наших юнитов, drop-in'ы чужого brain-bot переносятся целиком
        self.assertLess(body.index("old-bot.$s.$stamp"), body.index('for u in brain-bot.service brain-brief.service'))
        self.assertIn("mv /etc/systemd/system/brain-bot.service.d", body)
        self.assertEqual(res["old_bot_backups"], {"brain-bot.service": "/var/backups/brain-link/old-bot.x"})

    def test_bot_owner_from_server_when_migrated(self):
        self.access("SERVER_IP=10.20.30.40\n")
        bk.save_state(owner_on_server=True)
        self.runner.rules = [("old_bots all", (0, b"", b"")), ("tar xzf", (0, b"", b"")),
                             ("BOT_TZ=", (0, "✅ ok\n".encode(), b""))]
        code, res, _ = self.call(["bot"])
        self.assertEqual(code, 0, res)
        body = [c["body"] for c in self.runner.calls if "BOT_TZ=" in c["body"]][0]
        self.assertIn("OWNER_ID=server", body)
        self.assertIn(bk.OWNER_FILE, body)

    def test_bot_without_owner_anywhere_is_config(self):
        self.access("SERVER_IP=10.20.30.40\n")
        self.runner.rules = [("old_bots all", (0, b"", b""))]
        code, res, _ = self.call(["bot"])
        self.assertEqual(code, 4, res)
        self.assertIn("USER_ID", res["human"])

    def test_harden_without_user_id_goes_on(self):
        self.access("SERVER_IP=10.20.30.40\n")
        (self.home / ".ssh" / "id_ed25519.pub").write_text("ssh-ed25519 " + "A" * 68 + " a@b\n", encoding="utf-8")
        (self.home / ".ssh" / "brain_sync_ed25519.pub").write_text("ssh-ed25519 " + "B" * 68 + " s@b\n", encoding="utf-8")
        self.runner.rules = [("harden.sh", (0, "✅ ok\n".encode(), b"")), ("tar xzf", (0, b"", b""))]
        code, res, _ = self.call(["harden"])
        self.assertEqual(code, 0, res)
        body = [c["body"] for c in self.runner.calls if "harden.sh" in c["body"]][0]
        self.assertIn("OWNER_ID=none", body)
        self.assertIn("USER_ID", " ".join(res["warnings"]))


@unittest.skipUnless(shutil.which("bash") and os.name != "nt", "lockdown исполняется на Linux-сервере")
class TestLockdownEffectiveSshd(UpgradeShellBase):
    """kit 2.3 (п.4): lockdown проверяет ДЕЙСТВУЮЩИЕ настройки sshd -T, а не только sshd -t."""

    def eff(self, sshd_body):
        fake = self.tmp / "bin"
        fake.mkdir(exist_ok=True)
        (fake / "sshd").write_text("#!/bin/sh\n" + sshd_body, encoding="utf-8")
        os.chmod(str(fake / "sshd"), 0o755)
        env = dict(os.environ, PATH=str(fake) + os.pathsep + os.environ.get("PATH", ""))
        script = bk.LOCKDOWN_SH.replace("\nbrain_lockdown\n", "\n") + "\neff_bad\n"
        self.assertNotEqual(script, bk.LOCKDOWN_SH + "\neff_bad\n")
        return self.bash(script, env)

    def test_cloudimg_password_yes_detected(self):
        out = self.eff("printf 'port 22\\npasswordauthentication yes\\npermitrootlogin no\\nkbdinteractiveauthentication no\\n'\n")
        self.assertIn("passwordauthentication=yes", out)

    def test_root_prohibit_password_detected(self):
        out = self.eff("printf 'passwordauthentication no\\npermitrootlogin prohibit-password\\n'\n")
        self.assertIn("permitrootlogin=prohibit-password", out)

    def test_all_closed_is_clean(self):
        out = self.eff("printf 'PasswordAuthentication no\\nPermitRootLogin no\\nKbdInteractiveAuthentication no\\n'\n")
        self.assertEqual(out.strip(), "")

    def test_match_for_root_seen_via_dash_C(self):
        # Match User root → PasswordAuthentication yes виден только в sshd -T -C user=root
        body = ('case "$*" in *user=root*) printf \'passwordauthentication yes\\npermitrootlogin no\\n\' ;;'
                ' *) printf \'passwordauthentication no\\npermitrootlogin no\\n\' ;; esac\n')
        self.assertIn("passwordauthentication=yes", self.eff(body))

    def test_old_sshd_without_dash_C_falls_back(self):
        body = ('case "$*" in *-C*) exit 1 ;; *) printf \'passwordauthentication yes\\n\' ;; esac\n')
        self.assertIn("passwordauthentication=yes", self.eff(body))

    def test_drop_in_name_sorts_before_cloud_images(self):
        # «первое значение побеждает»: наш файл должен идти раньше 50-cloud-init.conf и 60-cloudimg-settings.conf
        for other in ("50-cloud-init.conf", "60-cloudimg-settings.conf", "10-brain-lab.conf", "01-x.conf"):
            self.assertLess("00-brain.conf", other)
        self.assertIn("/etc/ssh/sshd_config.d/00-brain.conf", bk.LOCKDOWN_SH)
        self.assertIn("Include /etc/ssh/sshd_config.d/*.conf", bk.LOCKDOWN_SH)
        self.assertIn("ROLLEDBACK", bk.LOCKDOWN_SH)


class TestServerChanged(Base):
    def test_detect_sees_new_server(self):
        self.access("SERVER_IP=10.20.30.99\nUSER_ID=123456789\n")
        (self.cfg / "sync_state.json").write_text(json.dumps(
            {"initialized": True, "target": "ssh:root@10.20.30.40:22"}), encoding="utf-8")
        self.ready_keys()
        probe = ("WHO=root\nNOW=%d\nNTP=yes\nBRAIN=1\nCLAUDE=1\nHARDENED=1\nLOCKDOWN=0\nHEARTBEAT=0\n"
                 "BOT=active\nMEMFILES=0\nOLD_BOTS=\nLEGACY_CRON=0\nTOKEN_CLAUDE=1\nTOKEN_BOT=1\n"
                 % int(__import__("time").time()))
        self.runner.rules = [("bash -s", (0, probe.encode(), b""))]
        code, res, raw = self.call(["detect"])
        self.assertEqual(code, 0, res)
        self.assertEqual(res["branch"], "D")
        self.assertEqual(res["next_step"], "init")
        self.assertTrue(res["server_changed"])
        self.assertIn("второй", " ".join(res["warnings"]).lower())
        self.assertNotIn("10.20.30.99", raw)

    def test_same_server_is_not_changed(self):
        self.assertEqual(bk.server_changed({"initialized": True, "target": "ssh:root@1.2.3.4:22"},
                                           {"SERVER_IP": "1.2.3.4", "SERVER_USER": "root", "SERVER_PORT": "22"}), "")
        self.assertEqual(bk.server_changed({"initialized": True, "target": "local:/x"}, {"SERVER_IP": "1.2.3.4"}), "")


class TestTarSkipsSymlinks(Base):
    @unittest.skipIf(os.name == "nt", "симлинки на Windows требуют прав")
    def test_symlink_not_packed(self):
        import tarfile
        srv = self.tmp / "server"
        (srv / "systemd").mkdir(parents=True)
        (srv / "harden.sh").write_text("echo ok\n", encoding="utf-8")
        (srv / "systemd" / "a.service").write_text("[Unit]\n", encoding="utf-8")
        os.symlink("/etc/passwd", str(srv / "evil"))
        os.symlink(str(srv / "systemd"), str(srv / "linkdir"))
        with mock.patch.object(bk, "SERVER_DIR", srv):
            data = bk.tar_server_dir()
        names = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz").getnames()
        self.assertIn("harden.sh", names)
        self.assertIn("systemd/a.service", names)
        self.assertFalse(any(n.startswith(("evil", "linkdir")) for n in names), names)

    def test_copy_kit_runs_as_brain(self):
        self.assertIn("runuser -u brain", bk.COPY_KIT_SH)
        self.assertNotIn("install -d", bk.COPY_KIT_SH)


class TestVerifyCleansProbe(Base):
    def test_probe_file_removed_after_check(self):
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\n")
        self.ready_keys()
        inbox = self.ws / "memory" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "n.md").write_text("запомни тест связки", encoding="utf-8")
        skills = self.tmp / "skills"
        (skills / "demo").mkdir(parents=True, exist_ok=True)
        (skills / "demo" / "SKILL.md").write_text("x", encoding="utf-8")
        self.runner.rules = [("grep -q verify-", (0, b"SYNCED=1\n", b"")),
                             ("bash -s", (0, b"NOW=0\nNTP=yes\nPRIVATE=\n", b""))]
        code, res, _ = self.call(["verify", "--root", str(self.ws), "--skills-dir", str(skills), "--wait", "0"])
        self.assertEqual(res["checks"]["а"]["status"], "ok", res)
        self.assertFalse((self.ws / "memory" / bk.VERIFY_FILE).exists())


class TestEncoding(Base):
    """Windows-консоль в cp1251: ✅ 🟡 ↑↓ не должны ронять процесс, stdout — JSON в UTF-8."""

    def _run(self, code_or_args, env_extra):
        import subprocess
        env = dict(os.environ, PYTHONIOENCODING="cp1251", **env_extra)
        env.pop("PYTHONUTF8", None)
        argv = [sys.executable] + code_or_args
        r = subprocess.run(argv, capture_output=True, env=env, timeout=60)
        return r.returncode, r.stdout, r.stderr

    def test_say_and_finish_survive_cp1251(self):
        code = ("import sys; sys.path.insert(0, %r); import brain_link as b; b.utf8_stdio(); "
                "b.say('🟡 жду ↑↓ ✅'); b.finish(0, '✅ готово ↑ 🟡 ↓ ❌')" % str(KIT / "scripts"))
        rc, out, err = self._run(["-c", code], {})
        self.assertEqual(rc, 0, err.decode("utf-8", "replace"))
        obj = json.loads(out.decode("utf-8"))
        self.assertEqual(obj["human"], "✅ готово ↑ 🟡 ↓ ❌")
        self.assertIn("🟡 жду ↑↓ ✅", err.decode("utf-8"))

    def test_cli_json_under_cp1251(self):
        rc, out, err = self._run([str(KIT / "scripts" / "brain_link.py"), "fly"], {})
        self.assertEqual(rc, 4, err.decode("utf-8", "replace"))
        self.assertIn("не понял", json.loads(out.decode("utf-8"))["human"])

    def test_emit_none_and_textio(self):
        bk.emit(None, "✅")                                      # pythonw: sys.stdout is None — молча
        raw = io.BytesIO()
        w = io.TextIOWrapper(raw, encoding="cp1251", errors="strict")
        bk.emit(w, "✅ привет ↑")
        self.assertEqual(raw.getvalue().decode("utf-8"), "✅ привет ↑")

    def test_run_sync_env_utf8(self):
        seen = {}

        def runner(argv, input=None, timeout=120, env=None, cwd=None):
            seen["env"] = env
            return 0, '{"ok": true, "human": "✅ ок"}\n'.encode("utf-8"), b""
        with mock.patch.object(bk, "RUNNER", runner):
            code, res = bk.run_sync(__import__("argparse").Namespace(root=None, skills_dir=None, transport=None),
                                    "status")
        self.assertEqual(code, 0)
        self.assertEqual(res["human"], "✅ ок")
        self.assertEqual(seen["env"]["PYTHONUTF8"], "1")
        self.assertEqual(seen["env"]["PYTHONIOENCODING"], "utf-8")



# ---------------------------------------------------------------- kit 2.1: report, BOT_TZ, verify + самопроверка
PUB = "ssh-ed25519 " + "A" * 68


class KeysMixin:
    def full_keys(self):
        self.ready_keys()
        (self.home / ".ssh" / "id_ed25519.pub").write_text(PUB + " admin\n", encoding="utf-8")
        (self.home / ".ssh" / "brain_sync_ed25519").write_text("fake", encoding="utf-8")
        (self.home / ".ssh" / "brain_sync_ed25519.pub").write_text("ssh-ed25519 " + "B" * 68 + " sync\n",
                                                                   encoding="utf-8")


class TestReport(KeysMixin, Base):
    def test_report_has_no_secrets(self):
        ip, uid = "10.20.30.40", "123456789"
        other_ip = "203.0.113.77"
        self.access("SERVER_IP=%s\nUSER_ID=%s\nBOT_TOKEN=%s\nPASSWORD=%s\nCLAUDE_TOKEN=%s\n"
                    % (ip, uid, FAKE_BOT_TOKEN, FAKE_PW, FAKE_CLAUDE_TOKEN))
        self.full_keys()
        logs = self.cfg / "logs"
        logs.mkdir()
        foreign = "sk-" + "ant-oat01-" + "Z" * 30
        (logs / "sync.log").write_text(
            "\n".join(["старт %s ssh brain@%s" % (str(self.home), ip),
                       "токен %s и %s, пароль password=%s" % (FAKE_CLAUDE_TOKEN, foreign, FAKE_PW),
                       "бот %s user %s, сосед %s, локально 127.0.0.1 и 169.254.169.254" % (
                           FAKE_BOT_TOKEN, uid, other_ip),
                       "в 12:34:56 всё ок, ::1 тоже"]), encoding="utf-8")
        (self.cfg / "sync_status.json").write_text(json.dumps({"last_error": "ssh %s: timeout" % ip}),
                                                   encoding="utf-8")
        server_out = ("=== brain-admin logs 200\nINFO claude rc=1 token=%s from %s CANARY-%s\n"
                      "ufw: active\nCurrently banned: 1  Banned IP list: 198.51.100.9\n"
                      % (FAKE_BOT_TOKEN, ip, "f" * 24))
        self.runner.rules = [("bash -s", (0, server_out.encode(), b"")),
                             ("detect", (0, json.dumps({"ok": True, "server": {"IP": ip}}).encode(), b""))]
        code, res, raw = self.call(["report"])
        self.assertEqual(code, 0, res)
        path = Path(res["path"])
        self.assertTrue(path.name.startswith("brain-link-report-"))
        self.assertEqual(path.parent, self.home)
        text = path.read_text(encoding="utf-8")
        for secret in (FAKE_BOT_TOKEN, FAKE_PW, FAKE_CLAUDE_TOKEN, foreign, ip, other_ip, "198.51.100.9",
                       uid, str(self.home), "f" * 24):
            self.assertNotIn(secret, text, secret)
            if secret != str(self.home):          # поле path в JSON — путь к самому отчёту на своём компьютере
                self.assertNotIn(secret, raw, secret)
        self.assertIn("127.0.0.1", text)
        self.assertIn("169.254.169.254", text)
        self.assertIn("12:34:56", text)
        self.assertIn("12…89", text)                       # USER_ID частично
        self.assertIn("ufw: active", text)
        self.assertIn("brain-admin logs 200", text)

    def test_report_file_private_from_creation(self):
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\n")
        if os.name == "nt":
            self.skipTest("права POSIX")
        old = os.umask(0)
        try:
            with mock.patch.object(bk.os, "chmod", lambda *a, **k: None):   # без chmod «после» — всё равно 0600
                code, res, _ = self.call(["report"])
        finally:
            os.umask(old)
        self.assertEqual(code, 0, res)
        self.assertEqual(os.stat(res["path"]).st_mode & 0o777, 0o600)

    def test_mask_windows_json_paths_tokens_and_strangers(self):
        win = "C:\\Users\\Иван"
        homes = [win, win.replace("\\", "/"), win.replace("\\", "\\\\")]
        text = json.dumps({"path": win + "\\brain\\memory"}) + " bot" + FAKE_BOT_TOKEN + \
            " ignored update kind=message from user_id=999888777 chat=-1001234567890"
        t = bk.mask_report(text, homes=homes)
        self.assertNotIn("Иван", t)
        self.assertNotIn(FAKE_BOT_TOKEN.split(":")[1], t)       # токен прилип к слову — всё равно скрыт
        self.assertNotIn("999888777", t)
        self.assertIn("user_id=99…77", t)
        self.assertNotIn("1001234567890", t)

    def test_cmd_report_adds_double_backslash_homes(self):
        src = (KIT / "scripts" / "brain_link.py").read_text(encoding="utf-8")
        body = src[src.index("def cmd_report("):]
        self.assertIn('h.replace("\\\\", "\\\\\\\\")', body)
        self.assertIn("write_private(dest", body)

    def test_mask_report_unit(self):
        t = bk.mask_report("a sk-" + "ant-oat01-abcdefghijkl b 8.8.8.8 c 2001:db8::1 d version 1.2.300.4",
                           homes=["/Users/x"])
        self.assertNotIn("abcdefghijkl", t)
        self.assertNotIn("8.8.8.8", t)
        self.assertNotIn("2001:db8::1", t)
        self.assertIn("1.2.300.4", t)


class TestBotTz(KeysMixin, Base):
    def test_default_and_from_access_file(self):
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\n")
        self.assertEqual(bk.bot_tz(), "Europe/Moscow")
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\nBOT_TZ=Asia/Almaty\n")
        self.assertEqual(bk.bot_tz(), "Asia/Almaty")

    def test_harden_passes_bot_tz(self):
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\nBOT_TZ=Asia/Almaty\n")
        self.full_keys()
        self.runner.default = (0, "✅ ок\n".encode(), b"")
        code, res, _ = self.call(["harden"])
        self.assertEqual(code, 0, res)
        script = [c for c in self.runner.calls if c["input"] and b"harden.sh" in c["input"]][0]["input"].decode()
        self.assertIn("BOT_TZ=Asia/Almaty bash ./harden.sh", script)

    def test_bad_tz_is_config_error(self):
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\nBOT_TZ=Europe/Moscow;id\n")
        self.full_keys()
        code, res, _ = self.call(["harden"])
        self.assertEqual(code, 4)
        self.assertIn("BOT_TZ", res["human"])

    def test_bot_script_substitutes_tz_and_backups_aside(self):
        sh = bk.BOT_ROOT_SH
        self.assertIn('s#Europe/Moscow#$BOT_TZ#g', sh)
        self.assertIn("BAK=/var/backups/brain-link", sh)
        self.assertNotIn('"$2.bak.', sh)
        self.assertIn("brain-admin canary-init", sh)
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\nBOT_TZ=America/New_York\n")
        self.full_keys()
        self.runner.rules = [("old_bots all", (0, b"", b""))]
        self.runner.default = (0, "✅ ок\n".encode(), b"")
        code, res, _ = self.call(["bot"])
        self.assertEqual(code, 0, res)
        script = [c for c in self.runner.calls if c["input"] and b"BOT_TZ=" in c["input"]][0]["input"].decode()
        self.assertIn("BOT_TZ=America/New_York", script)


class TestVerifySelfcheck(KeysMixin, Base):
    def _verify(self, selfcheck_out, extra=None):
        import hashlib
        import time as _t
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\n")
        self.ready_keys()
        inbox = self.ws / "memory" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "n.md").write_text("запомни тест связки", encoding="utf-8")
        skills = self.tmp / "skills"
        (skills / "demo").mkdir(parents=True, exist_ok=True)
        (skills / "demo" / "SKILL.md").write_text("x", encoding="utf-8")
        sha = hashlib.sha256(b"x").hexdigest()
        kv = {"NOW": str(int(_t.time())), "NTP": "yes", "PRIVATE": "", "SKILL_SHA": sha, "BOT_USER": "brainbot",
              "BOT_ACTIVE": "active", "SELFTEST": "ok", "CRED_READ": "no", "CRED_READ2": "no", "CRED_RUN": "no",
              "CRED_RUN2": "no", "STATE_READ": "no", "SUDO_LINES": "0", "LOG_TOKENS": "0"}
        kv.update(extra or {})
        vs = "".join("%s=%s\n" % i for i in kv.items())
        self.runner.rules = [("grep -q verify-", (0, b"SYNCED=1\n", b"")),
                             ("selfcheck-security", selfcheck_out),
                             ("bash -s", (0, vs.encode(), b""))]
        return self.call(["verify", "--root", str(self.ws), "--skills-dir", str(skills), "--wait", "0"])

    def _state(self):
        return json.loads((self.cfg / "link_state.json").read_text(encoding="utf-8"))

    PASS_OUT = (0, "✅ утечки нет\nSELFCHECK=pass\nSELFCHECK_CACHED=0\nSELFCHECK_SANDBOX=systemd\n".encode(), b"")

    def test_rt11_brain_reads_unit_credentials_is_red(self):
        # RT-11: юнит под brain → /run/credentials/brain-bot.service/* читает любой процесс brain
        code, res, _ = self._verify(self.PASS_OUT, {"CRED_RUN": "yes"})
        self.assertNotEqual(code, 0)
        self.assertEqual(res["checks"]["ж"]["status"], "fail")
        self.assertIn("/run/credentials/brain-bot.service: False", res["checks"]["ж"]["detail"])

    def test_rt11_bot_under_brain_is_red_with_migration_hint(self):
        code, res, _ = self._verify(self.PASS_OUT, {"BOT_USER": "brain"})
        self.assertNotEqual(code, 0)
        self.assertEqual(res["checks"]["е"]["status"], "fail")
        self.assertEqual(res["checks"]["ж"]["status"], "fail")
        self.assertIn("повтори шаг bot до lockdown", res["checks"]["е"]["detail"])

    def test_rt11_state_readable_or_unknown_is_red(self):
        for extra in ({"STATE_READ": "yes"}, {"CRED_RUN2": ""}, {"STATE_READ": ""}):
            code, res, _ = self._verify(self.PASS_OUT, extra)
            self.assertEqual(res["checks"]["ж"]["status"], "fail", extra)   # нет ответа ≠ «закрыто»

    def test_verify_sh_checks_unit_credentials_as_brain(self):
        self.assertIn("/run/credentials/brain-bot.service", bk.VERIFY_SH)
        self.assertIn('AS="runuser -u brain --"', bk.VERIFY_SH)
        self.assertIn("ls /var/lib/brain-bot", bk.VERIFY_SH)
        self.assertIn("brain-admin bot-user", bk.BOT_ROOT_SH)
        self.assertLess(bk.BOT_ROOT_SH.index("brain-admin bot-user"), bk.BOT_ROOT_SH.index("systemctl restart brain-bot"))
        self.assertEqual(bk.BOT_CLAUDE_CONFIG, "/var/lib/brain-bot/claude-config")
        self.assertIn("bot-state", bk.REPORT_SH)

    def test_pass_is_green(self):
        out = "✅ утечки нет\nSELFCHECK=pass\nSELFCHECK_CACHED=0\nSELFCHECK_SANDBOX=systemd\n"
        code, res, _ = self._verify((0, out.encode(), b""))
        self.assertEqual(code, 0, {k: (v["status"], v["detail"]) for k, v in res.get("checks", {}).items()})
        self.assertEqual(res["checks"]["и"]["status"], "ok")
        self.assertEqual(self._state()["selfcheck"], "pass")

    def test_pass_outside_unit_sandbox_is_unverified(self):
        for sandbox in ("fallback", None):
            out = "✅ утечки нет\nSELFCHECK=pass\nSELFCHECK_CACHED=0\n" + (
                "SELFCHECK_SANDBOX=%s\n" % sandbox if sandbox else "")
            code, res, _ = self._verify((0, out.encode(), b""))
            self.assertEqual(code, 2, res)
            self.assertEqual(res["checks"]["и"]["status"], "warn")
            self.assertEqual(self._state()["selfcheck"], "unverified")
            self.assertIn("--accept-unverified", res["human"])

    def test_fail_blocks(self):
        out = "❌ приманка в ~/.config — в ответе модели есть приманка или токен\nSELFCHECK=fail\n"
        code, res, _ = self._verify((1, out.encode(), b""))
        self.assertEqual(code, 1)
        self.assertEqual(res["checks"]["и"]["status"], "fail")
        self.assertFalse(self._state()["verify_green"])

    def test_unverified_needs_explicit_flag_for_lockdown(self):
        out = "🟡 не проверено: лимит подписки (429)\nSELFCHECK=unverified\n"
        code, res, _ = self._verify((3, out.encode(), b""))
        self.assertEqual(code, 2, res)
        self.assertEqual(res["checks"]["и"]["status"], "warn")
        self.assertIn("--accept-unverified", res["human"])
        self.assertEqual(self._state()["selfcheck"], "unverified")
        self.runner.rules, self.runner.calls = [], []
        code, res, _ = self.call(["lockdown", "--confirm", "--confirm-again"])
        self.assertEqual(code, 2)
        self.assertIn("--accept-unverified", res["human"])
        self.assertEqual(self.runner.calls, [])           # на сервер даже не ходили

    def test_lockdown_requires_pass_when_selfcheck_missing(self):
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\n")
        self.ready_keys()
        (self.cfg / "link_state.json").write_text('{"verify_green": true}', encoding="utf-8")
        code, res, _ = self.call(["lockdown", "--confirm", "--confirm-again", "--accept-unverified"])
        self.assertEqual(code, 1)
        self.assertIn("PASS", res["human"])


class TestCapabilitiesFlagsByExec(Base):
    """Флаги claude — исполнением (`claude <флаг> [значение] --version` → 0), одна логика в трёх местах."""

    def test_same_block_in_brain_admin_and_caps_sh(self):
        admin = (KIT / "server" / "brain-admin").read_text(encoding="utf-8")

        def block(t):
            return t[t.index("# >>> claude-flags"):t.index("# <<< claude-flags")]
        self.assertEqual(block(admin), block(bk.CAPS_SH))
        b = block(admin)
        self.assertIn("--version", b)
        self.assertIn("--allowedTools,--allowed-tools", b)
        self.assertIn("--brain-link-no-such-flag", b)
        self.assertIn("runuser -u brain", b)
        upd = admin[admin.index("  update-claude)"):admin.index("  remove-private)")]
        self.assertNotIn("grep -q --", upd)               # не по --help
        self.assertIn("cl_caps", upd)

    def test_help_only_is_reported_and_none_means_unknown(self):
        caps, warns = bk.server_capabilities({"CLAUDE_VER": "2.1", "CAP_METHOD": "none", "SYSTEMD_VER": "255",
                                              "CGROUP_UNIFIED": "1"})
        self.assertEqual(caps["claude_flags"], {})
        self.assertFalse(any("update-claude" in w for w in warns))   # неизвестно ≠ «флагов нет»
        caps, warns = bk.server_capabilities({"CAP_METHOD": "exec", "CAP_TOOLS": "1", "CAP_SETTING_SOURCES": "1",
                                              "CAP_ALLOWEDTOOLS": "1", "CAP_DISALLOWEDTOOLS": "1",
                                              "CAP_NO_SESSION_PERSISTENCE": "0", "SYSTEMD_VER": "255"})
        self.assertEqual(caps["claude_flags_method"], "exec")
        self.assertFalse(caps["claude_flags"]["--no-session-persistence"])
        self.assertFalse(any("update-claude" in w for w in warns))   # необязательный флаг — не повод

    @unittest.skipUnless(os.name != "nt" and shutil.which("bash") and shutil.which("timeout"),
                         "shell-блок исполняется на Linux-сервере (нужны bash и timeout)")
    def test_shell_block_runs_against_fake_claude(self):
        import subprocess
        fake = self.tmp / "claude"
        fake.write_text(
            "#!/bin/sh\n"
            "for a in \"$@\"; do case \"$a\" in --tools|--setting-sources|--allowed-tools|--disallowedTools|"
            "--version|--help|''|Read|Bash) ;; *) echo \"unknown option $a\" >&2; exit 1 ;; esac; done\n"
            "case \" $* \" in *' --help '*) echo 'Usage: --allowedTools --no-session-persistence';; "
            "*) echo '9.9.9 (Claude Code)';; esac\n", encoding="utf-8")
        fake.chmod(0o755)
        sh = bk.CAPS_SH[bk.CAPS_SH.index("# >>> claude-flags"):bk.CAPS_SH.index("# <<< claude-flags")]
        self.assertNotIn("/home/brain/.local/bin/claude", sh)   # RT-11b: только root-копия бота
        sh = sh.replace("/usr/local/lib/brain-bot/claude/bin/claude", str(fake)) + "\ncl_caps\n"
        sh = sh.replace('[ "$(id -u)" = 0 ]', "false")
        out = subprocess.run(["bash", "-c", sh], capture_output=True, text=True, timeout=60).stdout
        self.assertIn("CAP_METHOD=exec", out)
        for k in ("TOOLS", "SETTING_SOURCES", "ALLOWEDTOOLS", "DISALLOWEDTOOLS"):
            self.assertIn("CAP_%s=1" % k, out)               # --allowed-tools принят во втором написании
        self.assertIn("CAP_NO_SESSION_PERSISTENCE=0", out)   # в help есть, исполнением — нет
        self.assertIn("CAP_STRICT_MCP_CONFIG=0", out)


class TestSelfcheckSandboxAndBudget(Base):
    def test_brain_admin_selfcheck_fallback_rules_and_trap(self):
        admin = (KIT / "server" / "brain-admin").read_text(encoding="utf-8")
        block = admin[admin.index("  selfcheck-security)"):admin.index("  clear-canary-hit)")]
        self.assertIn("systemctl cat brain-bot.service", block)
        self.assertIn("DropInPaths", block)
        self.assertIn("Unknown assignment|Failed to start transient", block)
        died = block[block.index("Unknown assignment|Failed"):block.index('if [ "$mode" = fallback ]')]
        self.assertIn("SELFCHECK=unverified", died)        # стартовала и умерла — не проверено, без запасного
        lines = block.splitlines()
        i = [n for n, l in enumerate(lines) if "mktemp -d /run/brain-selfcheck" in l][0]
        self.assertRegex(lines[i + 1].strip(), r"""^trap 'rm -rf "\$CD"[^']*' EXIT HUP INT TERM""")
        rt = int(__import__("re").search(r"RuntimeMaxSec=(\d+)", block).group(1))
        sys.path.insert(0, str(KIT / "server"))
        import brain_bot as bb
        self.assertLess(bb.SELFCHECK_BUDGET, rt)
        self.assertLess(rt, bk.SELFCHECK_TIMEOUT)

    def test_brain_admin_clear_canary_hit(self):
        admin = (KIT / "server" / "brain-admin").read_text(encoding="utf-8")
        block = admin[admin.index("  clear-canary-hit)"):admin.index("  update-claude)")]
        self.assertIn("read -r -t 60", block)
        self.assertIn("runuser -u brain", block)
        self.assertIn("brain_bot.py\" clear-canary-hit", block)
        self.assertIn("clear-canary-hit", admin[:admin.index("USAGE\n}")])


class TestCapabilities(Base):
    def test_server_caps_warn_old_claude_and_container(self):
        caps, warns = bk.server_capabilities({"CLAUDE_VER": "1.0.0", "CAP_TOOLS": "0", "CAP_SETTING_SOURCES": "1",
                                              "CAP_ALLOWEDTOOLS": "1", "CAP_DISALLOWEDTOOLS": "1",
                                              "SYSTEMD_VER": "255", "VIRT": "lxc", "CONTAINER": "lxc",
                                              "CGROUP_UNIFIED": "1", "UFW_BIN": "1"})
        self.assertFalse(caps["claude_flags"]["--tools"])
        self.assertTrue(caps["container"])
        self.assertFalse(caps["ip_address_deny"])
        self.assertTrue(any("update-claude" in w for w in warns))
        self.assertTrue(any("контейнер" in w for w in warns))

    def test_detect_reports_capabilities(self):
        self.access("SERVER_IP=10.20.30.40\nUSER_ID=123456789\n")
        self.ready_keys()
        probe = ("WHO=root\nNOW=%d\nNTP=yes\nBRAIN=1\nCLAUDE=1\nHARDENED=1\nCLAUDE_VER=2.1.200\nCAP_TOOLS=1\n"
                 "CAP_SETTING_SOURCES=1\nCAP_ALLOWEDTOOLS=1\nCAP_DISALLOWEDTOOLS=1\nSYSTEMD_VER=255\nVIRT=kvm\n"
                 "CONTAINER=none\nCGROUP_UNIFIED=1\n" % int(__import__("time").time()))
        self.runner.rules = [("bash -s", (0, probe.encode(), b""))]
        code, res, _ = self.call(["detect"])
        self.assertEqual(code, 0, res)
        self.assertEqual(res["capabilities"]["server"]["claude_version"], "2.1.200")
        self.assertTrue(res["capabilities"]["server"]["ip_address_deny"])
        self.assertEqual(res["capabilities"]["local"]["os"], "mac")
        self.assertIn("CAP_METHOD=", bk.PROBE_SH)
        self.assertIn("systemd-detect-virt", bk.PROBE_SH)
        self.assertIn("runuser -u brain", bk.CAPS_SH)        # claude root не запускает


class TestLabTransport(Base):
    def test_mac_plist_gets_transport_env_and_arg(self):
        self.runner.rules = [("launchctl", (0, b"", b""))]
        with mock.patch.dict(os.environ, {"BRAIN_SYNC_TRANSPORT": "local:/tmp/lab srv"}):
            code, res, _ = self.call(["schedule", "--wait", "0"])
        dest = self.home / "Library" / "LaunchAgents" / "com.ikigai.brain-sync.plist"
        data = plistlib.loads(dest.read_bytes())
        self.assertEqual(data["EnvironmentVariables"]["BRAIN_SYNC_TRANSPORT"], "local:/tmp/lab srv")
        self.assertEqual(data["ProgramArguments"][-2:], ["--transport", "local:/tmp/lab srv"])
        self.assertEqual(res["lab_transport"], "local:/tmp/lab srv")

    def test_bad_transport_is_config(self):
        with mock.patch.dict(os.environ, {"BRAIN_SYNC_TRANSPORT": "ftp://x"}):
            code, res, _ = self.call(["schedule", "--wait", "0"])
        self.assertEqual(code, 4)

    def test_no_transport_plist_unchanged(self):
        self.runner.rules = [("launchctl", (0, b"", b""))]
        os.environ.pop("BRAIN_SYNC_TRANSPORT", None)
        self.call(["schedule", "--wait", "0"])
        data = plistlib.loads((self.home / "Library" / "LaunchAgents" / "com.ikigai.brain-sync.plist").read_bytes())
        self.assertNotIn("BRAIN_SYNC_TRANSPORT", data["EnvironmentVariables"])
        self.assertNotIn("--transport", data["ProgramArguments"])


class TestLabTransportWindows(Base):
    os_name = "windows"

    def test_windows_task_gets_transport(self):
        self.runner.rules = [("schtasks /Query", (1, b"", b"")),
                             ("-ExecutionPolicy", (0, "Ikigai brain-sync | ok".encode(), b""))]
        with mock.patch.dict(os.environ, {"BRAIN_SYNC_TRANSPORT": "local:C:\\lab"}):
            self.call(["schedule", "--wait", "0"])
        call = [c for c in self.runner.calls if "-ExecutionPolicy" in c["line"]][0]["argv"]
        self.assertEqual(call[call.index("-Transport") + 1], "local:C:\\lab")
        ps1 = bk.render_ps1().decode("utf-8-sig")
        self.assertIn("[string]$Transport", ps1)
        self.assertIn("--transport", ps1)


if __name__ == "__main__":
    unittest.main()


class TestDistAndKitChecks(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(KIT.parent / "tools"))

    def test_ci_and_tests_not_published_anywhere(self):
        import build_dist
        for p in ("brain-link/ci/fake_claude.py", "brain-link/ci/README.md", "brain-link/tests/test_bot.py"):
            self.assertTrue(build_dist.is_excluded(p), p)           # ни витрина, ни пак
        self.assertFalse(build_dist.is_excluded("brain-link/server/brain_bot.py"))
        files = ["brain-link/SKILL.md", "brain-link/ci/x.py", "brain-link/tests/t.py"]
        site = [f for f in files if not build_dist.is_excluded(f)]
        self.assertEqual(site, ["brain-link/SKILL.md"])

    def test_ps1_without_bom_is_error(self):
        import check_kit
        tmp = Path(tempfile.mkdtemp(prefix="kitbom-"))
        try:
            (tmp / "a.ps1").write_bytes("Write-Host 'привет'".encode("utf-8"))
            (tmp / "b.ps1").write_bytes(b"\xef\xbb\xbf" + "Write-Host 'привет'".encode("utf-8"))
            rep = check_kit.Report()
            check_kit.check_ps1_bom(rep, str(tmp), ["a.ps1", "b.ps1"])
            self.assertEqual([m for _, m in rep.errors if "a.ps1" in m] != [], True)
            self.assertFalse(any("b.ps1" in m for _, m in rep.errors))
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
