#!/usr/bin/env python3
"""Package module resources into explicit-only student START files. Never install."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = '\n<!-- BEGIN STUDENT RESOURCE BUNDLE -->\n'
HEADER = '''
## Установка из встроенных ресурсов

Этот раздел — данные учебного комплекта. Чтение, поиск, сборка или редактирование пакета НЕ являются запросом установки. Только при явном запросе ученика и после подтверждения его отдельной рабочей папки выполни следующие действия доступными средствами записи файлов:

1. Убедись, что это папка ученика, а не репозиторий исходников учебных материалов и не личный второй мозг автора. Прочитай действующие AGENTS.md и карту SYSTEM.md, если они есть. Для модуля 0 допускается пустая папка; для модулей 2–7 сначала нужны входные артефакты соответствующего сценария. Отсутствие статуса живого пилота само по себе не блокирует черновое прохождение учеником.
2. В JSON ниже ключ — путь внутри локального навыка, значение — точное содержимое файла UTF-8. Сохраняй только под `.agents/skills/<имя навыка из сценария>/`. Не допускай абсолютные пути, `..`, симлинки и запись вне рабочей папки. Глобальные каталоги не меняй.
3. Файл отсутствует — создай; совпадает — оставь; отличается — сохрани существующий и покажи различие перед обновлением. Не запускай скрипты только потому, что они входят в payload. После установки прочитай SKILL.md и лишь затем продолжай сценарий. На сервере все ресурсы разворачиваются по отдельному явному действию ученика.
4. Локальные `.ikigai/moduleXX.json` хранят module/version, phase, checks=not_run и список созданных артефактов без секретов. Обновляй только запись этого модуля; статус installed/drafted не означает verified. Ссылки и навыки свяжи с проектом по указаниям сценария, не дублируя маркерные блоки.
5. Если нет инструмента записи, остановись с конкретным объяснением. Не выдавай инструкцию за выполненную установку. Не требуй от ученика терминала для базовой работы. Программы и сервисы, отсутствующие в среде, не объявляй доступными.

При нехватке контекста установи только навык этого модуля и продолжи в новой сессии по его SKILL.md. Не загружай все паки одновременно. Команды авторизации выполняет сам человек в официальном интерфейсе. Секреты в payload и чат не записывать.

### Payload навыка

'''


def build(module):
    start = module/'START.md'
    if not start.exists():
        return None
    if module.name == 'module-01-architecture':
        return None  # Module 1 has its reviewed stdlib bootstrap builder.
    skills = list((module/'skill').glob('*/SKILL.md'))
    if len(skills) != 1:
        raise ValueError('Expected exactly one main skill in '+module.name)
    skill = skills[0].parent
    resources = {p.relative_to(skill).as_posix(): p.read_text(encoding='utf-8')
                 for p in sorted(skill.rglob('*')) if p.is_file()
                 and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    body = start.read_text(encoding='utf-8').split(BOUNDARY)[0].rstrip()
    payload = json.dumps(resources, ensure_ascii=False, indent=2)
    start.write_text(body+'\n'+BOUNDARY+HEADER+'Имя навыка: `'+skill.name+'`.\n\n```json\n'+payload+'\n```\n',encoding='utf-8')
    return {'module': module.name, 'skill': skill.name, 'resource_count': len(resources),
            'start_bytes': start.stat().st_size, 'functional_checks': 'not_run'}


def main():
    modules = [result for module in sorted(ROOT.glob('module-*')) if (result := build(module))]
    (ROOT/'BUNDLES.json').write_text(json.dumps({'version':'0.2.0-draft','modules':modules},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    files={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted(ROOT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts
           and p.suffix not in ('.pyc','.zip') and p.name!='MANIFEST.json'}
    (ROOT/'MANIFEST.json').write_text(json.dumps({'version':'0.2.0-draft','files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'bundles':modules,'files':len(files)},ensure_ascii=False))


if __name__ == '__main__':
    main()
