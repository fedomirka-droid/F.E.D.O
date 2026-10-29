# F.E.D.O. Ecosystem — состояние (снимок)

Дата: **2026-10-29**. Ветка: `arena/3a9f3ab5-f-e-d-o`. Роль документа: честный
ответ на вопрос «что работает сейчас, что проверено и чем именно, а что нет».

**Статус: Pilot-ready, не Production.** Один владелец, несколько устройств,
локальный backend + HUB + агент + Telegram-бот + AI Router.

## Что где и в каком состоянии

| Компонент | Состояние | Чем подтверждено |
|-----------|-----------|------------------|
| F.E.D.O. Core (v1.5.10) | работает, **не изменён** | `main.py --console`: время, монитор CPU/RAM/диск, корректный выход; `git diff` по `core/ ai/ interface/ voice/ config.py main.py` — 0 файлов |
| Backend Ecosystem 2.0.0-personal | работает | `/api/health` → `status: ok`, `core: v1.5.10` |
| Desktop UI (React+TS) | собирается, отдаётся backend'ом | `npm run build` (226.90 kB JS / gzip 68.86), `GET /` → 200, SPA-fallback `/tasks` → 200 |
| Tauri-обёртка | конфиг готов, **инсталлятор не собран** | нет Rust toolchain в песочнице — `.msi/.exe` не существует |
| Синхронизация Desktop ↔ HUB | работает | два живых процесса (8795/8796): push/pull, конфликт, разрешение, offline-восстановление |
| Агент устройств | работает в режиме симуляции | lock/launch/shutdown/wol → `done`, запрещённые → `failed` с причиной |
| Telegram Mini (aiogram) | работает через HubClient | `/link`, `/today`, `/tasks`, `/devices`, действия по задачам, `ask_ai` |
| AI Router | работает с локальной заглушкой LM Studio | `/api/ai/health` видит `stub-llama-3.1-8b`, cloud без ключа корректно падает на local |
| Student Edition | **интеграция заблокирована** | исходников нет; статус `blocked`, импорт → 409. Слой совместимости готов |
| VPS-развёртывание | **не выполнялось** | скрипты и документация готовы, требуется подтверждение владельца |

## Тесты

```
.venv/bin/python -m pytest        → 149 passed  (~33 s)
cd desktop && npx vitest run      → 11 passed
cd desktop && npx tsc --noEmit    → 0 ошибок
cd desktop && npm run build       → ok
```

| Файл | Тестов |
|------|--------|
| `test_ecosystem_integration.py` | 29 |
| `test_schedule_import.py` | 20 |
| `test_sync.py` | 20 |
| `test_ai_router.py` | 16 |
| `test_devices_agent.py` | 16 |
| `test_migrations_core.py` | 10 |
| `test_mini_bot.py` | 9 |
| `test_auth.py` | 8 |
| `test_gateway.py` | 8 |
| `test_telegram.py` | 8 |
| `test_tasks_calendar.py` | 5 |
| **Итого** | **149** |

Базовая точка (коммит `236d324`): **110 passed**. Арифметика роста:
`+29` (новый файл интеграции) `+3` (тесты расписания) `+7` (тесты синхронизации) = **149**.

## Что требует внешних ресурсов

1. **Rust + MSVC** → сборка `.msi`/`.exe` Tauri. Без них установщика нет.
2. **LM Studio на RTX 3080** → реальные генерации (сейчас проверено на заглушке,
   повторяющей OpenAI-контракт).
3. **Ключ Gemini / OpenAI-совместимого облака** → облачные ответы. Без ключа
   Router честно переключается на локальную модель.
4. **Токен @BotFather** → живой Telegram. Логика бота проверена тестами и HubClient.
5. **VPS Ubuntu 24.04** → реальный деплой. Ничего не менялось без разрешения.
6. **Домашний ПК + WoL-контроллер** → настоящий запуск/сон/пробуждение.
7. **Исходники Student Edition** → полная интеграция (см. `STUDENT_EDITION_GAP.md`).

## Известные ограничения

* Core GUI (CustomTkinter) в песочнице не запускается: нет `tkinter`/дисплея.
  Консольный путь Core проверен; GUI-файлы не изменялись.
* Белый список приложений хранится на HUB (`command_allowlist`) и отдельно в
  аргументах агента (`--allow-app`); CLI-флаг не пишет список на сервер — это
  осознанно (агент не может расширять себе права).
* SQLite + WAL рассчитан на одного владельца и единицы устройств.
* Напоминания о парах работают через WebView/браузерные `Notification`;
  в чистом Tauri-окне поведение зависит от WebView2.
* Классы конфликтов: «моя версия» и «серверная» — выбор владельца; автослияния полей нет.

## Документы

* [`REPORT_ECOSYSTEM.md`](REPORT_ECOSYSTEM.md) — отчёт A–L с командами и результатами.
* [`DEPLOY.md`](DEPLOY.md) — HUB на Ubuntu 24.04, Desktop на Windows 11, бэкапы, откат.
* [`STUDENT_EDITION_GAP.md`](STUDENT_EDITION_GAP.md) — чего не хватает для Student Edition.
* [`MINI_INTEGRATION.md`](MINI_INTEGRATION.md) — контракт бота и HUB.
* [`DESKTOP_BUILD.md`](DESKTOP_BUILD.md) — сборка Desktop.
