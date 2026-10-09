# F.E.D.O v1.0 — Первый рабочий прототип

**F.E.D.O — Functional Event Detection Operator.**

Первый рабочий прототип локального ИИ-ассистента: графический интерфейс в стиле инженерного терминала, локальная языковая модель через LM Studio, голосовой вывод и модульная структура. С этой версии началась история проекта.

Версия ветки: **v1.0** (ветка `v1.0-release`) · Статус: архивная (май 2026)

---

## Что нового в v1.0

- первый запуск проекта через `main.py`;
- графический интерфейс (tkinter);
- подключение к локальной LLM через LM Studio;
- системный промпт личности F.E.D.O;
- голосовой вывод через Silero TTS;
- базовые системные команды;
- защита от VPN/Proxy (`core/proxy_guard.py`);
- модульная структура проекта;
- базовая обработка ошибок.

---

## Возможности

- диалог с локальной нейросетью;
- спокойный краткий оператор в стиле советской научно-технической системы;
- голосовое озвучивание ответов;
- базовые команды и данные о системе (psutil);
- графический и консольный режимы.

---

## Установка и запуск

Требуются: **Python 3.11.9**, pip, Git, LM Studio.

1. Установи LM Studio: https://lmstudio.ai — скачай модель и запусти локальный сервер (обычно `http://localhost:1234`, должен совпадать с настройками проекта).
2. Создай окружение в папке проекта: `py -3.11 -m venv .venv`
3. Активируй: PowerShell — `.\.venv\Scripts\Activate.ps1`, CMD — `.\.venv\Scripts\activate.bat`
4. Установи зависимости: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` (при ошибке SOCKS — сначала `pip install PySocks`).
5. Запусти: `.\.venv\Scripts\python.exe main.py`

При включённом VPN возможны проблемы с pip и LM Studio: proxy_guard чистит proxy-переменные и добавляет `localhost` в исключения, но VPN лучше отключать. Без запущенного LM Studio ассистент не отвечает.

---

## Стек

- Python 3.11.9, tkinter, LM Studio (локальная LLM)
- requests, colorama, psutil, numpy
- torch, Silero TTS, sounddevice, soundfile, SpeechRecognition
- PySocks, Git / GitHub

---

## Структура проекта

```text
F.E.D.O/
├── main.py / config.py / requirements.txt / CHANGELOG.md
├── ai/          # LLM-клиент и prompt'ы
├── core/        # команды, память, настройки, proxy_guard
├── interface/   # GUI (tkinter) + консоль
└── voice/       # TTS (Silero) + STT
```

---

## Дальше

v1.1 — удобство интерфейса (вкладки, кнопки, копирование); v1.2 — EXE-сборка и стабильность; v1.3 — новый UI и мониторинг ПК.

---

## Статус

Архивная — разработка завершена в мае 2026.
