# CHANGELOG

## F.E.D.O v1.4 — Linux Migration & Core Foundation

### Added
- Added `core/ai_router.py` — базовый AI Router: единая точка входа (команды → system → LLM). Через роутер теперь идут и GUI, и консоль.
- Added `core/complexity.py` — определение сложности запроса по количеству слов (1–5 simple, 6–15 normal, 16+ complex). Пороги настраиваются в `data/settings.json`.
- Added `core/system_monitor.py` — кроссплатформенный модуль мониторинга: CPU, RAM, диск (авто-определение раздела), GPU/VRAM (GPUtil), температура CPU, топ процессов.
- Added `core/user_profile.py` — структурированный профиль пользователя (`data/user_profile.json`): имя, город, о пользователе, предпочтения, контекст, привычки. Отдельный уровень памяти.
- Added одноразовая миграция данных v1.3: плоские ключи памяти (`имя`, `город`, `кто`) переносятся в профиль автоматически.
- Added консольный режим: `python main.py --console`.
- Added системные запросы через роутер: «Покажи состояние системы», «Почему компьютер тормозит?» и т.п. Если LM Studio офлайн — монитор отвечает напрямую, без нейросети.
- Added команда `система` — прямой вывод снимка состояния без LLM.
- Added поле **TTS speaker** в Настройках (Silero, голос настраивается, по умолчанию — голос модели).
- Added v1.4-ключи в `data/settings.json`: пороги сложности, интервал мониторинга, TTS speaker.

### Improved
- Linux-first: `core/pc_commands.py` теперь кроссплатформенный (`xdg-open` / `os.startfile`, домашняя папка вместо `C:\`, запуск процессов без Windows-флагов).
- GUI: диск определяется автоматически (`/` на Linux, системный раздел на Windows) — монитор системы больше не падает на Linux.
- GUI: Developer Terminal кроссплатформенный (bash на Linux, PowerShell/CMD на Windows), блокировщик расширен Linux-командами (`rm -rf /`, `mkfs`, `dd if=`, `reboot` и др.).
- LLM client: имя модели определяется автоматически через `/v1/models` (вместо захардкоженного `qwen/qwen2.5-vl-7b`).
- LLM client: контекст запроса расширен профилем пользователя и внешним контекстом от роутера; сложность запроса влияет на `max_tokens`.
- Разделение логики и интерфейса: GUI больше не вызывает LLM и команды напрямую — только через AI Router.
- Настройки: сохранение теперь поверх существующего файла (новые ключи не теряются).
- Консольный баннер и GUI теперь используют актуальную версию из `config.py`.

### Fixed
- **Fixed critical:** `ask_llm()` падал с TypeError (системный prompt строился с неверным аргументом `style_mode`) — каждый LLM-запрос в v1.3 возвращал ошибку.
- **Fixed critical:** `psutil.disk_usage("C:\\")` в GUI — мгновенный краш монитора на Linux.
- **Fixed:** Silero TTS: спикер теперь настраивается через `tts_speaker` в настройках
  (голоса v4_ru: aidar, eugene, baya, kseniya, xenia, random).
  По умолчанию — `aidar` (глубокий мужской).
- Fixed `open_explorer`: вместо жёсткого `C:\` открывается домашняя папка (кроссплатформенно).
- Fixed `open_site`: запрос кодируется через `urllib.parse.quote` (спецсимволы не ломают URL).
- Fixed пути `LOG_PATH` / `PROJECT_PATH`: теперь absolute, не зависят от cwd запуска.

### Architecture (v1.4)

```
                ┌──────────────┐      ┌──────────────┐
                │     GUI      │      │   Console    │
                └──────┬───────┘      └──────┬───────┘
                       ──────────┬───────────┘
                                  ↓
                          ┌──────────────┐
                          │  AI Router   │  команды → system → LLM
                          └─────────────┘
            ┌────────────────────┼────────────────────┐
            ↓                    ↓                    ↓
      LM Studio            Memory / Profile      System Monitor
      (auto model)     (user_profile + memory)   (CPU/RAM/GPU/Disks)
```

### Known Issues
- AI Router v1.4 — ключевой (keyword) механизм; семантический роутинг — v1.5.
- STT использует Google Speech Recognition (не локальный движок) — замена в планах.
- Gemini-бэкенд: поле для ключа есть, интеграция — следующая версия.
- Hotkeys Ctrl+A/C/V/X могут вести себя неоднородно на некоторых раскладках Windows.
