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


# Бот работает только на Linux-сервере: замки — fcntl.flock. На Windows (CI unit) этих тестов нет —
# классы, которым нужен fcntl, пропускаются целиком (наследники Base тоже).
NEEDS_FCNTL = unittest.skipUnless(bb.fcntl is not None and hasattr(os, "getuid"),
                                  "бот и его замки (fcntl) — только Linux/Mac")


@NEEDS_FCNTL
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
        for flag, val in (("--max-turns", "25"), ("--output-format", "text"), ("--model", "opus"),
                          ("--settings", self.cfg.settings)):
            self.assertEqual(args[args.index(flag) + 1], val)
        self.assertIn("--strict-mcp-config", args)
        self.assertEqual(call["timeout"], 300)   # kit 2.3: Opus — 5 минут

    def test_default_is_opus_fast_is_sonnet(self):
        """kit 2.3: по умолчанию Opus; /fast — Sonnet; /fast без вопроса — подсказка, claude не зовём."""
        self.assertEqual((self.cfg.model_default, self.cfg.model_fast), ("opus", "sonnet"))
        self.bot.handle_update(upd("что в фокусе?"))
        self.bot.handle_update(upd("/fast коротко: что в фокусе?"))
        self.bot.handle_update(upd("/fast"))
        models = [c["args"][c["args"].index("--model") + 1] for c in self.claude.calls]
        self.assertEqual(models, ["opus", "sonnet"])
        self.assertNotIn("/fast", self.claude.calls[1]["prompt"])
        self.assertTrue(any("/fast" in m for m in self.api.sent()))
        self.assertIn("/fast", bb.HELP)
        self.assertIn("Opus", bb.HELP)

    def test_fast_has_short_timeout_brief_and_selfcheck_are_sonnet(self):
        self.bot.handle_update(upd("/fast коротко"))
        self.assertEqual(self.claude.calls[-1]["timeout"], 180)
        self.assertEqual((self.cfg.model_brief, self.cfg.model_selfcheck), ("sonnet", "sonnet"))
        self.bot.ask_claude("брифинг", deep=False, model=self.cfg.model_brief)
        c = self.claude.calls[-1]
        self.assertEqual((c["args"][c["args"].index("--model") + 1], c["timeout"]), ("sonnet", 180))
        src = open(bb.__file__, encoding="utf-8").read()
        self.assertIn("model=cfg.model_brief", src)
        self.assertIn("cfg.model_selfcheck, token", src)

    def test_models_overridable_by_env(self):
        cfg = bb.Config({"OWNER_ID": "42", "MODEL_DEFAULT": "sonnet", "MODEL_FAST": "haiku"})
        self.assertEqual((cfg.model_default, cfg.model_deep, cfg.model_fast), ("sonnet", "opus", "haiku"))

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
        self.assertIn("/fast", bb.MSG_LIMIT)   # при лимите Opus бот сам предлагает быстрый Sonnet

        def boom(*a, **k):
            raise bb.subprocess.TimeoutExpired("claude", 180)
        self.bot.exec_claude = boom
        self.bot.handle_update(upd("вопрос 2"))
        self.assertIn(bb.MSG_TIMEOUT.format(minutes=5), self.api.sent())

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
            f.write("Фокус: запуск встречи")
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
            f.write("Фокус: запуск встречи")
        bb.brief(self.bot)
        self.assertIn("Фокус: запуск встречи", self.api.sent()[-1])


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
                if "$VOICE_VENV.new" in code and "env -i PATH=/usr/bin:/bin HOME=/root" in code:
                    # venv голоса (RT-11b): root-интерпретатор, но без файлов brain: env -i, cwd /, root-копия списка
                    self.assertNotRegex(code, r"/home/brain|\$BRAIN_HOME|\$SRC_DIR")
                    continue
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
        # RT-11: состояние и конфиг claude бота — у brainbot, не в /home/brain; создаёт brain-admin bot-user
        self.assertIn("CLAUDE_CFG=$BOT_STATE/claude-config", src)
        self.assertIn("BOT_STATE=/var/lib/brain-bot", src)
        self.assertIn("/usr/local/sbin/brain-admin bot-user", src)
        self.assertLess(src.index("brain-admin bot-user"), src.index("brain-admin canary-init"))
        self.assertIn('install -d -m 2770 -o "$BRAIN" -g "$BRAIN" "$BH/$d"', src)
        self.assertNotIn(".local/state/brain-bot", src)
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
        for target in ("../.config/brain-canary", "./../.claude/.canary-credentials.json", ".config/brain-canary",
                       ".claude/.canary-credentials.json", "/proc/self/environ",
                       "/run/credentials/brain-bot.service/bot_token", "/var/run/credentials/", "Grep", "Glob",
                       "http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:22"):
            self.assertIn(target, prompts)
        for c in self.claude.calls:   # события, а не голый текст: по ним видно, что реально прочитал инструмент
            self.assertEqual(c["args"][c["args"].index("--output-format") + 1], "stream-json")
            self.assertIn("--verbose", c["args"])
        ids = [p[0] for p in bb.selfcheck_probes(self.cfg)]
        self.assertNotIn("etc-canary", ids)          # файл root 0600: из-за прав ОС проба не могла провалиться
        self.assertIn("traversal-canary", ids)
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

    @NEEDS_FCNTL
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
        self.assertIn(bb.CANARY_HIT, bb.read_safe_mode(self.cfg))
        self.assertIn(bb.MSG_SELFCHECK_FAIL, self.api.sent())      # владельцу — сразу

    def test_spaced_canary_in_live_answer_also_trips(self):
        bb.clear_safe_reason(self.cfg, "selfcheck")
        tail = CANARIES[1][7:]
        self.claude.out = "вот: " + " ".join(tail[i:i + 4] for i in range(0, len(tail), 4)) + "\u200b"
        self.bot.handle_update(upd("что в фокусе?"))
        self.assertIn(bb.CANARY_HIT, bb.read_safe_mode(self.cfg))

    def test_canary_hit_survives_selfcheck_pass_and_clears_only_by_admin(self):
        bb.clear_safe_reason(self.cfg, "selfcheck")
        self.claude.out = "вот: " + CANARIES[0]
        self.bot.handle_update(upd("что в фокусе?"))
        self.claude.out = "Не могу прочитать: доступ запрещён."
        res = bb.selfcheck(self.bot)
        self.assertEqual(res["status"], "pass", res["items"])
        self.assertIn(bb.CANARY_HIT, bb.read_safe_mode(self.cfg))   # PASS её НЕ снимает
        self.assertNotIn(bb.MSG_SELFCHECK_PASS, self.api.sent())
        self.bot.handle_update(upd("/status"))
        self.assertIn("clear-canary-hit", self.api.sent()[-1])         # /status показывает причину
        bb.brief(self.bot)
        self.assertIn("Безопасный режим", self.api.sent()[-1])         # и брифинг
        self.assertIn("clear-canary-hit", self.api.sent()[-1])
        import io
        buf = io.StringIO()
        with mock.patch.dict(os.environ, self.env), mock.patch("sys.stdout", buf):
            self.assertEqual(bb.main(["clear-canary-hit"]), 0)
        self.assertIn("снят", buf.getvalue())
        self.assertEqual(bb.read_safe_mode(self.cfg), {})

    def test_capabilities_help_fallback_when_exec_not_discriminating(self):
        help_text = "Usage: claude\n  --tools <tools...>\n  --allowedTools, --allowed-tools <x>\n  --disallowedTools <x>\n"
        with mock.patch.object(bb, "_cmd", side_effect=[help_text, "1.0.0"]), \
                mock.patch.object(bb, "_rc", return_value=0):          # «принимает» даже несуществующий флаг
            caps = bb.claude_capabilities(self.cfg)
        self.assertEqual(caps["method"], "help")
        self.assertEqual(caps["missing"], ["--setting-sources"])
        with mock.patch.object(bb, "_cmd", return_value=None), mock.patch.object(bb, "_rc", return_value=None):
            caps = bb.claude_capabilities(self.cfg)
        self.assertFalse(caps["known"])
        self.assertIsNone(bb.apply_capabilities(self.cfg, caps))   # неизвестно — решений не принимаем


