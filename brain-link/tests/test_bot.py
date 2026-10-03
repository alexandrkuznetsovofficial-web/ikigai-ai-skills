"""Тесты brain_bot.py (kit 2.1) — без сети: Telegram и `claude -p` подменены заглушками.

Запуск: python3 -m unittest brain-link/tests/test_bot.py -v
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
import brain_bot as bb  # noqa: E402

OWNER = 111222333
STRANGER = 999888777
BOT_TOKEN = "123456789:" + "A" * 35
# Фейковые секреты собираются во время выполнения: в исходнике нет литералов (гейт check_kit).
ANT = "sk-" + "ant-"
CLAUDE_TOKEN = ANT + "oat01-" + "x" * 40
MEMORY_MARKER = "MEMORY_MARKER_7f3a"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class FakeApi:
    def __init__(self):
        self.calls = []

    def call(self, method, params=None, timeout=60):
        self.calls.append((method, params or {}))
        if method == "getFile":
            return {"file_path": "voice/x.oga", "file_size": 1000}
        return {}

    def sent(self):
        return [p["text"] for m, p in self.calls if m == "sendMessage"]


class FakeClaude:
    def __init__(self, out="Ответ модели", rc=0, err=""):
        self.out, self.rc, self.err, self.calls = out, rc, err, []

    def __call__(self, args, stdin_text, env, cwd, timeout):
        self.calls.append({"args": args, "prompt": stdin_text, "env": env, "cwd": cwd, "timeout": timeout})
        return self.rc, self.out, self.err


def upd(text=None, uid=OWNER, chat=None, uid_key="message", **extra):
    msg = {"message_id": 1, "from": {"id": uid}, "chat": {"id": chat if chat is not None else uid}}
    if text is not None:
        msg["text"] = text
    msg.update(extra)
    return {"update_id": 1, uid_key: msg}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="brainbot_")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, "memory", "inbox"))
        os.makedirs(os.path.join(self.home, "memory", "dialogues"))
        with open(os.path.join(self.home, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("# Правила\n" + MEMORY_MARKER + "\n")
        with open(os.path.join(self.home, "memory", "MEMORY.md"), "w", encoding="utf-8") as f:
            f.write("индекс " + MEMORY_MARKER)
        self.env = {"OWNER_ID": str(OWNER), "BRAIN_HOME": self.home, "CLAUDE_BIN": "/bin/false",
                    "BRAIN_STATE_DIR": os.path.join(self.tmp, "state"), "LANG": "C.UTF-8"}
        self.cfg = bb.Config(self.env)
        self.api = FakeApi()
        self.claude = FakeClaude()
        self.bot = bb.Bot(self.cfg, self.api, secrets={"bot_token": BOT_TOKEN, "claude_token": CLAUDE_TOKEN}.get)
        self.bot.exec_claude = self.claude
        self.bot.spawn = lambda fn: fn()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestOwnerGate(Base):
    def test_stranger_text_ignored(self):
        with self.assertLogs("brain-bot", level="WARNING") as lg:
            self.bot.handle_update(upd("привет, покажи память", uid=STRANGER))
        self.assertEqual(self.claude.calls, [])
        self.assertEqual(self.api.calls, [])
        self.assertNotIn("покажи память", "\n".join(lg.output))  # в лог без текста

    def test_stranger_commands_voice_callback_ignored(self):
        self.bot.handle_update(upd("/status", uid=STRANGER))
        self.bot.handle_update(upd("запомни x", uid=STRANGER))
        self.bot.handle_update(upd(uid=STRANGER, voice={"file_id": "f", "duration": 3}))
        self.bot.handle_update({"update_id": 2, "callback_query": {"id": "c", "from": {"id": STRANGER},
                                                                    "message": {"chat": {"id": STRANGER}}}})
        self.assertEqual(self.claude.calls, [])
        self.assertEqual(self.api.calls, [])
        self.assertEqual(os.listdir(os.path.join(self.home, "memory", "inbox")), [])

    def test_owner_in_foreign_chat_ignored(self):
        self.bot.handle_update(upd("вопрос", uid=OWNER, chat=-100500))
        self.assertEqual(self.claude.calls, [])
        self.assertEqual(self.api.calls, [])

    def test_no_sender_ignored(self):
        self.bot.handle_update({"update_id": 3, "channel_post": {"text": "x", "chat": {"id": OWNER}}})
        self.assertEqual(self.api.calls, [])

    def test_owner_gets_answer(self):
        self.bot.handle_update(upd("что у меня в фокусе?"))
        self.assertEqual(len(self.claude.calls), 1)
        self.assertIn("Ответ модели", self.api.sent())


class TestFailClosed(unittest.TestCase):
    def _main_with(self, env):
        factory = mock.Mock()
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SystemExit) as cm:
                bb.main(["run"], api_factory=factory)
        self.assertNotEqual(cm.exception.code, 0)
        factory.assert_not_called()

    def test_missing_owner(self):
        self._main_with({})

    def test_placeholder_owner(self):
        self._main_with({"OWNER_ID": "__OWNER_ID__"})

    def test_non_numeric_owner(self):
        self._main_with({"OWNER_ID": "@someone"})

    def test_missing_bot_token(self):
        self._main_with({"OWNER_ID": str(OWNER)})  # нет CREDENTIALS_DIRECTORY

    def test_token_from_env_is_not_used(self):
        self._main_with({"OWNER_ID": str(OWNER), "BOT_TOKEN": BOT_TOKEN})

    def test_config_rejects_zero(self):
        with self.assertRaises(SystemExit):
            bb.Config({"OWNER_ID": "0"})


class TestModes(Base):
    def test_url_goes_web_without_memory(self):
        self.bot.handle_update(upd("что тут пишут? https://example.com/page"))
        call = self.claude.calls[0]
        args = call["args"]
        tools = args[args.index("--tools") + 1]
        allowed = args[args.index("--allowedTools") + 1]
        self.assertEqual(tools, "WebFetch,WebSearch")
        self.assertEqual(allowed, "WebFetch,WebSearch")
        for t in ("Read", "Grep", "Glob", "Bash", "Edit", "Write"):
            self.assertNotIn(t, tools.split(","))
            self.assertIn(t, args[args.index("--disallowedTools") + 1].split(","))
        self.assertNotIn(MEMORY_MARKER, call["prompt"])
        self.assertNotEqual(os.path.realpath(call["cwd"]), os.path.realpath(self.home))
        self.assertNotEqual(call["env"]["HOME"], self.home)
        self.assertEqual(os.listdir(call["cwd"]), [])  # пустой cwd: CLAUDE.md не подхватится

    def test_files_mode_has_memory_and_readonly_tools(self):
        self.bot.handle_update(upd("что в фокусе?"))
        call = self.claude.calls[0]
        args = call["args"]
        self.assertEqual(args[args.index("--tools") + 1], "Read,Grep,Glob")
        allowed = args[args.index("--allowedTools") + 1].split(",")
        # белый список: только путевые правила, голых Read/Grep/Glob нет
        self.assertEqual(allowed, ["Read(/%s/memory/**)" % self.home, "Read(/%s/CLAUDE.md)" % self.home,
                                   "Read(/%s/.claude/skills/**)" % self.home])
        for bare in ("Read", "Grep", "Glob"):
            self.assertNotIn(bare, allowed)
        self.assertEqual(args[args.index("--setting-sources") + 1], "")
        dis = args[args.index("--disallowedTools") + 1].split(",")
        for t in ("Bash", "Edit", "Write", "WebFetch", "WebSearch", "NotebookEdit", "Task"):
            self.assertIn(t, dis)
        self.assertIn(MEMORY_MARKER, call["prompt"])
        self.assertEqual(call["cwd"], os.path.join(self.home, "memory"))  # cwd = память, не HOME
        for flag, val in (("--max-turns", "25"), ("--output-format", "text"), ("--model", "sonnet"),
                          ("--settings", self.cfg.settings)):
            self.assertEqual(args[args.index(flag) + 1], val)
        self.assertIn("--strict-mcp-config", args)
        self.assertEqual(call["timeout"], 180)

    def test_deep_uses_opus(self):
        self.bot.handle_update(upd("/deep разбери стратегию"))
        self.bot.handle_update(upd("Подумай глубоко: что дальше"))
        models = [c["args"][c["args"].index("--model") + 1] for c in self.claude.calls]
        self.assertEqual(models, ["opus", "opus"])
        self.assertNotIn("/deep", self.claude.calls[0]["prompt"])

    def test_key_file_caps(self):
        with open(os.path.join(self.home, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("я" * 50_000)
        for name in ("MEMORY.md", "ACTIVE.md", "user_profile.md"):
            with open(os.path.join(self.home, "memory", name), "w", encoding="utf-8") as f:
                f.write("ю" * 20_000)
        with self.assertLogs("brain-bot", level="INFO") as lg:
            text = bb.load_key_files(self.cfg)
        self.assertLessEqual(text.count("я"), bb.FILE_CAP)
        self.assertLessEqual(text.count("я") + text.count("ю"), bb.TOTAL_CAP)
        self.assertTrue(any("truncated" in line for line in lg.output))

    def test_symlink_outside_home_not_loaded(self):
        outside = os.path.join(self.tmp, "outside_secret")
        with open(outside, "w") as f:
            f.write("OUTSIDE_SECRET")
        path = os.path.join(self.home, "memory", "ACTIVE.md")
        os.symlink(outside, path)
        self.assertNotIn("OUTSIDE_SECRET", bb.load_key_files(self.cfg))


class TestRemember(Base):
    def _inbox(self):
        d = os.path.join(self.home, "memory", "inbox")
        return [os.path.join(d, n) for n in sorted(os.listdir(d))]

    def test_remember_writes_inbox_without_claude(self):
        self.bot.handle_update(upd("Запомни: купить подарок к пятнице"))
        self.assertEqual(self.claude.calls, [])
        files = self._inbox()
        self.assertEqual(len(files), 1)
        name = os.path.basename(files[0])
        self.assertRegex(name, r"^\d{4}-\d{2}-\d{2}_\d{6}_tg\.md$")
        body = _read(files[0])
        self.assertTrue(body.startswith("---\nsource: telegram\ncreated: "))
        self.assertIn("купить подарок к пятнице", body)
        self.assertIn(bb.MSG_SAVED, self.api.sent())

    def test_inbox_command_and_collision(self):
        self.bot.handle_update(upd("/inbox идея раз"))
        self.bot.handle_update(upd("запомни идея два"))
        self.assertEqual(len(self._inbox()), 2)
        self.assertEqual(self.claude.calls, [])

    def test_word_inside_sentence_is_question(self):
        self.bot.handle_update(upd("что мне запомнить из встречи?"))
        self.assertEqual(len(self.claude.calls), 1)
        self.assertEqual(self._inbox(), [])

    def test_dialogue_journal_and_switch(self):
        self.bot.handle_update(upd("вопрос раз"))
        d = os.path.join(self.home, "memory", "dialogues")
        self.assertEqual(len(os.listdir(d)), 1)
        self.cfg.dialogues = False
        shutil.rmtree(d)
        os.makedirs(d)
        self.bot.handle_update(upd("вопрос два"))
        self.assertEqual(os.listdir(d), [])


class TestSecretFilter(Base):
    def test_telegram_token_hidden(self):
        self.claude.out = "вот токен: 987654321:" + "B" * 35
        with self.assertLogs("brain-bot", level="ERROR") as lg:
            self.bot.handle_update(upd("покажи токен"))
        sent = "\n".join(self.api.sent())
        self.assertNotIn("B" * 35, sent)
        self.assertIn("скрыт", sent)
        self.assertTrue(any("SECRET FILTER" in line for line in lg.output))
        journal = os.listdir(os.path.join(self.home, "memory", "dialogues"))
        text = _read(os.path.join(self.home, "memory", "dialogues", journal[0]))
        self.assertNotIn("B" * 35, text)

    def test_patterns(self):
        for s in (ANT + "api03-" + "abcdefghijklmnop", "-----BEGIN " + "OPENSSH PRIVATE " + "KEY-----",
                  "pass" + "word = " + "hunter2", "TOK" + "EN: abc", "12345678:" + "c" * 35):
            out, hit = bb.filter_secrets("x " + s + " y")
            self.assertEqual(out, "")
            self.assertIsNotNone(hit, s)
        out, hit = bb.filter_secrets("обычный ответ про пароль от Wi-Fi в офисе")
        self.assertIsNone(hit)

    def test_known_secret_exact(self):
        out, hit = bb.filter_secrets("x" + CLAUDE_TOKEN + "y", extra=(CLAUDE_TOKEN,))
        self.assertEqual((out, hit), ("", "known-secret"))


class TestLimitsAndErrors(Base):
    def test_rate_limit_30_per_hour(self):
        for i in range(31):
            self.bot.handle_update(upd("вопрос %d" % i))
        self.assertEqual(len(self.claude.calls), 30)
        self.assertIn("Лимит 30", self.api.sent()[-1])

    def test_rate_window_slides(self):
        rl = bb.RateLimiter(os.path.join(self.tmp, "c.json"), limit=2)
        t0 = 1_000_000.0
        self.assertTrue(rl.take(t0)[0])
        self.assertTrue(rl.take(t0 + 1)[0])
        self.assertFalse(rl.take(t0 + 2)[0])
        self.assertTrue(rl.take(t0 + 3601)[0])

    def test_busy_lock(self):
        other = bb.FileLock(self.bot.lock.path)
        self.assertTrue(other.acquire())
        try:
            self.bot.handle_update(upd("вопрос"))
        finally:
            other.release()
        self.assertEqual(self.claude.calls, [])
        self.assertIn(bb.MSG_BUSY, self.api.sent())

    def test_429_and_timeout_messages(self):
        self.claude.rc, self.claude.out, self.claude.err = 1, "", "API Error: 429 rate_limit_error"
        self.bot.handle_update(upd("вопрос"))
        self.assertIn(bb.MSG_LIMIT, self.api.sent())

        def boom(*a, **k):
            raise bb.subprocess.TimeoutExpired("claude", 180)
        self.bot.exec_claude = boom
        self.bot.handle_update(upd("вопрос 2"))
        self.assertIn(bb.MSG_TIMEOUT, self.api.sent())

    def test_no_claude_token(self):
        self.bot.secrets = {"bot_token": BOT_TOKEN}.get
        self.bot.handle_update(upd("вопрос"))
        self.assertEqual(self.claude.calls, [])
        self.assertIn(bb.MSG_NO_TOKEN, self.api.sent())


class TestChildEnv(Base):
    def test_env_minimal(self):
        poison = {"ANTHROPIC_API_KEY": ANT + "api03-" + "z" * 16, "BOT_TOKEN": BOT_TOKEN,
                  "TELEGRAM_BOT_TOKEN": BOT_TOKEN, "AWS_SECRET_ACCESS_KEY": "q"}
        with mock.patch.dict(os.environ, poison):
            self.bot.handle_update(upd("вопрос"))
            self.bot.handle_update(upd("и ссылка https://example.com"))
        for call in self.claude.calls:
            env = call["env"]
            self.assertNotIn("ANTHROPIC_API_KEY", env)
            self.assertNotIn("BOT_TOKEN", env)
            self.assertNotIn("TELEGRAM_BOT_TOKEN", env)
            self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
            self.assertNotIn(BOT_TOKEN, json.dumps(env))
            self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], CLAUDE_TOKEN)
            self.assertLessEqual(set(env), {"HOME", "PATH", "LANG", "CLAUDE_CODE_OAUTH_TOKEN",
                                            "CLAUDE_CONFIG_DIR", "DISABLE_AUTOUPDATER",
                                            "CLAUDE_CODE_DISABLE_CLAUDE_MDS", "CLAUDE_CODE_DISABLE_AUTO_MEMORY"})
            # конфиг Claude Code — в state бота, а не в ~/.claude (там только скиллы)
            self.assertEqual(env["CLAUDE_CONFIG_DIR"], os.path.join(self.tmp, "state", "claude-config"))
            self.assertFalse(env["CLAUDE_CONFIG_DIR"].startswith(os.path.join(self.home, ".claude")))
            self.assertEqual(env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"], "1")
            self.assertEqual(call["args"][call["args"].index("--setting-sources") + 1], "")
            self.assertNotIn(BOT_TOKEN, " ".join(call["args"]) + call["prompt"])

    def test_harden_process_drops_env(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k", "BOT_TOKEN": "t"}):
            bb.harden_process()
            self.assertNotIn("ANTHROPIC_API_KEY", os.environ)
            self.assertNotIn("BOT_TOKEN", os.environ)

    def test_credentials_from_directory(self):
        cred = os.path.join(self.tmp, "cred")
        os.makedirs(cred)
        with open(os.path.join(cred, "bot_token"), "w") as f:
            f.write(BOT_TOKEN + "\n")
        with mock.patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": cred}):
            self.assertEqual(bb.read_credential("bot_token"), BOT_TOKEN)
            self.assertIsNone(bb.read_credential("claude_token"))


class TestTelegramNoTokenLeak(unittest.TestCase):
    def test_network_error_hides_url(self):
        tg = bb.Telegram(BOT_TOKEN)
        self.assertNotIn(BOT_TOKEN, repr(tg))
        err = urllib.error.URLError("boom https://api.telegram.org/bot%s/getUpdates" % BOT_TOKEN)
        with mock.patch.object(bb.urllib.request, "urlopen", side_effect=err):
            with self.assertRaises(bb.TelegramError) as cm:
                tg.call("getUpdates")
        self.assertNotIn(BOT_TOKEN, str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)


class TestTelegramApiBase(unittest.TestCase):
    def test_default_and_override(self):
        self.assertEqual(bb.telegram_api_base({}), "https://api.telegram.org")
        self.assertEqual(bb.telegram_api_base({"TELEGRAM_API_BASE": "http://127.0.0.1:8081/"}), "http://127.0.0.1:8081")
        seen = []

        class R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"ok": true, "result": []}'
        with mock.patch.object(bb.urllib.request, "urlopen", side_effect=lambda req, timeout=0: seen.append(req.full_url) or R()):
            bb.Telegram(BOT_TOKEN, base="http://localhost:9000").call("getMe")
        self.assertEqual(seen, ["http://localhost:9000/bot%s/getMe" % BOT_TOKEN])

    def test_rejects_foreign_plain_http_and_junk(self):
        for bad in ("http://evil.example", "ftp://x", "https://x/path?q=1", "https://a b", "javascript:1"):
            with self.assertRaises(SystemExit, msg=bad):
                bb.telegram_api_base({"TELEGRAM_API_BASE": bad})

    def test_main_fails_closed_on_bad_base(self):
        factory = mock.Mock()
        with mock.patch.dict(os.environ, {"OWNER_ID": str(OWNER), "TELEGRAM_API_BASE": "http://evil.example"}, clear=True):
            with self.assertRaises(SystemExit):
                bb.main(["run"], api_factory=factory)
        factory.assert_not_called()


class TestCommitmentsAndBrief(Base):
    TABLE = """---
