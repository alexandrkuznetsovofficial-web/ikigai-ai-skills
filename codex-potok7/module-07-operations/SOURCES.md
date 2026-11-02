# Источники эксплуатации

Учебная основа: публичный `ikigai-ai-skills`, `meeting-2-3/auto-commit-backup.md`, `novoselie-server-kit/04_ISTINA_I_BEKAPY.md`; новый контракт memory из модуля 1. Изучены принципы главной копии, локальной истории, отдельного backup и восстановления во временную папку.

Адаптация: отдельные ZIP-снимки текстовых файлов вместо предположения о уже настроенном git, dry-run и staging restore, отсутствие автоудаления и публикации памяти. Это новое непроверенное исполнением средство; прежняя проверенность Claude-пака на него не переносится.

Ссылки для конкретной ОС: [systemd.timer](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html), [Apple launchd](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html), [Microsoft Task Scheduler](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-start-page). Перед установкой расписания сверить актуальную ОС, доступы и фактическое срабатывание. Сейчас прогоны отложены.