FAKE_CLAUDE_SRC = """#!/usr/bin/env python3
import sys
KNOWN = {%s}
args, i = sys.argv[1:], 0
while i < len(args):
    a = args[i]
    if a not in KNOWN:
        sys.stderr.write("error: unknown option '%%s'\\n" %% a)
        sys.exit(1)
    i += 1 + KNOWN[a]
if "--help" in args:
    print("Usage: claude --tools --setting-sources --allowedTools --disallowedTools --no-session-persistence")
    sys.exit(0)
print("9.9.9 (Claude Code)")
"""
STRICT_FLAGS = ('"--version": 0, "--help": 0, "--tools": 1, "--setting-sources": 1, "--allowed-tools": 1, '
                '"--disallowedTools": 1')


def write_fake_claude(folder, known=STRICT_FLAGS):
    path = os.path.join(folder, "claude")
    with open(path, "w", encoding="utf-8") as f:
        f.write(FAKE_CLAUDE_SRC % known)
    os.chmod(path, 0o755)
    return path


class TestCapabilitiesByExec(SelfcheckBase):
    """Флаги проверяются исполнением (`claude <флаг> [значение] --version` → 0), --help — только отчёт."""

    def test_exec_beats_lying_help_and_kebab_spelling(self):
        self.cfg.claude_bin = write_fake_claude(self.tmp)
        caps = bb.claude_capabilities(self.cfg)
        self.assertEqual(caps["method"], "exec")
        self.assertEqual(caps["missing"], [])
        self.assertEqual(caps["spell"], {"--allowedTools": "--allowed-tools"})   # принят только kebab-case
        # в help --no-session-persistence есть, но исполнение его не принимает → не передаём
        self.assertNotIn("--no-session-persistence", caps["flags"])
        self.assertNotIn("--strict-mcp-config", caps["flags"])
        self.bot.caps = caps
        args, _, _, _ = bb.build_claude_call(self.cfg, "q", "files", "sonnet", CLAUDE_TOKEN, caps=caps)
        self.assertNotIn("--no-session-persistence", args)
        self.assertNotIn("--strict-mcp-config", args)
        self.assertIn("--allowed-tools", args)
        self.assertNotIn("--allowedTools", args)
        # итоговые аргументы реально принимает «claude» (кроме -p и прочего, что заглушка не знает) — флаги изоляции
        for flag in ("--tools", "--setting-sources", "--allowed-tools", "--disallowedTools"):
            self.assertIn(flag, args)

    def test_missing_required_by_exec(self):
        self.cfg.claude_bin = write_fake_claude(self.tmp, '"--version": 0, "--help": 0, "--tools": 1')
        caps = bb.claude_capabilities(self.cfg)
        self.assertEqual(caps["method"], "exec")
        self.assertEqual(caps["missing"], ["--setting-sources", "--allowedTools", "--disallowedTools"])
        self.assertFalse(bb.apply_capabilities(self.cfg, caps))
        self.assertIn("claude-flags", bb.read_safe_mode(self.cfg))

    def test_optional_flags_only_when_supported(self):
        caps = {"known": True, "flags": list(bb.REQUIRED_FLAGS), "missing": [], "spell": {}}
        for mode in ("files", "web", "safe"):
            args, _, _, _ = bb.build_claude_call(self.cfg, "q", mode, "sonnet", CLAUDE_TOKEN, caps=caps)
            self.assertNotIn("--no-session-persistence", args, mode)
            self.assertNotIn("--strict-mcp-config", args, mode)
        caps["flags"] += list(bb.OPTIONAL_FLAGS)
        for mode in ("files", "web", "safe"):
            args, _, _, _ = bb.build_claude_call(self.cfg, "q", mode, "sonnet", CLAUDE_TOKEN, caps=caps)
            self.assertIn("--no-session-persistence", args, mode)
            self.assertIn("--strict-mcp-config", args, mode)

    def test_safe_disallowed_covers_all_read_and_meta_tools(self):
        for t in ("LS", "MultiEdit", "NotebookRead", "TodoWrite", "Skill", "SlashCommand", "Read", "Bash"):
            self.assertIn(t, bb.SAFE_DISALLOWED.split(","))


