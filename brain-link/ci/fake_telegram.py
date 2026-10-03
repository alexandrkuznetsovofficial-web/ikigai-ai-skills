#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fake_telegram.py — фейковый Telegram Bot API для лаборатории brain-link (GitHub Actions).

Бот получает адрес через TELEGRAM_API_BASE=http://127.0.0.1:<порт> (drop-in юнита в лаборатории).
Сервер принимает /bot<токен>/<метод> и /file/bot<токен>/<путь>; токен НИГДЕ не пишется — в состоянии
хранится только его sha256 (проверка «бот ходит с токеном из LoadCredential»). Журнал запросов — без пути.

Управление сценарием (без токена):
  POST /_ctl/update  {"from": <id>, "chat": <id>, "text": "..."}  → поставить входящее сообщение в очередь
  GET  /_ctl/sent                                               → что бот отправил, какие методы звал
Запуск: python3 fake_telegram.py --port 8081. Только стандартная библиотека.
"""
import argparse
import hashlib
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Condition()
STATE = {"updates": [], "next_id": 1, "sent": [], "methods": {}, "token_sha256": [], "msg_id": 100}


def _token_seen(token):
    sha = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if sha not in STATE["token_sha256"]:
        STATE["token_sha256"].append(sha)


class Handler(BaseHTTPRequestHandler):
    server_version = "fake-telegram/1"

    def log_message(self, fmt, *args):  # путь содержит токен — в журнал только метод и код
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except ValueError:
            return {}

    def do_GET(self):
        if self.path == "/_ctl/sent":
            with LOCK:
                return self._send(200, {"sent": list(STATE["sent"]), "methods": dict(STATE["methods"]),
                                        "token_sha256": list(STATE["token_sha256"]),
                                        "queued": len(STATE["updates"])})
        return self._api()

    def do_POST(self):
        if self.path == "/_ctl/update":
            req = self._body()
            with LOCK:
                uid = STATE["next_id"]
                STATE["next_id"] += 1
                frm, chat = int(req.get("from")), int(req.get("chat", req.get("from")))
                msg = {"message_id": uid, "date": int(time.time()), "text": req.get("text", ""),
                       "from": {"id": frm, "is_bot": False, "first_name": "Lab"},
                       "chat": {"id": chat, "type": "private" if chat > 0 else "group"}}
                STATE["updates"].append({"update_id": uid, "message": msg})
                LOCK.notify_all()
            return self._send(200, {"ok": True, "update_id": uid})
        return self._api()

    def _api(self):
        parts = self.path.split("?", 1)[0].strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "file" and parts[1].startswith("bot"):
            with LOCK:
                _token_seen(parts[1][3:])
            return self._send(404, {"ok": False, "error_code": 404, "description": "lab: no files"})
        if len(parts) != 2 or not parts[0].startswith("bot"):
            return self._send(404, {"ok": False, "error_code": 404, "description": "Not Found"})
        token, method = parts[0][3:], parts[1]
        params = self._body() if self.command == "POST" else {}
        with LOCK:
            _token_seen(token)
            STATE["methods"][method] = STATE["methods"].get(method, 0) + 1
        if method == "getUpdates":
            offset = int(params.get("offset") or 0)
            wait = min(float(params.get("timeout") or 0), 5.0)   # короткий long-poll: сценарий идёт быстрее
            deadline = time.time() + wait
            with LOCK:
                while True:
                    res = [u for u in STATE["updates"] if u["update_id"] >= offset]
                    if res or time.time() >= deadline:
                        break
                    LOCK.wait(timeout=max(0.05, deadline - time.time()))
                # подтверждённые (offset) больше не храним
                STATE["updates"] = [u for u in STATE["updates"] if u["update_id"] >= offset]
            return self._send(200, {"ok": True, "result": res})
        if method == "sendMessage":
            with LOCK:
                STATE["msg_id"] += 1
                STATE["sent"].append({"chat_id": params.get("chat_id"), "text": params.get("text", ""),
                                      "ts": time.time()})
                mid = STATE["msg_id"]
            return self._send(200, {"ok": True, "result": {"message_id": mid}})
        if method == "getMe":
            return self._send(200, {"ok": True, "result": {"id": 1, "is_bot": True, "username": "lab_fake_bot"}})
        if method == "getFile":
            return self._send(400, {"ok": False, "error_code": 400, "description": "lab: no files"})
        return self._send(200, {"ok": True, "result": True})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8081)
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    print("fake telegram on http://%s:%d" % (a.host, a.port), file=sys.stderr, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
