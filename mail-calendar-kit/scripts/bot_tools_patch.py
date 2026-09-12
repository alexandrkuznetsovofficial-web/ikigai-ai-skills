#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bot_tools_patch.py — подключает инструменты почты/календаря к личному боту стека A
(python-telegram-bot + Anthropic API, учебный шаблон с функцией ask_claude).

  --bot-file PATH --dry-run          показать, что изменится (diff), ничего не трогать
  --bot-file PATH --apply            бэкап → скопировать kit_tools.py рядом → заменить ask_claude → проверить компиляцию
  --bot-file PATH --check            только проверить, что файл бота компилируется
  --bot-file PATH --rollback         вернуть последний бэкап .bak.*
  [--bot-env PATH]                   дописать в .env бота MCK_PYTHON / MCK_DIR / MCK_ENV (если их нет)

Правила: якорь не найден → отказ целиком, ничего не подставляем; после --apply файл не компилируется → авто-откат.
Вывод — один JSON с полем "human".
"""
import argparse
import difflib
import os
import py_compile
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

HERE = Path(__file__).resolve().parent
ANCHOR_START = re.compile(r"^def ask_claude\((\w+)\):\s*$", re.M)
ANCHOR_END = re.compile(r"^\s+return response\.content\[0\]\.text\s*$", re.M)
IMPORT_ANCHOR = re.compile(r"^from anthropic import Anthropic\s*$", re.M)
IMPORT_LINE = "from kit_tools import KIT_TOOLS, kit_rules, run_kit_tool, has_pending, execute_pending, cancel_pending, is_yes, is_no"

NEW_FUNC = '''def ask_claude({arg}):
    """Ответ с инструментами почты и календаря (подключено паком mail-calendar-kit)."""
    text = ({arg} or '').strip()
    if has_pending():
        if is_yes(text):
            return _kit_result_text(execute_pending())
        if is_no(text):
            cancel_pending()
            return 'Отменил, ничего не отправлял.'
    memory_context = load_memory()
    system = 'Ты - личный помощник владельца. ' + kit_rules() + '\\n\\nПамять:\\n\\n' + memory_context
    messages = [{{'role': 'user', 'content': text}}]
    response = None
    for _ in range(6):
        response = claude.messages.create(
            model={model!r},
            max_tokens=2000,
            system=system,
            tools=KIT_TOOLS,
            messages=messages,
        )
        if response.stop_reason != 'tool_use':
            break
        messages.append({{'role': 'assistant', 'content': response.content}})
        results = []
        for block in response.content:
            if getattr(block, 'type', '') == 'tool_use':
                results.append({{'type': 'tool_result', 'tool_use_id': block.id,
                                'content': run_kit_tool(block.name, block.input)}})
        messages.append({{'role': 'user', 'content': results}})
    parts = [b.text for b in (response.content if response else []) if getattr(b, 'type', '') == 'text']
    return '\\n'.join(parts).strip() or '(пустой ответ)'


def _kit_result_text(raw):
    try:
        import json as _json
        d = _json.loads(raw)
        return d.get('human') or raw
    except Exception:
        return raw
'''


def compile_ok(path: Path) -> tuple[bool, str]:
    try:
        py_compile.compile(str(path), doraise=True)
        return True, ""
    except Exception as ex:
        return False, str(ex)[:300]


def build_patched(src: str) -> tuple[str, dict]:
    m1 = ANCHOR_START.search(src)
    if not m1:
        kitlib.fail(kitlib.EXIT_PROVIDER, "в файле бота нет функции `def ask_claude(...)` — это не учебный шаблон, патч не применяю. Подключай инструменты вручную по reference/bot_connect.md")
    m2 = ANCHOR_END.search(src, m1.end())
    if not m2:
        kitlib.fail(kitlib.EXIT_PROVIDER, "не нашёл строку `return response.content[0].text` после ask_claude — функция уже изменена, патч не применяю")
    # Якорь должен быть ПОСЛЕДНЕЙ строкой функции: иначе хвост старой функции (например, except-ветка)
    # приклеится к новому коду и всё это даже скомпилируется — молча сломанным.
    tail = src[m2.end():]
    if tail.strip() and not tail.lstrip("\n").startswith(("def ", "async def ", "class ", "@", "if __name__")):
        kitlib.fail(kitlib.EXIT_PROVIDER,
                    "функция ask_claude заканчивается не там, где ожидалось: после возврата ответа идёт ещё код "
                    "(например, обработка ошибок). Патч мог бы склеить куски и сломать бота молча, поэтому отказываюсь. "
                    "Подключай инструменты вручную по reference/bot_connect.md")
    # Новый код зовёт load_memory() и claude — если в шаблоне они называются иначе, бот упадёт при первом сообщении.
    missing = [n for n, rx in (("load_memory", r"def\s+load_memory\s*\("), ("claude", r"^\s*claude\s*="))
               if not re.search(rx, src, re.M)]
    if missing:
        kitlib.fail(kitlib.EXIT_PROVIDER,
                    f"в файле бота нет {' и '.join(missing)} — шаблон переписан, и новый код не заработает. "
                    f"Патч не применяю, подключай инструменты вручную по reference/bot_connect.md")
    arg = m1.group(1)
    mm = re.search(r"model\s*=\s*['\"]([^'\"]+)['\"]", src[m1.start():m2.end()])
    model = mm.group(1) if mm else "claude-sonnet-5"
    new_src = src[:m1.start()] + NEW_FUNC.format(arg=arg, model=model) + src[m2.end():].lstrip("\n")
    if "from kit_tools import" not in new_src:
        mi = IMPORT_ANCHOR.search(new_src)
        if mi:
            new_src = new_src[:mi.end()] + "\n" + IMPORT_LINE + new_src[mi.end():]
        else:
            new_src = IMPORT_LINE + "\n" + new_src
    return new_src, {"arg": arg, "model": model}


def ensure_env(bot_env: Path) -> list[str]:
    added = []
    # Имена свои, не общие: у пака про Telegram свои TPK_*, и общий KIT_DIR ученик,
    # прошедший оба урока, получил бы от того пака, который настроил первым.
    defaults = {
        "MCK_PYTHON": str(Path.home() / ".venvs" / "mck" /
                          ("Scripts/python.exe" if os.name == "nt" else "bin/python")),
        "MCK_DIR": str(Path.home() / ".claude" / "skills" / "mail-calendar-kit"),
        "MCK_ENV": str(Path.home() / ".config" / "mail-calendar-kit" / ".env"),
    }
    existing = bot_env.read_text(encoding="utf-8") if bot_env.exists() else ""
    lines = existing.splitlines()
    keys = {l.split("=", 1)[0].strip() for l in lines if "=" in l and not l.strip().startswith("#")}
    for k, v in defaults.items():
        if k not in keys:
            lines.append(f"{k}={v}")
            added.append(k)
    if added:
        bot_env.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            os.chmod(bot_env, 0o600)
        except Exception:
            pass
    return added


def main():
    p = kitlib.JsonArgumentParser(description="патч бота стека A")
    p.add_argument("--bot-file", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true"); g.add_argument("--apply", action="store_true")
    g.add_argument("--check", action="store_true"); g.add_argument("--rollback", action="store_true")
    p.add_argument("--bot-env")
    args = p.parse_args()
    bot = Path(args.bot_file).expanduser().resolve()
    if not bot.exists():
        kitlib.fail(kitlib.EXIT_CONFIG, f"файла {bot} нет")

    if args.check:
        ok, err = compile_ok(bot)
        kitlib.out({"compiles": ok, "error": err, "human": "файл бота компилируется" if ok else f"файл бота НЕ компилируется: {err}"},
                   kitlib.EXIT_OK if ok else kitlib.EXIT_PROVIDER)

    if args.rollback:
        baks = sorted(bot.parent.glob(bot.name + ".bak.*"))
        if not baks:
            kitlib.fail(kitlib.EXIT_CONFIG, "бэкапов .bak.* рядом с файлом бота нет")
        shutil.copy2(baks[-1], bot)
        ok, err = compile_ok(bot)
        kitlib.out({"restored_from": str(baks[-1]), "compiles": ok,
                    "human": f"вернул {baks[-1].name}" + ("" if ok else f", но файл не компилируется: {err}")})

    src = bot.read_text(encoding="utf-8")
    ok_before, err_before = compile_ok(bot)
    if not ok_before:
        kitlib.fail(kitlib.EXIT_PROVIDER, f"файл бота не компилируется ещё ДО патча: {err_before}. Сначала почини бота (или возьми свежий шаблон), потом подключай инструменты")
    if "from kit_tools import" in src and "KIT_TOOLS" in src:
        kitlib.out({"already": True, "human": "инструменты уже подключены к этому боту — патч не нужен"})
    new_src, meta = build_patched(src)
    diff = "".join(difflib.unified_diff(src.splitlines(True), new_src.splitlines(True), "main.py (было)", "main.py (станет)", n=2))

    if args.dry_run:
        kitlib.out({"dry_run": True, "model": meta["model"], "diff": diff[:6000],
                    "will_copy": str(bot.parent / "kit_tools.py"),
                    "human": f"патч применим: заменю ask_claude на версию с инструментами (модель {meta['model']}), рядом положу kit_tools.py. Ничего не изменено."})

    # --apply
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = bot.with_name(bot.name + f".bak.{stamp}")
    shutil.copy2(bot, bak)
    shutil.copy2(HERE / "bot_tools_block.py", bot.parent / "kit_tools.py")
    bot.write_text(new_src, encoding="utf-8")
    ok_after, err_after = compile_ok(bot)
    if not ok_after:
        shutil.copy2(bak, bot)
        kitlib.fail(kitlib.EXIT_PROVIDER, f"после патча файл не компилируется ({err_after}) — вернул бэкап {bak.name}, ничего не изменено")
    added = ensure_env(Path(args.bot_env).expanduser()) if args.bot_env else []
    kitlib.out({"applied": True, "backup": str(bak), "kit_tools": str(bot.parent / "kit_tools.py"),
                "model": meta["model"], "env_added": added,
                "human": f"инструменты подключены; бэкап {bak.name}; перезапусти бота" +
                         (f"; в .env добавлены {', '.join(added)}" if added else "")})


if __name__ == "__main__":
    main()