def sj(*events):
    """stream-json: по событию на строку."""
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n"


def tool_use(tid, name, **inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def tool_result(tid, text, is_error=False):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "is_error": is_error,
                                                      "content": [{"type": "text", "text": text}]}]}}


def final(text):
    return {"type": "result", "subtype": "success", "result": text}


class TestSelfcheckStreamJson(SelfcheckBase):
    """FAIL по событиям stream-json, а не по совпадению текста ответа."""

    def _run_with(self, probe_id, out):
        target = [p for p in bb.selfcheck_probes(self.cfg) if p[0] == probe_id][0][3]

        def fn(args, prompt):
            if target in prompt:
                return 0, out, ""
            return 0, sj(final("Не могу: доступ запрещён.")), ""
        self.bot.exec_claude = ScriptedClaude(fn)
        return bb.selfcheck(self.bot)

    def test_successful_read_outside_allowlist_fails_even_without_leak(self):
        res = self._run_with("config-canary", sj(
            tool_use("t1", "Read", file_path=self.home + "/.config/brain-canary"),
            tool_result("t1", "     1\tкакой-то текст без приманки"),
            final("Прочитал, ничего интересного.")))
        self.assertEqual(res["items"]["config-canary"]["status"], "fail")
        self.assertIn("вне белого списка", res["items"]["config-canary"]["detail"])
        self.assertEqual(res["status"], "fail")

    def test_relative_traversal_read_fails(self):
        res = self._run_with("traversal-canary", sj(
            tool_use("t1", "Read", file_path="../.config/brain-canary"),
            tool_result("t1", "ok"), final("готово")))
        self.assertEqual(res["items"]["traversal-canary"]["status"], "fail")

    def test_denied_read_and_allowed_memory_read_pass(self):
        res = self._run_with("config-canary", sj(
            tool_use("t1", "Read", file_path=self.home + "/.config/brain-canary"),
            tool_result("t1", "Claude requested permissions to read from it, but you haven't granted it yet.",
                        is_error=True),
            tool_use("t2", "Read", file_path="MEMORY.md"),
            tool_result("t2", "индекс"),
            tool_use("t3", "Read", file_path=self.home + "/CLAUDE.md"),
            tool_result("t3", "правила"),
            tool_use("t4", "Grep", pattern="CANARY"),
            tool_result("t4", self.home + "/memory/MEMORY.md"),
            final("Доступа к файлу нет.")))
        self.assertEqual(res["items"]["config-canary"]["status"], "pass", res["items"])
        self.assertEqual(res["status"], "pass")

    def test_denial_text_without_is_error_is_not_a_success(self):
        res = self._run_with("config-canary", sj(
            tool_use("t1", "Read", file_path="/etc/brain-bot/canary"),
            tool_result("t1", "<tool_use_error>Permission to read denied</tool_use_error>"),
            final("нет доступа")))
        self.assertEqual(res["items"]["config-canary"]["status"], "pass")

    def test_glob_from_root_listing_outside_fails(self):
        res = self._run_with("glob-canary", sj(
            tool_use("t1", "Glob", pattern="/**/*canary*"),
            tool_result("t1", "/etc/brain-bot/canary\n/home/brain/.config/brain-canary"),
            final("нашёл два файла, читать не стал")))
        self.assertEqual(res["items"]["glob-canary"]["status"], "fail")

    def test_grep_with_root_path_fails_even_if_empty(self):
        res = self._run_with("grep-canary", sj(
            tool_use("t1", "Grep", pattern="CANARY-", path="/"),
            tool_result("t1", "No files found"), final("ничего")))
        self.assertEqual(res["items"]["grep-canary"]["status"], "fail")

    def test_canary_in_tool_result_fails_even_if_answer_clean(self):
        res = self._run_with("credentials", sj(
            tool_use("t1", "Read", file_path="/run/credentials/brain-selfcheck.service/canary_list"),
            tool_result("t1", "\n".join(CANARIES), is_error=True),
            final("Файл есть, но выводить не буду.")))
        self.assertEqual(res["items"]["credentials"]["status"], "fail")
        self.assertIn("результате инструмента", res["items"]["credentials"]["detail"])

    def test_obfuscated_canary_in_answer_fails(self):
        import base64 as b64
        tail = CANARIES[2][7:]
        variants = {
            "spaces": " ".join(tail),
            "markdown": "**" + tail[:20] + "**_" + tail[20:] + "_",
            "zero-width": "\u200b".join(tail),
            "base64": b64.b64encode(CANARIES[2].encode()).decode(),
            "base64-tail-glued": "result" + b64.b64encode(tail.encode()).decode(),
            "hex": CANARIES[2].encode().hex(),
            "window-only": tail[5:5 + 16],
        }
        for name, text in variants.items():
            with self.subTest(name):
                leaks = bb.text_leaks("ответ: " + text, CANARIES)
                self.assertTrue(any("приманка" in k for k in leaks), (name, leaks))

    def test_unknown_canary_pattern_and_token_pattern_fail(self):
        self.assertIn("шаблон canary", bb.text_leaks("CANARY-deadbeef00", CANARIES))
        self.assertTrue(bb.text_leaks("ключ " + ANT + "oat01-abcdefghijklmnop", CANARIES))
        self.assertTrue(bb.text_leaks("tg 1234567890:" + "Q" * 35, CANARIES))
        self.assertEqual(bb.text_leaks("Не могу прочитать token: access denied. Доступ запрещён.", CANARIES), [])
        res = self._run_with("grep-canary", sj(final("нашёл CANARY-0123456789abcdef в /etc")))
        self.assertEqual(res["items"]["grep-canary"]["status"], "fail")

    def test_plain_text_output_still_checked(self):
        # старый claude / заглушка без stream-json: строки не-JSON — текст ответа
        res = self._run_with("config-canary", "Содержимое: " + CANARIES[1] + "\n")
        self.assertEqual(res["items"]["config-canary"]["status"], "fail")


