# F.E.D.O. Ecosystem — состояние реализации

Дата среза: 2026-10-29. Ветка: `arena/3a9f3ab5-f-e-d-o`.
Основание: репозиторий содержит только **F.E.D.O. Core v1.5.10** — архива
`F.E.D.O-Student-Edition-MVP(1).zip` (FastAPI/React/SQLite MVP) в рабочем
окружении не оказалось, поэтому слой Ecosystem написан с нуля **поверх Core**
и переиспользует его модули (монитор, prompt-ы, команды, конфиг).

## Готово и проверено

| Блок | Состояние | Чем проверено |
|------|-----------|----------------|
| Аудит и стабилизация Core | Core не изменён, работает | `tests/test_migrations_core.py`, `git diff` по `core/`, `ai/`, `interface/` |
| Backend (HUB + Desktop) | FastAPI, 60+ эндпоинтов | `pytest tests/test_auth.py tests/test_tasks_calendar.py` |
| Миграции БД | Alembic + автобэкап SQLite | `tests/test_migrations_core.py` |
| AI Router 2.0 | 4 режима, приватность, лимиты, отмена, стриминг | `tests/test_ai_router.py` (18 тестов) |
| Sync Engine | outbox, идемпотентность, конфликты, backoff, перезапуск | `tests/test_sync.py` (14 тестов) + живой прогон HUB↔Desktop |
| Импорт ИС-21 | XLSX/XLS, merge, соседние группы, даты, предупреждения | `tests/test_schedule_import.py` (17 тестов) |
| Device Manager + Agent | белый список команд, подпись канала, аудит, симуляция | `tests/test_devices_agent.py`, `tests/test_gateway.py` |
| Telegram Mini | привязка по коду, права, задачи/расписание/устройства | `tests/test_telegram.py`, `tests/test_mini_bot.py` |
| Desktop UI | 8 разделов, тёмная/светлая тема, масштаб, стриминг чата | `npm run build`, ручная проверка через live-preview |
| Desktop shell (Tauri 2) | конфигурация, sidecar, health-check, kill при выходе | **не собрано**: в песочнице нет Rust toolchain |
| Deployment | Docker Compose (isolated), systemd, nginx, бэкапы | YAML провалидирован; реальный VPS не менялся |

## Требует реального оборудования/доступов

1. **Windows-сборка Tauri**: `rustup` + MSVC Build Tools, затем
   `.\desktop\scripts\build-sidecar.ps1` и `npm run tauri build`.
2. **LM Studio**: локальные модели — `FEDO_LOCAL_AI_URL`, интерфейс покажет статус.
3. **Gemini/облако**: API-ключ вводится в Настройках (шифруется), реальные
   запросы не выполнялись — только мок-транспорт в тестах.
4. **Telegram**: токен @BotFather + `FEDO_BOT_SERVICE_TOKEN` на HUB.
5. **VPS**: развёртывание по `docs/DEPLOY.md` требует подтверждения владельца.
6. **GPU-ПК (RTX 3080)**: запуск `python -m ecosystem.agent ... --gateway-port 8790`,
   LM Studio локально; проверено в режиме симуляции + реальный heartbeat.
7. **Wake-on-LAN**: нужен реальный контроллер (старый ноутбук) в той же сети.
8. **Существующий F.E.D.O. Mini 2.1**: подключить адаптер `HubClient`
   к имеющейся бизнес-логике (контракты зафиксированы).

## Что осталось сделать (честно)

* Windows-установщик: конфигурация готова, сборка не выполнялась (нет Rust).
* Сквозной тест «два Desktop ↔ один HUB по сети» — логика покрыта тестами на
  HTTP-уровне, но реальные две машины не поднимались.
* Планировщик напоминаний в Desktop (in-process) не реализован: напоминания
  отдаются через API (`/api/tasks/reminders/due`, `/api/bot/reminders`).
* Миграция данных из старой версии Mini (если у неё своя БД) — не выполнялась,
  исходников Mini нет.
* Импорт `.xls` проверен кодом и юнит-тестами xlrd-ветки, но реального
  «колледжного» .xls-файла в окружении не было — проверено на синтетике.

## Как продолжить

1. Собрать sidecar и установщик на Windows (`docs/DESKTOP_BUILD.md`).
2. Развернуть HUB (`docs/DEPLOY.md`), задать секреты, создать владельца.
3. Зарегистрировать устройства, ввести их токены в агенты.
4. Указать на ноутбуке `FEDO_HUB_URL` + `FEDO_SYNC_DEVICE_TOKEN`.
5. Подключить Mini 2.1 к `HubClient` и запустить бота.
6. Прогнать `pytest -q` на целевой машине и сценарии из README.

## Живая проверка синхронизации двух узлов (2026-10-29)

Подняты два отдельных процесса backend: HUB (`--role hub`, порт 8781) и
Desktop (`--role desktop`, порт 8782, `FEDO_HUB_URL` + токен устройства).
Данные — разные каталоги, общение только по HTTP.

| Шаг | Результат |
|-----|-----------|
| Desktop создаёт задачу → `POST /api/sync/run` | `pushed: 1, applied: 1`; на HUB задача появилась |
| HUB создаёт задачу → sync | `pulled: 1`; на Desktop появилась |
| Обе стороны правят одну задачу | `conflicts: 1`; сохранены обе версии (`Правка на HUB` / `Правка на ноутбуке`) |
| Разрешение конфликта «моя версия» | правка уехала на HUB (`sync: pushed 1`), HUB показывает локальный текст |
| Третье устройство (`HomePC`) читает журнал | видит **обе** версии конфликта и итоговую — данные не потеряны |
| Без токена / с неверным токеном | `401` на `/api/tasks` и `/api/sync/pull` |

Найденный и исправленный баг: при разрешении конфликта «моя версия» на
клиенте правка применялась только локально, в outbox ничего не попадало, и
HUB оставался со своей версией. Теперь `resolve_conflict`:
1) применяет входящую версию относительно **локальной** версии записи,
2) ставит/обновляет операцию в outbox с `base_version` = версии HUB.
Регрессия закреплена тестами
`test_client_resolves_conflict_locally_and_pushes_it_to_hub` и
`test_hub_conflict_resolution_does_not_enqueue_outbox`.

Полный прогон: `110 passed` (`pytest -q`, 22.8 s).
