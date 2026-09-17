# F.E.D.O v1.4 — Linux Migration & Core Foundation

**F.E.D.O — Functional Event Detection Operator.**

Локальный AI-ассистент на Python. v1.4 — этап, на котором F.E.D.O перестает быть
«GUI, который сам себе LLM-клиент», и становится **системой**: ядро (AI Router),
уровни памяти (профиль + общая память), системный модуль и интерфейс, который
просто вызывает ядро.

---

## Что нового в v1.4

### Ядро

* **AI Router** (`core/ai_router.py`) — единая точка входа:
  команды → системный запрос (system module) → локальная LLM.
  GUI и консоль теперь работают через один и тот же конвейер;
* **Определение сложности запроса** (`core/complexity.py`) — простой механизм v1.4
  по количеству слов: 1–5 → simple, 6–15 → normal, 16+ → complex.
  Пороги настраиваются в `data/settings.json`;
* **Системный монитор** (`core/system_monitor.py`) — CPU, RAM, диск
  (авто-определение раздела), GPU/VRAM (GPUtil), температура CPU, топ процессов.
  Снимок состояния уходит в контекст LLM на системные вопросы;
* **User Profile** (`core/user_profile.py`) — структурированная память пользователя
  (`data/user_profile.json`): имя, город, о пользователе, предпочтения, контекст, привычки.
  Данные v1.3 из плоской памяти мигрируют в профиль автоматически.

### Linux-first

* кроссплатформенные PC-команды (`xdg-open` / `os.startfile`, домашняя папка,
  запуск без Windows-специфичных флагов);
* GUI-монитор работает на Linux (вместо краша на `C:\`);
* Developer Terminal: bash на Linux, PowerShell/CMD на Windows;
  блокировщик опасных команд расширен (`rm -rf /`, `mkfs`, `dd if=`, `reboot` …);
* консольный режим: `python main.py --console`.

### Стабильность (критичные фиксы v1.3)

* **LLM-запросы вообще не работали** — `ask_llm()` падал с TypeError
  (неверный аргумент системного prompt). Исправлено;
* модель LM Studio больше не захардкожена — определяется через `/v1/models`;
* Silero TTS: загрузка `v4_ru` со спикером `aidar` (v3) молчала.
  Теперь speaker настраивается, по умолчанию — голос модели;
* сохранение настроек не теряет новые ключи.

---

## Архитектура v1.4

```
                ┌──────────────┐      ┌──────────────┐
                │     GUI      │      │   Console    │
                │ (CustomTk)   │      │ (--console)  │
                └──────┬───────┘      └──────┬───────┘
                       └──────────┬──────────┘
                                  ↓
                          ┌──────────────┐
                          │  AI Router   │
                          └─────────────┘
            ┌────────────────────┼────────────────────┐
            ↓                    ↓                    ↓
      LM Studio            Memory / Profile      System Monitor
      (auto model)      user_profile.json      CPU / RAM / GPU /
                      + memory.json             Disk / Temps / Procs
```

### Структура проекта

```text
F.E.D.O/
├── main.py               # точка входа: GUI | --console
├── config.py             # версия, имена, базовые константы
├── ai/
│   ├── llm_client.py     # LM Studio (auto model, контекст, сложность)
│   └── prompts.py        # системные prompt'ы и личности
├── core/
│   ├── ai_router.py      # конвейер: команды → system → LLM
│   ├── assistant.py      # консольный режим
│   ├── commands.py       # локальные команды
│   ├── complexity.py     # сложность запроса (v1.4)
│   ├── logger.py         # журнал сессии
│   ├── memory.py         # общая память (ключ = значение)
│   ├── pc_commands.py    # действия с ПК (кроссплатформенно)
│   ├── proxy_guard.py    # защита от proxy-переменных
│   ├── settings.py       # data/settings.json (v1.4-ключи)
│   ├── settings_manager.py
│   ├── system_monitor.py # состояние компьютера (v1.4)
│   └── user_profile.py   # профиль пользователя (v1.4)
├── interface/
│   ├── gui.py            # CustomTkinter: Чат / ПК / Память / Настройки
│   │                     # + Developer Mode: Терминал / Логи / Отладка
│   └── console_ui.py
├── voice/
│   ├── stt.py            # распознавание речи (SpeechRecognition)
│   └── tts.py            # Silero TTS (speaker из настроек)
├── assets/
├── data/                 # runtime: settings.json, memory.json, user_profile.json
└── logs/
```

---

## Запуск

```bash
# GUI
python main.py

# Консоль
python main.py --console
```

Требования: Python 3.11, LM Studio с включённым локальным сервером
(`http://127.0.0.1:1234`), зависимости из `requirements.txt`.

Системные вопросы работают и без LLM:

```
> Покажи состояние системы
F.E.D.O: Состояние системы (монитор F.E.D.O):
  CPU: 12% (8 ядер), температура 47°C
  RAM: 58% (9.2 / 16.0 GB)
  ...
```

---

## Текущий вектор разработки

v1.5 и далее:

* развитие GUI (карточки памяти, настройки сложности, визуализация событий);
* семантический AI Router (вместо ключевой базы) + Gemini-бэкенд;
* локальный STT (уход от Google Speech Recognition);
* событийная часть: обнаружение → анализ → реакция (раскрытие названия F.E.D.O);
* подготовка v1.8 — Telegram Bot;
* v2.0 — Windows-релиз, always-on, глубокое управление ПК.

---

## Статус проекта

Активная разработка — v1.4