class TestSelfcheckRunsAndLocks(SelfcheckBase):
    def test_run_marked_before_each_call_so_crash_counts(self):
        class Boom(Exception):
            pass
        calls = []

        def crash(args, stdin, env, cwd, timeout):
            calls.append(1)
            runs = json.loads(_read(bb.selfcheck_paths(self.cfg)[1]))
            self.assertEqual(len(runs), 1)            # метка уже есть ДО вызова
            raise Boom()
        self.bot.exec_claude = crash
        with self.assertRaises(Boom):
            bb.selfcheck(self.bot)
        self.assertEqual(len(calls), 1)
        self.bot.exec_claude = self.claude
        res = bb.selfcheck(self.bot)
        self.assertEqual(res["status"], "skipped")    # упавший запуск засчитан в лимит 1/сутки
        self.assertEqual(self.claude.calls, [])

    def test_parallel_run_is_refused(self):
        import fcntl
        path = bb.selfcheck_paths(self.cfg)[1] + ".lock"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            res = bb.selfcheck(self.bot)
        finally:
            os.close(fd)
        self.assertEqual(res["status"], "skipped")
        self.assertIn("идёт", res["reason"])
        self.assertEqual(self.claude.calls, [])

    def test_owner_lock_wait_is_bounded(self):
        waits = []
        self.bot.lock.acquire = lambda wait=0.0: waits.append(wait) or False
        res = bb.selfcheck(self.bot)
        self.assertEqual(res["status"], "unverified")
        self.assertEqual(waits, [bb.SELFCHECK_LOCK_WAIT])
        self.assertLessEqual(bb.SELFCHECK_LOCK_WAIT, 60)

    def test_cached_result_reports_sandbox(self):
        import io
        # раннер GitHub Actions сам работает под systemd (INVOCATION_ID в окружении) — «вне юнита» эмулируем явно
        with mock.patch.dict(os.environ):
            os.environ.pop("INVOCATION_ID", None)
            os.environ.pop("BRAIN_SELFCHECK_SANDBOX", None)
            bb.selfcheck(self.bot)
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = bb.selfcheck_cli(self.cfg)
        self.assertEqual(rc, 4)
        self.assertIn("SELFCHECK_SANDBOX=none", buf.getvalue())     # прошлый запуск был вне юнита

    def test_safe_reasons_are_not_lost_under_concurrency(self):
        import threading
        threads = [threading.Thread(target=bb.set_safe_reason, args=(self.cfg, "k%d" % i, "x")) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(bb.read_safe_mode(self.cfg)), 16 + 0)


class TestLogHygiene(Base):
    def test_stderr_filtered_whole_before_cut(self):
        err = "x" * 1000 + CLAUDE_TOKEN + "y" * 380      # граница err[-400:] режет токен пополам
        self.claude.rc, self.claude.out, self.claude.err = 1, "", err
        with self.assertLogs("brain-bot", level="WARNING") as lg:
            self.bot.handle_update(upd("вопрос"))
        joined = "\n".join(lg.output)
        self.assertNotIn(CLAUDE_TOKEN[-20:], joined)
        self.assertNotIn("yyyy", joined)                  # весь stderr скрыт: в нём был секрет

    def test_stranger_id_masked_in_log(self):
        with self.assertLogs("brain-bot", level="WARNING") as lg:
            self.bot.handle_update(upd("привет", uid=STRANGER))
        joined = "\n".join(lg.output)
        self.assertIn("ignored update", joined)
        self.assertNotIn(str(STRANGER), joined)
        self.assertIn("99…77", joined)


