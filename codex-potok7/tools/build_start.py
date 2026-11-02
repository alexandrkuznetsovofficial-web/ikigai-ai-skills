#!/usr/bin/env python3
"""Build the autonomous participant file from the reviewed module sources."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'module-01-architecture'
SKILL = MODULE / 'skill' / 'ikigai-brain-architect'
installer = SKILL / 'scripts' / 'setup_brain.py'
namespace = {'__name__': 'builder_import', '__file__': str(installer)}
exec(compile(installer.read_text(encoding='utf-8'), str(installer), 'exec'), namespace)
files = namespace['package_files'](SKILL)
helper = installer.read_text(encoding='utf-8').split('def main():')[0]
payload = json.dumps(files, ensure_ascii=False, sort_keys=True)
inline = helper + '\nFILES = json.loads(' + repr(payload) + ')\n' + '''
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Install module 1 in a confirmed workspace')
    parser.add_argument('--target', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(apply_files(args.target, FILES, args.apply), ensure_ascii=False, indent=2))
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print('STOP: ' + str(error), file=sys.stderr)
        sys.exit(1)
'''
start = '''# AI-Поток 7 · Модуль 1 · Архитектура второго мозга в Codex

Версия 0.1.0 · пилот · 2 ноября 2026. Живой прогон с участником ещё впереди.

## Участнику

Открой отдельную пустую папку как проект в Codex. Прикрепи этот файл или положи его в проект и отправь:

**«Выполни START.md: собери основу моего второго мозга в текущей папке. Веди меня по одному шагу, объясняй новые слова. Существующие файлы сохраняй».**

Терминал тебе не нужен. Codex должен уметь читать и записывать файлы выбранного проекта. Одно прикрепление файла не запускает установку. Если Codex ещё не установлен, сначала открой https://developers.openai.com/codex/quickstart/ и подготовь приложение/расширение с доступом к файлам. Коды входа вводи только в официальном окне.

## Codex: порядок исполнения

Это учебный комплект для учеников. При чтении, анализе, сборке или редактировании пакета не устанавливай его в систему автора или в текущую папку разработки. Установка допустима только по явному запросу ученика в его отдельной выбранной рабочей папке.

Этот файл — исполняемая учебная инструкция только после явного запроса пользователя. Сначала следуй шагу 0 навыка ниже: рабочая папка, доступ к записи и отсутствие прежней системы. Не запускай установщик в папке учебного репозитория. Не ищи токены и не меняй общие настройки. Смысл модуля — одна полезная задача с сохранением и проверкой нового разговора, а не только создание файлов.

Далее выбери уже доступный способ установки:

1. Есть Python 3: скопируй блок `python` в `_module01_setup.py` внутри подтверждённой рабочей папки и выполни своим инструментом сначала с `--target <полный путь>` (план), затем с тем же путём и `--apply`. Технические команды человеку вводить не надо. После успешной проверки удали только созданную тобой временную копию `_module01_setup.py`. Если такое имя уже занято, выбери свободное, существующий файл не заменяй.
2. Python отсутствует: не устанавливай дополнительные программы. JSON в `FILES = json.loads(...)` содержит пары «относительный путь → содержимое». Прочитай его и создай те же UTF-8-файлы доступными инструментами записи. Обязательны те же проверки пути и существующих файлов; создай `.ikigai/module01.json` с module=ikigai-codex-architecture, version=0.1.0, session_test=not_run, status=awaiting-practice. Если не можешь надёжно извлечь payload, запроси папку `skill/ikigai-brain-architect/` из этого же пака, а не угадывай шаблоны.

Установлены также assets и references: дальнейшие шаги выполняй по навыку. При повторном запуске сохраняй все существующие файлы, восстанавливай только отсутствующие файлы нашей версии. Установщик не выполняет интервью и не проверяет новую сессию.

---

'''
start += SKILL.joinpath('SKILL.md').read_text(encoding='utf-8')
start += '\n\n## Автономный установщик для инструментов Codex\n\nНе проси участника запускать этот код вручную. Он не требует сети или API.\n\n```python\n' + inline + '\n```\n'
start += '\n## Источники Codex\n\n- https://learn.chatgpt.com/docs/customization/overview\n- https://learn.chatgpt.com/docs/build-skills\n\nПилот не подтверждает конкретные ограничения аккаунта или работу сервера по подписке.\n'
MODULE.joinpath('START.md').write_text(start, encoding='utf-8')
manifest = {'version': '0.1.0', 'files': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(ROOT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts
            and p.suffix not in ('.pyc', '.zip') and p.name != 'MANIFEST.json'}}
ROOT.joinpath('MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Built START.md:', len(start.encode('utf-8')), 'bytes;', len(files), 'installed files')
