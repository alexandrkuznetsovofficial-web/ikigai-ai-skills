# AI-Поток 7 · Второй мозг с нуля в Codex

> Учебные материалы для учеников. Этот каталог — исходники комплекта, а не действующий второй мозг автора. Чтение, анализ и редактирование файлов не разрешают устанавливать их в текущую систему. Установка — только по явному запросу ученика в его отдельной рабочей папке. Ничего из этого каталога не устанавливается в личные навыки автора.

**Сборка 0.2.0-draft · 2 ноября 2026.** Подготовлена вся согласованная базовая цепочка: подготовка и модули 1–7. Новые модули собраны без функциональных прогонов по запросу автора. Серверный код, подключения, резервирование и ученические сценарии не запускались. Это комплект черновых материалов, а не подтверждение работающей системы.

## Все паки

Каждый START.md автономен: содержит сценарий и ресурсы своего навыка. В ZIP входят также инструкции, исходники навыка, словарь, материалы ведущего и презентация. Ученику не требуется прежний Claude. Не прикрепляй сразу все START.md в один разговор.

| Этап | Запуск | Пак | Презентация |
|---|---|---|---|
| 0. Подготовка Codex | [START.md](module-00-preflight/START.md) | [ZIP](dist/module-00-preflight.zip) | [PDF](module-00-preflight/presentation/slides.pdf) · [HTML](module-00-preflight/presentation/slides.html) |
| 1. Архитектура | [START.md](module-01-architecture/START.md) | [ZIP](dist/module-01-architecture.zip) | [PDF](module-01-architecture/presentation/architecture.pdf) · [HTML](module-01-architecture/presentation/architecture.html) |
| 2. Интервью основателя | [START.md](module-02-founder-context/START.md) | [ZIP](dist/module-02-founder-context.zip) | [PDF](module-02-founder-context/presentation/slides.pdf) · [HTML](module-02-founder-context/presentation/slides.html) |
| 3. Оркестратор и команда | [START.md](module-03-orchestrator/START.md) | [ZIP](dist/module-03-orchestrator.zip) | [PDF](module-03-orchestrator/presentation/slides.pdf) · [HTML](module-03-orchestrator/presentation/slides.html) |
| 4. ОС второго мозга | [START.md](module-04-brain-os/START.md) | [ZIP](dist/module-04-brain-os.zip) | [PDF](module-04-brain-os/presentation/slides.pdf) · [HTML](module-04-brain-os/presentation/slides.html) |
| 5. Внешние сервисы | [START.md](module-05-integrations/START.md) | [ZIP](dist/module-05-integrations.zip) | [PDF](module-05-integrations/presentation/slides.pdf) · [HTML](module-05-integrations/presentation/slides.html) |
| 6. Сервер и Telegram | [START.md](module-06-server-telegram/START.md) | [ZIP](dist/module-06-server-telegram.zip) | [PDF](module-06-server-telegram/presentation/slides.pdf) · [HTML](module-06-server-telegram/presentation/slides.html) |
| 7. Эксплуатация | [START.md](module-07-operations/START.md) | [ZIP](dist/module-07-operations.zip) | [PDF](module-07-operations/presentation/slides.pdf) · [HTML](module-07-operations/presentation/slides.html) |

[Скачать весь комплект](dist/potok7-codex-student-kits-0.2.0-draft.zip).

## Как пользоваться

1. Если Codex ещё не работает — сначала [подготовка](module-00-preflight/PARTICIPANT.md). Ученик сам устанавливает официальный клиент и входит в аккаунт; из неработающего чата это сделать невозможно.
2. Открыть отдельную папку ученика как проект. Папка учебных материалов рабочей памятью не является.
3. Прикрепить START.md текущего модуля или положить его в открытую папку и явно попросить выполнить. При прохождении Codex делает технические действия доступными инструментами; ученику не нужно вводить команды.
4. Новые сведения и результаты сохраняются в файлах ученика. При переходе к следующему модулю нужны его входные артефакты. Статус живого пилота не является условием сборки файлов следующего пака.

HTML-презентацию скачай и открой браузером. Стрелки переключают слайды, N показывает заметки ведущего, P открывает печать. На GitHub HTML отображается исходником. Рядом есть PDF и редактируемый `presentation/SLIDES.md`. PPTX в сборке нет: обязательная библиотека экспорта отсутствует в среде.

## Что важно знать о готовности

- Для новых модулей статус `draft_unrun`: нет функционального прогона, установки, подключения сервисов или живого испытания на ученике.
- У модуля 1 есть [исторический протокол проверок версии 0.1](module-01-architecture/pilot/VALIDATION.md); он не подтверждает остальные модули или всю цепочку.
- Сервер и Telegram подготовлены как материалы и код для будущего развёртывания. Бот не включён, сервер не арендован, чужие токены и инфраструктура не используются.
- Экспорт презентации и сборка архива не являются проверкой работы модуля.
- Список ещё не выполненных действий — [ASSEMBLY_STATUS.md](ASSEMBLY_STATUS.md).

## Ведущему и разработчику материалов

- [Как вести ученика и объяснять термины](FACILITATOR.md)
- [Архитектура и контракты](research/ARCHITECTURE.md)
- [Изменения относительно Claude](research/CHANGES_FROM_CLAUDE.md)
- [Соответствие исходным пакам и границы сборки](research/COVERAGE.md)
- [Источники](research/SOURCES.md) · [Изменения сборки](RELEASE_NOTES.md)

Исходники навыков — внутри каждой папки `skill/`; это исходные материалы, а не установленная `.agents/skills/`. `tools/build_student_starts.py` собирает автономные START модулей 0 и 2–7, `tools/build_start.py` — установочный файл модуля 1; `tools/build_presentation.py --module <папка>` — HTML и MD, `tools/build_archives.py` — ZIP. Эти сборщики не разворачивают систему ученика. Их выполняет составитель материалов, а не участник.