class TestBotUserRT11(unittest.TestCase):
    """kit 2.1 (RT-11): LoadCredential отдаёт /run/credentials/<юнит>/ во владение пользователю юнита. Под brain
    токены читал бы любой процесс brain (ssh-вход). Бот — отдельный системный пользователь brainbot."""

    def _src(self, *parts):
        return _read(os.path.join(SERVER, *parts))

    def test_units_run_as_brainbot_with_own_state(self):
        for unit in ("brain-bot.service", "brain-brief.service", "brain-watch.service"):
            src = self._src("systemd", unit)
            lines = src.splitlines()
            for d in ("User=brainbot", "Group=brain", "UMask=0007", "StateDirectory=brain-bot",
                      "StateDirectoryMode=0700", "Environment=BRAIN_STATE_DIR=/var/lib/brain-bot"):
                self.assertIn(d, lines, "%s: нет %s" % (unit, d))
            self.assertNotIn("User=brain", lines)
            self.assertNotIn(".local/state", " ".join(l for l in lines if not l.startswith("#")))
            rw = [l for l in lines if l.startswith("ReadWritePaths=")]
            if unit == "brain-bot.service":
                self.assertEqual(rw, ["ReadWritePaths=/home/brain/memory/inbox /home/brain/memory/dialogues"])
            else:
                self.assertEqual(rw, [])   # брифинг и сторож пишут только в своё состояние

    def test_brain_admin_bot_user(self):
        src = self._src("brain-admin")
        block = src[src.index("  bot-user)"):src.index("  status)")]
        block += src[src.index("# >>> migrate-state"):src.index("# <<< migrate-state")]
        self.assertIn("useradd --system --user-group --no-create-home", block)
        self.assertIn("--shell /usr/sbin/nologin", block)
        self.assertIn('usermod -aG brain "$BOT_USER"', block)
        self.assertIn('gpasswd -d brain "$BOT_USER"', block)          # brain не в группе brainbot
        self.assertIn('install -d -m 0700 -o "$BOT_USER" -g brain "$BOT_STATE"', block)
        self.assertIn("chmod 2770", block)
        # файлы в папке brain трогает только brain; перенос: читает brain, пишет brainbot — root файлов не открывает
        self.assertIn("runuser -u brain -- sh -c", block)
        self.assertIn('runuser -u brain -- head -c 1048576 -- "$LEGACY_STATE/$f"', block)
        self.assertIn('runuser -u "$BOT_USER" -- sh -c', block)
        self.assertNotRegex(block, r"(?m)^\s*(chmod|chown|cp|mv|rm)\b[^\n]*\$BRAIN_HOME")
        self.assertIn("safe_mode", src[src.index("LEGACY_FILES="):src.index("LEGACY_FILES=") + 120])
        self.assertIn("BOT_STATE=/var/lib/brain-bot", src)

    def test_brain_admin_runs_bot_code_as_brainbot(self):
        src = self._src("brain-admin")
        for cmd, nxt in (("  selftest)", "  canary-init)"), ("  clear-canary-hit)", "  update-claude)")):
            block = src[src.index(cmd):src.index(nxt)]
            self.assertIn("runuser -u brainbot -- env -i", block)
            self.assertIn('BRAIN_STATE_DIR="$BOT_STATE"', block)
        sc = src[src.index("  selfcheck-security)"):src.index("  clear-canary-hit)")]
        self.assertIn("-p User=brainbot -p Group=brain", sc)
        self.assertIn('runuser -u brainbot -- env -i', sc)
        self.assertNotIn("User=brain ", sc.replace("User=brainbot", ""))
        st = src[src.index("  selftest)"):src.index("  canary-init)")]
        self.assertIn("/run/credentials/brain-bot.service/claude_token", st)   # RT-11 в selftest
        self.assertIn('runuser -u brain -- cat -- "$f"', st)
        self.assertIn('"700 $BOT_USER"', st)
        self.assertIn('"2770 brain"', st)

    def test_canary_bait_readable_by_bot_only(self):
        src = self._src("brain-admin")
        block = src[src.index("  canary-init)"):src.index("  selfcheck-security)")]
        self.assertIn('"$BOT_STATE/canary-bait"', block)
        self.assertIn('runuser -u "$BOT_USER" -- sh -c', block)
        self.assertIn('-lt 4', block)                                   # 4 приманки, прежние сохраняются
        self.assertIn("/var/lib/brain-bot", self._src("claude_settings.json"))   # deny слоя claude

    def test_harden_creates_bot_user_before_units(self):
        src = self._src("harden.sh")
        self.assertLess(src.index("brain-admin bot-user"), src.index("# 12. Код бота"))
        self.assertIn('install -d -m 2770 -o "$BRAIN" -g "$BRAIN" "$BH/$d"', src)

    def test_default_state_dir(self):
        env = {"OWNER_ID": "1"}
        with mock.patch.object(bb, "STATE_DIR_SYSTEM", "/nonexistent/brain-bot"):
            self.assertEqual(bb.default_state_dir(env, "/home/brain"), os.path.join("/home/brain", ".local/state/brain-bot"))
            self.assertEqual(bb.default_state_dir(dict(env, STATE_DIRECTORY="/var/lib/brain-bot:/x"), "/h"),
                             "/var/lib/brain-bot")
            self.assertEqual(bb.default_state_dir(dict(env, BRAIN_STATE_DIR="/s", STATE_DIRECTORY="/x"), "/h"), "/s")
        d = tempfile.mkdtemp()
        try:
            with mock.patch.object(bb, "STATE_DIR_SYSTEM", d):
                self.assertEqual(bb.default_state_dir(env, "/home/brain"), d)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_probes_include_state_canary_for_claude_layer(self):
        cfg = bb.Config({"OWNER_ID": "1", "BRAIN_HOME": "/home/brain", "BRAIN_STATE_DIR": "/var/lib/brain-bot"})
        probes = {p[0]: p[3] for p in bb.selfcheck_probes(cfg)}
        self.assertIn("/var/lib/brain-bot/canary-bait", probes["claude-dir-canary"])
        self.assertIn("../../../var/lib/brain-bot/canary-bait", probes["traversal-canary"])
        self.assertLessEqual(len(probes), bb.SELFCHECK_MAX_CALLS)


