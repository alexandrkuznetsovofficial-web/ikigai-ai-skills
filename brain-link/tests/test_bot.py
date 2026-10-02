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
        dis = args[args.index("--disallowedTools") + 1].split(",")
        for t in ("Bash", "Edit", "Write", "WebFetch", "WebSearch", "NotebookEdit", "Task"):
            self.assertIn(t, dis)
        self.assertIn(MEMORY_MARKER, call["prompt"])
        self.assertEqual(call["cwd"], self.home)
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
                                            "CLAUDE_CONFIG_DIR", "DISABLE_AUTOUPDATER"})
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


if __name__ == "__main__":
    unittest.main()
