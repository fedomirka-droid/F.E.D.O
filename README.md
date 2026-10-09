# F.E.D.O v1.2 — App Build & Stability Update

**F.E.D.O — Functional Event Detection Operator.**

Версия, в которой проект стал ближе к обычному приложению для ПК: своя иконка, подготовка к EXE-сборке, первый собранный F.E.D.O.exe и стабильный запуск.

Версия ветки: **v1.2** (ветка `v1.2-release`) · Статус: архивная (май 2026)

---

## Что нового в v1.2

- добавлена иконка приложения (`assets/icon.ico`), подключена к GUI;
- подготовка к EXE-сборке;
- собран первый рабочий F.E.D.O.exe (локально, для тестов запуска без Python);
- Silero TTS безопасно отключается при ошибке;
- улучшена стабильность запуска;
- готовность проекта к GitHub Release.

---

## Возможности

- всё из v1.1 (вкладки, кнопки, память, голос);
- узнаваемая иконка приложения;
- тестовый запуск без установленного Python (через .exe, LM Studio всё равно нужен отдельно).

---

## Установка и запуск

Вариант А (тестовый): F.E.D.O.exe + запущенный LM Studio.
Вариант Б (из исходников): как в v1.1 — Python 3.11.9, `pip install -r requirements.txt`, старт через `main.py`.

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
├── assets/      # иконка приложения
├── ai/          # LLM-клиент и prompt'ы
├── core/        # команды, память, настройки, proxy_guard
├── interface/   # GUI с вкладками + консоль
└── voice/       # TTS (Silero) + STT
```

---

## Дальше

v1.3 — новый интерфейс, мониторинг ПК и режим разработчика.

---

## Статус

Архивная — разработка завершена в мае 2026.