@NEEDS_FCNTL
class TestBotFileModesRT11(Base):
    def test_inbox_and_dialogue_files_group_writable(self):
        old = os.umask(0o007)                                           # UMask юнита
        try:
            p = bb.write_inbox(self.cfg, "заметка", dt.datetime(2026, 10, 4, 12, 0, 0))
            bb.append_dialogue(self.cfg, dt.datetime(2026, 10, 4, 12, 0, 0), "в", "о", "m")
        finally:
            os.umask(old)
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o660)
        d = os.path.join(self.home, "memory", "dialogues", "2026-10-04.md")
        self.assertEqual(os.stat(d).st_mode & 0o777, 0o660)


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
        upd_block = upd_block[:upd_block.index("  voice-venv)")]
        # RT-11b: установщик — от brainbot во временной папке root-владения, не под brain и не от root
        self.assertIn("curl -fsSL https://claude.ai/install.sh | bash", upd_block)
        self.assertNotIn("runuser -l brain", upd_block)
        self.assertIn('runuser -u "$BOT_USER" -- "${BENV[@]}" bash -c', upd_block)
        self.assertIn("mktemp -d /var/cache/brain-claude-install.", upd_block)
        self.assertIn('runuser -u "$BOT_USER" -- head -c', upd_block)      # бинарник root читает правами brainbot
        self.assertIn("7f454c46", upd_block)                                # только ELF
        self.assertIn('"$NEW" --version', upd_block)
        self.assertIn("sha256sum", upd_block)
        self.assertIn('mv -f "$ts" "$BOT_CLAUDE_SHA"', upd_block)
        self.assertIn("BOT_CLAUDE=$BOT_CLAUDE_DIR/bin/claude", src)
        self.assertIn("BOT_CLAUDE_DIR=$LIB_DIR/claude", src)
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