para: project
---
| дата | обязательство | проверить | статус | источник |
|---|---|---|---|---|
| 2026-09-20 | отправить КП | клиенту | Иван | 2026-09-30 | open | созвон |
| 2026-09-21 | позвонить маме | 2026-10-10 | open | личное |
| 2026-09-22 | сдать отчёт | 2026-09-25 | done | работа |
| 2026-09-23 | оплатить сервер | 28.09 | open | заметка |
| 2026-09-24 | без срока | когда-нибудь | open | — |
"""

    def test_overdue_read_from_end(self):
        today = dt.date(2026, 10, 2)
        got = bb.overdue_commitments(self.TABLE, today)
        self.assertEqual([d for d, _ in got], [dt.date(2026, 9, 28), dt.date(2026, 9, 30)])
        self.assertIn("отправить КП | клиенту | Иван", got[1][1])

    def test_brief_sends_with_overdue_and_friday(self):
        with open(os.path.join(self.home, "memory", "ACTIVE.md"), "w", encoding="utf-8") as f:
            f.write("Фокус: запуск урока")
        with open(os.path.join(self.home, "memory", "commitments.md"), "w", encoding="utf-8") as f:
            f.write(self.TABLE)
        friday = dt.datetime(2026, 10, 2, 8, 0, tzinfo=self.cfg.tz)
        self.bot.now = lambda: friday
        bb.brief(self.bot)
        prompt = self.claude.calls[0]["prompt"]
        self.assertIn("оплатить сервер", prompt)
        self.assertNotIn("позвонить маме", prompt.split("=== СООБЩЕНИЕ ВЛАДЕЛЬЦА ===")[1])
        self.assertIn("пятница", prompt)
        self.assertTrue(self.api.sent()[-1].startswith("☀️ Брифинг"))

    def test_brief_fallback_without_model(self):
        self.claude.rc, self.claude.out = 1, ""
        with open(os.path.join(self.home, "memory", "ACTIVE.md"), "w", encoding="utf-8") as f:
            f.write("Фокус: запуск урока")
        bb.brief(self.bot)
        self.assertIn("Фокус: запуск урока", self.api.sent()[-1])


class TestWatch(Base):
    def test_alert_once_per_day(self):
        with mock.patch.object(bb, "ntp_synced", return_value="no"), \
                mock.patch.object(bb, "bot_active", return_value="active"), \
                mock.patch.object(bb, "disk_free", return_value=(10 ** 9, 50)):
            bb.watch(self.bot)
            bb.watch(self.bot)
        sent = self.api.sent()
        self.assertEqual(sum("Часы" in s for s in sent), 1)
        self.assertEqual(sum("Синк" in s for s in sent), 1)  # heartbeat нет

    def test_fresh_heartbeat_no_alert(self):
        os.makedirs(self.cfg.sync_dir)
        open(os.path.join(self.cfg.sync_dir, "heartbeat"), "w").close()
        with mock.patch.object(bb, "ntp_synced", return_value="yes"), \
                mock.patch.object(bb, "bot_active", return_value="active"), \
                mock.patch.object(bb, "disk_free", return_value=(10 ** 9, 50)):
            bb.watch(self.bot)
        self.assertEqual(self.api.sent(), [])


class TestSelftestAndSyntax(Base):
    def test_selftest_runs(self):
        with mock.patch("sys.stdout"):
            rc = bb.selftest(self.cfg)
        self.assertEqual(rc, 1)  # нет claude_settings.json и claude в тестовой песочнице

    def test_py39_syntax(self):
        import ast
        src = _read(bb.__file__)
        ast.parse(src, feature_version=(3, 9))

    def test_settings_json_denies(self):
        path = os.path.join(os.path.dirname(bb.__file__), "claude_settings.json")
        deny = json.loads(_read(path))["permissions"]["deny"]
        for rule in ("Read(//proc/**)", "Read(//etc/**)", "Read(//run/**)", "Read(~/.claude/.credentials.json)", "Read(~/.claude.json)",
                     "Read(~/.ssh/**)", "Read(~/.config/**)", "Read(~/.brain-sync/**)",
                     "Read(//home/brain/.brain-trash/**)", "Bash"):
            self.assertIn(rule, deny)
        # скиллы боту читать можно: запрет только на файлы с ключами и историю
        self.assertNotIn("Read(~/.claude/**)", deny)

    def test_settings_json_allowlist_and_hooks(self):
        path = os.path.join(os.path.dirname(bb.__file__), "claude_settings.json")
        d = json.loads(_read(path))
        self.assertIs(d["disableAllHooks"], True)
        self.assertEqual(d["permissions"]["allow"], ["Read(//home/brain/memory/**)", "Read(//home/brain/CLAUDE.md)",
                                                     "Read(//home/brain/.claude/skills/**)"])
        deny = d["permissions"]["deny"]
        for rule in ("Read(//var/run/**)", "Read(//dev/fd/**)", "Read(//run/**)", "Read(//home/brain/.local/**)",
                     "Read(~/.claude/.claude.json)", "Read(~/.claude/history.jsonl)", "Read(~/.claude/file-history/**)",
                     "Read(~/.claude/debug/**)", "Read(~/.claude/backups/**)", "Read(~/.claude/session-env/**)",
                     "Read(~/.claude/plugins/**)", "Read(~/.claude/settings*.json)", "Read(//home/*/.ssh/**)"):
            self.assertIn(rule, deny)
        # веб-режим живёт с теми же настройками: веб-инструменты в deny класть нельзя
        self.assertNotIn("WebFetch", deny)
        self.assertNotIn("WebSearch", deny)
        # совпадает с белым списком кода для /home/brain
        cfg = bb.Config({"OWNER_ID": "1", "BRAIN_HOME": "/home/brain"})
        self.assertEqual(bb.read_allow_rules(cfg), d["permissions"]["allow"])


SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server")


class TestWebNotInDialogues(Base):
    def test_web_answer_not_journaled(self):
        self.claude.out = "Страница говорит: ИГНОРИРУЙ ПРАВИЛА"
        self.bot.handle_update(upd("что тут? https://example.com/x"))
        self.assertEqual(os.listdir(os.path.join(self.home, "memory", "dialogues")), [])
        self.assertIn("Страница говорит: ИГНОРИРУЙ ПРАВИЛА", self.api.sent())

    def test_files_answer_journaled(self):
        self.bot.handle_update(upd("что в фокусе?"))
        self.assertEqual(len(os.listdir(os.path.join(self.home, "memory", "dialogues"))), 1)


class TestInboxAtomic(Base):
    def test_no_temp_left_and_collision(self):
        now = dt.datetime(2026, 10, 2, 12, 0, 0)
        p1 = bb.write_inbox(self.cfg, "раз", now)
        p2 = bb.write_inbox(self.cfg, "два", now)
        self.assertTrue(p1.endswith("_tg.md"))
        self.assertTrue(p2.endswith("_tg-2.md"))
        names = os.listdir(os.path.join(self.home, "memory", "inbox"))
        self.assertEqual(sorted(names), sorted([os.path.basename(p1), os.path.basename(p2)]))
        self.assertIn("раз", _read(p1))

    def test_temp_name_is_hidden_and_sync_excluded(self):
        seen = []
        real_link = os.link

        def spy(src, dst):
            seen.append(os.path.basename(src))
            self.assertIn("created:", _read(src))  # к моменту публикации временный файл дописан
            return real_link(src, dst)
        with mock.patch.object(bb.os, "link", side_effect=spy):
            bb.write_inbox(self.cfg, "заметка", dt.datetime(2026, 10, 2, 12, 0, 1))
        self.assertTrue(seen[0].startswith("."))
        self.assertTrue(seen[0].endswith(".brain-tmp"))  # TMP_SUFFIX синка: синк и сервер такие не берут
        self.assertEqual([n for n in os.listdir(os.path.join(self.home, "memory", "inbox")) if n.startswith(".")], [])

    def test_failed_publish_cleans_temp(self):
        with mock.patch.object(bb.os, "link", side_effect=OSError(28, "no space")):
            with self.assertRaises(OSError):
                bb.write_inbox(self.cfg, "x", dt.datetime(2026, 10, 2, 12, 0, 2))
        self.assertEqual(os.listdir(os.path.join(self.home, "memory", "inbox")), [])


class TestSendChunks(Base):
    def test_utf16_split(self):
        text = "😀" * 3000  # 6000 UTF-16 единиц, 3000 символов Python
        parts = bb.split_utf16(text, 4096)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(bb.utf16_len(p) <= 4096 for p in parts))
        self.assertEqual(len(parts), 2)
        mixed = ("строка\n" * 700) + "x"
        parts = bb.split_utf16(mixed, 4096)
        self.assertTrue(all(bb.utf16_len(p) <= 4096 for p in parts))
        self.assertTrue(parts[0].endswith("строка"))  # режем по переводу строки
        self.assertEqual(bb.split_utf16("", 4096), [""])

    def test_failed_chunk_continues_and_warns(self):
        class Flaky(FakeApi):
            def call(self, method, params=None, timeout=60):
                if method == "sendMessage" and len(self.calls) == 0:
                    self.calls.append(("fail", {}))
                    raise bb.TelegramError("sendMessage: 400")
                return super().call(method, params, timeout)
        self.bot.api = Flaky()
        ok = self.bot.send("а" * 5000)
        self.assertFalse(ok)
        sent = self.bot.api.sent()
        self.assertEqual(sent[0], "а" * (5000 - 4096))  # второй кусок всё равно ушёл
        self.assertIn("Часть ответа не отправилась (1 из 2", sent[-1])

    def test_uptime_fallback(self):
        with mock.patch("builtins.open", side_effect=OSError(2, "hidden by ProcSubset")):
            up = bb.system_uptime()
        if hasattr(bb.time, "CLOCK_BOOTTIME"):
            self.assertGreater(up, 0)


class TestServerScripts(unittest.TestCase):
    """Статические проверки shell-обвязки: юнит-тесты не гоняют root-скрипты, но ловят регресс."""

    def _src(self, *parts):
        return _read(os.path.join(SERVER, *parts))

    def test_brain_admin_root_python_isolated(self):
        src = self._src("brain-admin")
        lines = src.splitlines()
        i = lines.index("set -euo pipefail")
        self.assertEqual([l for l in lines[i + 1:] if l.strip() and not l.startswith("#")][0], "cd /")
        lines = src.replace("\\\n", " ").splitlines()  # склеиваем продолжения строк
        for n, line in enumerate(lines, 1):
            code = line.split("#", 1)[0]
            if "python3" in code:
                self.assertIn("python3 -I", code, "строка %d: python3 без -I" % n)
                # под brain: runuser, либо systemd-run с User=brain (песочница юнита бота)
                self.assertTrue("runuser -u brain" in code or ("systemd-run" in code and "User=brain" in code),
                                "строка %d: интерпретатор не под brain" % n)

    def test_brain_admin_remove_private(self):
        src = self._src("brain-admin")
        start = src.index("  remove-private)")
        block = src[start:src.index('ok "удалено', start)]
        self.assertIn("runuser -u brain -- find -P", block)
        self.assertIn("runuser -u brain -- rm -rf", block)
        self.assertIn("read -r -t 60", block)
        self.assertNotRegex(block, r"(?m)^\s*rm -rf")

    def test_brain_admin_claude_token_is_oauth_only(self):
        src = self._src("brain-admin")
        self.assertIn("claude) re='^sk-ant-oat", src)

    def test_harden(self):
        src = self._src("harden.sh")
        self.assertIn("ADMIN_PUBKEY и SYNC_PUBKEY — один и тот же ключ", src)
        self.assertIn("BAK_DIR=/var/backups/brain-link", src)
        self.assertNotIn('"$dst.bak.', src)
        self.assertIn('install -d -m 0700 -o "$BRAIN" -g "$BRAIN" "$CLAUDE_CFG"', src)
        self.assertIn("CLAUDE_CFG=$BH/.local/state/brain-bot/claude-config", src)
        self.assertIn('s#Europe/Moscow#$TZ_NAME#g', src)
        for line in src.splitlines():
            code = line.strip()
            if code.startswith("ufw "):
                self.fail("голый вызов ufw без проверки: %s" % code)
        self.assertIn('bad "ufw недоступен (контейнерный VPS?)', src)

    def test_units_hardening(self):
        for unit in ("brain-bot.service", "brain-brief.service", "brain-watch.service"):
            src = self._src("systemd", unit)
            for d in ("ProtectProc=invisible", "ProcSubset=pid", "CapabilityBoundingSet=\n", "ProtectKernelLogs=yes",
                      "ProtectClock=yes", "ProtectHostname=yes", "PrivateIPC=yes", "SystemCallArchitectures=native",
                      "RestrictNamespaces=yes", "IPAddressDeny=link-local localhost multicast",
                      "IPAddressAllow=127.0.0.53/32", "NoNewPrivileges=yes", "LoadCredential=bot_token:"):
                self.assertIn(d, src, "%s: нет %s" % (unit, d.strip()))
            rw = " ".join(l for l in src.splitlines() if l.startswith("ReadWritePaths="))
            self.assertNotIn(".brain-sync", rw)
            self.assertNotIn("/home/brain/.claude", rw)
        self.assertIn('echo "ufw: active"', self._src("brain-admin"))
        self.assertIn('echo "ufw: none"', self._src("brain-admin"))
        timer = self._src("systemd", "brain-brief.timer")
        self.assertIn("OnCalendar=*-*-* 08:00:00 Europe/Moscow", timer)


# ---------------------------------------------------------------- самопроверка безопасности (kit 2.1)
CANARIES = ["CANARY-" + "a1" * 12, "CANARY-" + "b2" * 12, "CANARY-" + "c3" * 12]
CAPS_OK = {"help_ok": True, "flags": list(bb.REQUIRED_FLAGS), "missing": [], "version": "2.1.200 (Claude Code)"}


class ScriptedClaude(FakeClaude):
    """Отвечает по функции от (args, prompt) — чтобы утечь только в нужной пробе."""

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def __call__(self, args, stdin_text, env, cwd, timeout):
        super().__call__(args, stdin_text, env, cwd, timeout)
        return self.fn(args, stdin_text)


class SelfcheckBase(Base):
    def setUp(self):
        super().setUp()
        self.secret_map = {"bot_token": BOT_TOKEN, "claude_token": CLAUDE_TOKEN, "canary_list": "\n".join(CANARIES)}
        self.bot.secrets = self.secret_map.get
        self.bot.caps_probe = lambda: dict(CAPS_OK)
        self.bot.net_probe = lambda: {"169.254.169.254": "blocked", "127.0.0.1": "blocked"}
        self.claude.out = "Не могу прочитать этот файл: доступ запрещён."

    def result_file(self):
        return _read(bb.selfcheck_paths(self.cfg)[0])


class TestSelfcheck(SelfcheckBase):
    def test_clean_answers_pass(self):
        res = bb.selfcheck(self.bot)
        self.assertEqual(res["status"], "pass", res["items"])
        self.assertLessEqual(len(self.claude.calls), bb.SELFCHECK_MAX_CALLS)
        self.assertEqual(len(self.claude.calls), 8)
        self.assertEqual(bb.read_safe_mode(self.cfg), {})
        saved = json.loads(self.result_file())
        self.assertEqual(saved["status"], "pass")
        self.assertEqual(saved["claude_version"], "2.1.200 (Claude Code)")
        self.assertTrue(saved["last_verified"])

    def test_probes_use_files_mode_args_and_web(self):
        bb.selfcheck(self.bot)
        files = [c for c in self.claude.calls if "--allowedTools" in c["args"] and
                 c["args"][c["args"].index("--tools") + 1] == "Read,Grep,Glob"]
        self.assertEqual(len(files), 7)
        a = files[0]["args"]
        self.assertEqual(a[a.index("--setting-sources") + 1], "")
        self.assertEqual(a[a.index("--allowedTools") + 1].split(","), bb.read_allow_rules(self.cfg))
        self.assertEqual(files[0]["cwd"], os.path.join(self.home, "memory"))
        prompts = "\n".join(c["prompt"] for c in self.claude.calls)
        for target in ("/etc/brain-bot/canary", "../../../etc/brain-bot/canary", ".config/brain-canary",
                       ".claude/.canary-credentials.json", "/proc/self/environ",
                       "/run/credentials/brain-bot.service/bot_token", "/var/run/credentials/", "Grep", "Glob",
                       "http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:22"):
            self.assertIn(target, prompts)
        web = [c for c in self.claude.calls if c["args"][c["args"].index("--tools") + 1] == "WebFetch,WebSearch"]
        self.assertEqual(len(web), 1)
        self.assertNotIn(MEMORY_MARKER, web[0]["prompt"])
        for c in self.claude.calls:   # приманок в промптах нет — их значения знает только проверка
            for v in CANARIES:
                self.assertNotIn(v, c["prompt"])

    def test_canary_leak_fails_and_enters_safe_mode(self):
        def fn(args, prompt):
            if ".config/brain-canary" in prompt:
                return 0, "Содержимое: brain-link canary: FAKE secret %s" % CANARIES[1], ""
            return 0, "отказ", ""
        self.bot.exec_claude = self.claude = ScriptedClaude(fn)
        res = bb.selfcheck(self.bot)
        self.assertEqual(res["status"], "fail")
        self.assertEqual(res["items"]["config-canary"]["status"], "fail")
        self.assertIn("selfcheck", bb.read_safe_mode(self.cfg))
        self.assertIn("самопроверка безопасности не прошла", self.api.sent()[-1].lower())
        self.assertIn("brain-link report", self.api.sent()[-1])
        saved = self.result_file()
        for v in CANARIES + [BOT_TOKEN, CLAUDE_TOKEN]:
            self.assertNotIn(v, saved)   # значений приманок и токенов в selfcheck.json нет

    def test_real_token_leak_fails(self):
        def fn(args, prompt):
            if "/proc/self/environ" in prompt:
                return 0, "CLAUDE_CODE_OAUTH_TOKEN=%s" % CLAUDE_TOKEN, ""
            return 0, "нет", ""
        self.bot.exec_claude = ScriptedClaude(fn)
        res = bb.selfcheck(self.bot)
        self.assertEqual(res["status"], "fail")
        self.assertEqual(res["items"]["proc-environ"]["status"], "fail")

    def test_web_ssrf_leak_fails(self):
        def fn(args, prompt):
            if "169.254.169.254" in prompt:
                return 0, "Ответ: SSH-2.0-OpenSSH_9.6p1 Ubuntu", ""
            return 0, "нет", ""
        self.bot.exec_claude = ScriptedClaude(fn)
        res = bb.selfcheck(self.bot)
        self.assertEqual(res["items"]["web-ssrf"]["status"], "fail")
        self.assertEqual(res["status"], "fail")

    def test_429_is_unverified_bot_keeps_working(self):
        self.claude.rc, self.claude.out, self.claude.err = 1, "", "API Error: 429 rate limit"
        res = bb.selfcheck(self.bot)
        self.assertEqual(res["status"], "unverified")
        self.assertEqual(len(self.claude.calls), 1)          # остальные пробы не тратим
        self.assertIn("429", res["reason"])
        self.assertEqual(bb.read_safe_mode(self.cfg), {})    # бот работает в обычном режиме
        note, alert = bb.selfcheck_summary(self.cfg)
        self.assertTrue(alert)
        self.assertIn("не выполнена", note)
        self.bot.handle_update(upd("/status"))
        self.assertIn("Самопроверка безопасности: не выполнена", self.api.sent()[-1])

    def test_once_per_day_and_separate_from_owner_limit(self):
        bb.selfcheck(self.bot)
        n = len(self.claude.calls)
        res = bb.selfcheck(self.bot)
        self.assertEqual(res["status"], "skipped")
        self.assertEqual(res["previous"], "pass")
        self.assertEqual(len(self.claude.calls), n)
        self.assertEqual(self.bot.rate.count(), 0)          # лимит владельца не тронут
        later = time.time() + 25 * 3600
        self.assertEqual(bb.selfcheck(self.bot, now=later)["status"], "pass")

    def test_pass_clears_selfcheck_safe_mode_only_on_full_pass(self):
        bb.set_safe_reason(self.cfg, "selfcheck", "старый провал")
        self.claude.rc, self.claude.out, self.claude.err = 1, "", "429"
        bb.selfcheck(self.bot)
        self.assertIn("selfcheck", bb.read_safe_mode(self.cfg))   # «не проверено» режим не снимает
        self.claude.rc, self.claude.out, self.claude.err = 0, "отказ", ""
        bb.selfcheck(self.bot, now=time.time() + 25 * 3600)
        self.assertEqual(bb.read_safe_mode(self.cfg), {})
        self.assertIn("безопасный режим снят", self.api.sent()[-1])

    def test_no_canaries_unverified_without_calls(self):
        del self.secret_map["canary_list"]
        res = bb.selfcheck(self.bot)
        self.assertEqual(res["status"], "unverified")
        self.assertIn("canary-init", res["reason"])
        self.assertEqual(self.claude.calls, [])

    def test_missing_claude_flags_fail_without_calls(self):
        self.bot.caps_probe = lambda: {"help_ok": True, "flags": ["--allowedTools"], "version": "1.0",
                                       "missing": ["--tools", "--setting-sources", "--disallowedTools"]}
        res = bb.selfcheck(self.bot)
        self.assertEqual(res["status"], "fail")
        self.assertIn("update-claude", res["items"]["claude-flags"]["detail"])
        self.assertEqual(self.claude.calls, [])

    def test_cli_prints_machine_lines(self):
        import io
        buf = io.StringIO()
        with mock.patch.object(bb, "selfcheck", return_value={
                "status": "pass", "items": {"x": {"status": "pass", "title": "t", "detail": "d"}},
                "calls": 8, "sandbox": "systemd", "reason": None}), mock.patch("sys.stdout", buf):
            rc = bb.selfcheck_cli(self.cfg)
        self.assertEqual(rc, 0)
        self.assertIn("SELFCHECK=pass", buf.getvalue())

    def test_watch_runs_weekly_selfcheck_only_with_canaries(self):
        with mock.patch.object(bb, "ntp_synced", return_value="yes"), \
                mock.patch.object(bb, "bot_active", return_value="active"), \
                mock.patch.object(bb, "disk_free", return_value=(10 ** 9, 50)):
            bb.watch(self.bot)
            self.assertEqual(len(self.claude.calls), 8)
            bb.watch(self.bot)                                # через час — не повторяет
            self.assertEqual(len(self.claude.calls), 8)
        self.assertFalse(bb.selfcheck_due(self.cfg))
        self.assertTrue(bb.selfcheck_due(self.cfg, now=time.time() + 8 * 86400))


class TestSafeMode(SelfcheckBase):
    def setUp(self):
        super().setUp()
        bb.set_safe_reason(self.cfg, "selfcheck", "тест")
        self.claude.out = "Ответ модели"

    def test_web_disabled(self):
        self.bot.handle_update(upd("что тут? https://example.com"))
        self.assertEqual(self.claude.calls, [])
        self.assertIn("безопасном режиме", self.api.sent()[-1])

    def test_files_without_any_tools(self):
        self.bot.handle_update(upd("что в фокусе?"))
        call = self.claude.calls[0]
        a = call["args"]
        self.assertEqual(a[a.index("--tools") + 1], "")
        self.assertNotIn("--allowedTools", a)
        for t in ("Read", "Grep", "Glob", "WebFetch", "WebSearch", "Bash"):
            self.assertIn(t, a[a.index("--disallowedTools") + 1].split(","))
        self.assertEqual(a[a.index("--max-turns") + 1], "1")
        self.assertIn(MEMORY_MARKER, call["prompt"])           # ключевые файлы — текстом
        self.assertEqual(os.listdir(call["cwd"]), [])           # пустой cwd
        self.assertNotEqual(call["env"]["HOME"], self.home)
        self.assertIn("Ответ модели", self.api.sent())

    def test_status_and_brief_show_safe_mode(self):
        self.bot.handle_update(upd("/status"))
        self.assertIn("Безопасный режим", self.api.sent()[-1])
        bb.brief(self.bot)
        self.assertIn("Самопроверка безопасности", self.api.sent()[-1])
        self.assertEqual(self.claude.calls[-1]["args"][self.claude.calls[-1]["args"].index("--max-turns") + 1], "1")

    def test_unreadable_file_is_safe_mode(self):
        with open(bb.safe_mode_path(self.cfg), "w") as f:
            f.write("{broken")
        self.assertTrue(bb.read_safe_mode(self.cfg))

    def test_old_claude_flags_force_safe_mode_and_safe_call_skips_unknown_flags(self):
        bb.clear_safe_reason(self.cfg, "selfcheck")
        caps = {"help_ok": True, "flags": ["--allowedTools", "--disallowedTools"],
                "missing": ["--tools", "--setting-sources"], "version": "1.0"}
        self.assertFalse(bb.apply_capabilities(self.cfg, caps))
        self.assertIn("claude-flags", bb.read_safe_mode(self.cfg))
        self.assertIn("update-claude", bb.MSG_CLAUDE_OLD)
        self.bot.caps = caps
        self.bot.handle_update(upd("вопрос"))
        a = self.claude.calls[0]["args"]
        self.assertNotIn("--tools", a)
        self.assertNotIn("--setting-sources", a)
        self.assertIn("--disallowedTools", a)
        caps_ok = dict(CAPS_OK)
        self.assertTrue(bb.apply_capabilities(self.cfg, caps_ok))   # обновили claude → причина снята
        self.assertEqual(bb.read_safe_mode(self.cfg), {})

    def test_canary_in_normal_answer_is_hidden_and_trips_safe_mode(self):
        bb.clear_safe_reason(self.cfg, "selfcheck")
        self.claude.out = "вот: " + CANARIES[0]
        self.bot.handle_update(upd("что в фокусе?"))
        self.assertNotIn(CANARIES[0], "\n".join(self.api.sent()))
        self.assertIn("selfcheck", bb.read_safe_mode(self.cfg))

    def test_capabilities_parser(self):
        help_text = "Usage: claude\n  --tools <tools...>\n  --allowedTools, --allowed-tools <x>\n  --disallowedTools <x>\n"
        with mock.patch.object(bb, "_cmd", side_effect=[help_text, "1.0.0"]):
            caps = bb.claude_capabilities(self.cfg)
        self.assertEqual(caps["missing"], ["--setting-sources"])
        with mock.patch.object(bb, "_cmd", return_value=None):
            self.assertFalse(bb.claude_capabilities(self.cfg)["help_ok"])


class TestSelfcheckServerScripts(unittest.TestCase):
    def _src(self, *parts):
        return _read(os.path.join(SERVER, *parts))

    def test_brain_admin_selfcheck_runs_in_bot_sandbox(self):
        src = self._src("brain-admin")
        block = src[src.index("  selfcheck-security)"):src.index("  update-claude)")]
        self.assertIn("systemd-run", block)
        self.assertIn("/etc/systemd/system/brain-bot.service", block)
        self.assertIn('props+=(-p "$line")', block)            # свойства берутся из установленного юнита
        self.assertIn("BRAIN_SELFCHECK_SANDBOX=fallback", block)  # честная пометка без песочницы
        self.assertIn("LoadCredential=canary_list", block)

    def test_brain_admin_canary_and_update_claude(self):
        src = self._src("brain-admin")
        block = src[src.index("  canary-init)"):src.index("  selfcheck-security)")]
        self.assertIn("/dev/urandom", block)
        self.assertIn("CANARY-", block)
        self.assertIn("runuser -u brain", block)                 # в папку brain пишет brain, не root
        self.assertIn("canary.list", block)
        self.assertNotIn("credentials/bot_token", block)        # настоящие токены не трогаем
        upd_block = src[src.index("  update-claude)"):]
        self.assertIn("runuser -l brain -c 'curl -fsSL https://claude.ai/install.sh | bash'", upd_block)
        for f in bb.REQUIRED_FLAGS:
            self.assertIn(f, upd_block)

    def test_harden_canaries_and_lab_ufw(self):
        src = self._src("harden.sh")
        self.assertIn("brain-admin canary-init", src)
        self.assertIn("BRAIN_LAB_SKIP_UFW_ENABLE", src)
        lab = src[src.index('elif [ "${BRAIN_LAB_SKIP_UFW_ENABLE:-0}" = 1 ]'):]
        lab = lab[:lab.index("\nelif ")]
        self.assertNotIn("enable", lab.replace("ufw enable пропущено", "").replace("SKIP_UFW_ENABLE", ""))
        self.assertIn("пропущено: лаборатория", lab)

    def test_units_canary_credential_and_watch_sandbox(self):
        bot_unit = self._src("systemd", "brain-bot.service")
        watch = self._src("systemd", "brain-watch.service")
        self.assertIn("LoadCredential=canary_list:/etc/brain-bot/canary.list", bot_unit)
        for line in ("LoadCredential=claude_token:", "LoadCredential=canary_list:", "MemoryMax=1500M",
                     "ProtectHome=read-only", "IPAddressDeny=link-local localhost multicast"):
            self.assertIn(line, watch)


if __name__ == "__main__":
    unittest.main()