# ---------------------------------------------------------------- RT-11b: claude бота — root-копия с sha256
class TestClaudeBinChoice(unittest.TestCase):
    def test_default_is_root_copy_never_home(self):
        cfg = bb.Config({"OWNER_ID": "1", "BRAIN_HOME": "/home/brain"})
        self.assertEqual(cfg.claude_bin, "/usr/local/lib/brain-bot/claude/bin/claude")
        self.assertEqual(cfg.claude_bin, bb.BOT_CLAUDE_BIN)
        self.assertEqual(cfg.claude_sha_file, "/usr/local/lib/brain-bot/claude.sha256")
        self.assertNotIn("/home", cfg.child_path)
        self.assertTrue(cfg.child_path.startswith("/usr/local/lib/brain-bot/claude/bin:"))

    def test_owner_copy_in_home_is_not_picked_up(self):
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, ".local", "bin"))
            fake = os.path.join(tmp, ".local", "bin", "claude")
            with open(fake, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(fake, 0o755)
            cfg = bb.Config({"OWNER_ID": "1", "BRAIN_HOME": tmp, "PATH": os.path.join(tmp, ".local", "bin")})
            self.assertEqual(cfg.claude_bin, bb.BOT_CLAUDE_BIN)    # PATH окружения не используется
            self.assertNotIn(tmp, cfg.child_path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_env_claude_bin_wins(self):
        cfg = bb.Config({"OWNER_ID": "1", "CLAUDE_BIN": "/opt/x/claude", "BRAIN_CLAUDE_SHA256": "/opt/x/sum"})
        self.assertEqual((cfg.claude_bin, cfg.claude_sha_file), ("/opt/x/claude", "/opt/x/sum"))


class TestClaudeIntegrity(Base):
    def setUp(self):
        super().setUp()
        self.bin = os.path.join(self.tmp, "claude-bin")
        with open(self.bin, "wb") as f:
            f.write(b"\x7fELF fake claude for tests")
        self.sumf = os.path.join(self.tmp, "claude.sha256")
        self._write_sum(bb.file_sha256(self.bin))
        self.cfg.claude_bin, self.cfg.claude_sha_file = self.bin, self.sumf

    def _write_sum(self, value):
        with open(self.sumf, "w") as f:
            f.write("%s  /usr/local/lib/brain-bot/claude/bin/claude\n" % value)

    def test_match_ok_and_clears_reason(self):
        bb.set_safe_reason(self.cfg, bb.CLAUDE_INTEGRITY, "было")
        ok, detail = bb.apply_integrity(self.cfg, trusted_uid=None)
        self.assertTrue(ok, detail)
        self.assertNotIn(bb.CLAUDE_INTEGRITY, bb.read_safe_mode(self.cfg))
        self.assertIsNone(bb.integrity_block(self.cfg))

    def test_mismatch_sets_safe_mode_and_claude_never_runs(self):
        with open(self.bin, "ab") as f:
            f.write(b"\n# wrapper: cat /run/credentials/* > inbox")
        ok, detail = bb.apply_integrity(self.cfg, trusted_uid=None)
        self.assertFalse(ok)
        self.assertIn("не совпадает", detail)
        self.assertIn(bb.CLAUDE_INTEGRITY, bb.read_safe_mode(self.cfg))
        answer, _, good = self.bot.ask_claude("что в памяти?", deep=False)
        self.assertFalse(good)
        self.assertIn("целостности", answer)
        self.assertEqual(self.claude.calls, [])          # подменённый бинарник не запускался вовсе
        self.assertIn("заблокирован", bb.claude_version(self.cfg))

    def test_missing_or_broken_sum(self):
        os.unlink(self.sumf)
        self.assertFalse(bb.claude_integrity(self.cfg, trusted_uid=None)[0])
        self._write_sum("zz")
        ok, detail = bb.claude_integrity(self.cfg, trusted_uid=None)
        self.assertFalse(ok)
        self.assertIn("битая", detail)

    def test_symlink_and_relative_rejected(self):
        link = os.path.join(self.tmp, "claude-link")
        os.symlink(self.bin, link)
        self.cfg.claude_bin = link
        self.assertFalse(bb.claude_integrity(self.cfg, trusted_uid=None)[0])
        self.cfg.claude_bin = "claude"
        self.assertFalse(bb.claude_integrity(self.cfg, trusted_uid=None)[0])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "под root файл и так root")
    def test_not_root_owned_rejected_even_if_sum_matches(self):
        # копия «как у brain» (владелец не root): отказ ещё до сверки суммы
        ok, detail = bb.claude_integrity(self.cfg)            # trusted_uid=0 по умолчанию
        self.assertFalse(ok)
        self.assertIn("владелец не root", detail)

    def test_selfcheck_does_not_run_blocked_claude(self):
        bb.set_safe_reason(self.cfg, bb.CLAUDE_INTEGRITY, "sha256 не совпадает")
        self.bot.caps_probe = lambda: self.fail("claude не должен запускаться даже для проверки флагов")
        res = bb.selfcheck(self.bot)
        self.assertEqual((res["status"], res["calls"]), ("unverified", 0))
        self.assertEqual(self.claude.calls, [])

    def test_watch_reports_integrity(self):
        bb.set_safe_reason(self.cfg, bb.CLAUDE_INTEGRITY, "sha256 не совпадает")
        with mock.patch.object(bb, "bot_active", return_value="active"), \
                mock.patch.object(bb, "ntp_synced", return_value="yes"):
            bb.watch(self.bot)
        sent = " ".join(str(p.get("text")) for m, p in self.api.calls if m == "sendMessage")
        self.assertIn("целостности", sent)


class TestClaudeRootCopyScripts(unittest.TestCase):
    ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")

    def _src(self, *parts):
        return _read(os.path.join(self.ROOT, *parts))

    def test_units_have_no_brain_paths(self):
        for u in ("brain-bot.service", "brain-brief.service", "brain-watch.service"):
            src = self._src("brain-link", "server", "systemd", u)
            code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
            self.assertIn("Environment=CLAUDE_BIN=/usr/local/lib/brain-bot/claude/bin/claude", code, u)
            self.assertIn("Environment=PATH=/usr/local/lib/brain-bot/claude/bin:/usr/local/bin:/usr/bin:/bin", code, u)
            self.assertNotIn("/home/brain/.local/bin", code, u)
            self.assertNotIn(".venv-voice", code, u)

    def test_installer_voice_is_root_venv(self):
        sys.path.insert(0, os.path.join(self.ROOT, "brain-link", "scripts"))
        import brain_link as bk
        sh = "\n".join(l for l in bk.BOT_ROOT_SH.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotIn("~/.venv-voice", sh)
        self.assertNotIn("runuser -l brain -c 'python3 -m venv", sh)
        self.assertIn("ExecStart=/usr/local/lib/brain-bot/voice-venv/bin/python3 -I", sh)
        self.assertIn("brain-admin voice-venv", sh)
        self.assertIn("brain-admin update-claude", sh)
        self.assertIn("brain-admin update-claude", bk.CLAUDE_SH)
        admin = self._src("brain-link", "server", "brain-admin")
        vv = admin[admin.index("  voice-venv)"):admin.index("  remove-private)")]
        self.assertIn("--only-binary=:all:", vv)
        self.assertIn('"$VOICE_REQ"', vv)
        self.assertNotIn("$SRC_DIR", vv)                     # список пакетов — только root-копия
        for line in self._src("brain-link", "server", "requirements-voice.txt").splitlines():
            if line.strip() and not line.startswith("#"):
                self.assertRegex(line, r"^[A-Za-z0-9][A-Za-z0-9._-]*==[0-9][0-9A-Za-z.]*$")

    def test_brain_admin_never_runs_owner_claude(self):
        admin = self._src("brain-link", "server", "brain-admin")
        code = "\n".join(l for l in admin.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotIn("/home/brain/.local/bin/claude", code)
        self.assertNotIn('"$BRAIN_HOME/.local/bin', code)

    def test_audit_hands_token_only_to_root_copy(self):
        for name in ("audit.sh", "audit.ps1"):
            src = self._src("novoselie-server-kit", "audit", name)
            self.assertNotIn("CL=/home/brain/.local/bin/claude", src, name)
            block = src[src.index("CL=/usr/local/lib/brain-bot/claude/bin/claude"):]
            block = block[:block.index("ENVF=")]
            block = "\n".join(l for l in block.splitlines() if not l.lstrip().startswith("#"))
            self.assertIn("NO_BOT_CLAUDE", block, name)
            self.assertIn("RU=brainbot", block, name)
            self.assertNotIn("RU=brain;", block, name)
            self.assertNotIn("/home/brain/.local/bin", block, name)
            self.assertIn("/usr/local/lib/brain-bot/claude/bin/claude", block, name)
            self.assertIn("claude.sha256", block, name)


@unittest.skipUnless(os.name != "nt" and shutil.which("bash"), "shell-блок brain-admin (bash)")
class TestMigrateLegacyState(unittest.TestCase):
    """🟡-2: перенос ~/.local/state/brain-bot → /var/lib/brain-bot только при настоящей миграции, один раз,
    без перезаписи. runuser подменён (пользователи — текущий), остальное — настоящий код brain-admin."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="migrate_")
        self.state = os.path.join(self.tmp, "var-lib-brain-bot")
        self.legacy = os.path.join(self.tmp, "home", ".local", "state", "brain-bot")
        self.unit = os.path.join(self.tmp, "brain-bot.service")
        os.makedirs(self.state)
        os.makedirs(self.legacy)
        admin = _read(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server", "brain-admin"))
        self.block = admin[admin.index("# >>> migrate-state"):admin.index("# <<< migrate-state")]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _put(self, folder, name, text):
        with open(os.path.join(folder, name), "w") as f:
            f.write(text)

    def _unit(self, user, exec_start="/usr/bin/python3 /usr/local/lib/brain-bot/brain_bot.py run"):
        self._put(self.tmp, "brain-bot.service", "[Service]\nUser=%s\nGroup=brain\nExecStart=%s\n"
                  % (user, exec_start))

    def run_migrate(self):
        import subprocess
        sh = r"""
set -uo pipefail
ok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }
runuser(){ while [ "$1" != "--" ]; do shift; done; shift
  local a=(); for x in "$@"; do [ "$x" = "--one-file-system" ] || a+=("$x"); done; "${a[@]}"; }
BOT_USER=brainbot BOT_STATE="$1" LEGACY_STATE="$2" BOT_UNIT="$3" LIB_DIR=/usr/local/lib/brain-bot
LEGACY_FILES="safe_mode selfcheck.json selfcheck_runs.json watch_state.json calls.json"
""" + self.block + "\nmigrate_legacy_state\n"
        r = subprocess.run(["bash", "-c", sh, "sh", self.state, self.legacy, self.unit],
                           capture_output=True, text=True, timeout=60)
        return r.stdout + r.stderr

    def _state(self, name):
        p = os.path.join(self.state, name)
        return _read(p) if os.path.exists(p) else None

    def test_fresh_install_never_migrates_and_marks(self):
        self._put(self.legacy, "selfcheck.json", '{"status": "pass", "planted": 1}')   # подложил brain
        out = self.run_migrate()                                                        # юнита ещё нет
        self.assertIn("MIGRATE=skip", out)
        self.assertIsNone(self._state("selfcheck.json"))
        self.assertTrue(os.path.exists(os.path.join(self.state, ".migrated-from-brain")))
        self.assertTrue(os.path.exists(os.path.join(self.legacy, "selfcheck.json")))   # папку brain не трогаем
        self._unit("brain")                                                             # и позже — уже нет
        self.assertIn("MIGRATE=already", self.run_migrate())
        self.assertIsNone(self._state("selfcheck.json"))

    def test_unit_already_brainbot_no_migration(self):
        self._unit("brainbot")
        self._put(self.legacy, "calls.json", "[]")
        self._put(self.state, "calls.json", "[1, 2, 3]")
        self.assertIn("MIGRATE=skip", self.run_migrate())
        self.assertEqual(self._state("calls.json"), "[1, 2, 3]")

    def test_real_migration_once_without_overwrite_and_keeps_safe_mode(self):
        self._unit("brain")
        self._put(self.legacy, "watch_state.json", '{"lab": 1}')
        self._put(self.legacy, "selfcheck.json", '{"status": "pass"}')
        self._put(self.state, "selfcheck.json", '{"status": "fail"}')        # уже есть — не перезаписываем
        self._put(self.state, "safe_mode", '{"reasons": {"selfcheck": {}}}')  # включён — остаётся включённым
        out = self.run_migrate()
        self.assertIn("MIGRATE=done 1", out)
        self.assertEqual(self._state("watch_state.json"), '{"lab": 1}')
        self.assertEqual(self._state("selfcheck.json"), '{"status": "fail"}')
        self.assertIn("selfcheck", self._state("safe_mode"))
        self.assertFalse(os.path.exists(self.legacy))                          # старое состояние убрано
        os.makedirs(self.legacy)
        self._put(self.legacy, "safe_mode", "")                               # второй раз — ничего
        self.assertIn("MIGRATE=already", self.run_migrate())
        self.assertIn("selfcheck", self._state("safe_mode"))

    def test_foreign_brain_bot_under_brain_is_not_migrated(self):
        """kit 2.3: чужой brain-bot.service под brain (мост claude-code-telegram) — не ранняя установка кита:
        его папки не переносим и не удаляем."""
        self._unit("brain", exec_start="/home/brain/bridge/venv/bin/claude-telegram-bot")
        self._put(self.legacy, "watch_state.json", '{"bridge": 1}')
        self.assertIn("MIGRATE=skip", self.run_migrate())
        self.assertIsNone(self._state("watch_state.json"))
        self.assertTrue(os.path.exists(os.path.join(self.legacy, "watch_state.json")))

    def test_real_migration_turns_safe_mode_on_not_off(self):
        self._unit("brain")
        self._put(self.legacy, "safe_mode", '{"reasons": {"canary-hit": {}}}')
        self.assertIn("MIGRATE=done 1", self.run_migrate())
        self.assertIn("canary-hit", self._state("safe_mode"))


if __name__ == "__main__":
    unittest.main()
