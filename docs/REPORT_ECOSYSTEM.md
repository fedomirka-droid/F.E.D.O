# F.E.D.O. Ecosystem — Personal Edition · итоговый отчёт

Формат А–H. Дата: 2026-10-29. Ветка: `arena/3a9f3ab5-f-e-d-o`.

---

## A. Реализовано

### A.1. F.E.D.O. Desktop (Tauri 2 + React/TS/Vite)
* Каркас `desktop/src-tauri`: `tauri.conf.json` (CSP `default-src 'self'`, окно 1280×860,
  min 1024×700, установщики NSIS + MSI, ресурсы `binaries/*`), `src/main.rs` —
  проверка `/api/health` (600 мс connect / 900 мс read) → запуск Python-sidecar →
  ожидание до 45 с → окно на `http://127.0.0.1:8765` → `kill` + `wait` по
  `RunEvent::Exit` (backend не остаётся висеть).
* Sidecar: `desktop/scripts/build-sidecar.ps1` (PyInstaller onefile + `--collect-submodules ecosystem`,
  докладывает `migrations`, `alembic.ini`, `core`, `ai`, `config.py`),
  `desktop/scripts/sidecar_entry.py`.
* Интерфейс: 8 разделов (Dashboard, AI Assistant, Tasks, Calendar, Schedule, Devices,
  System Monitor, Settings), тёмная тема по умолчанию, светлая переключаемая,
  масштаб UI через CSS-переменную `--scale`, индикатор соединения (backend / sync /
  режим AI / очередь операций), toast-уведомления, экран первичной настройки и логина.
* Локальная БД: `%APPDATA%\FEDO\fedo.db` + `secret.key` (0600) + `backups\` + `logs\`.
* Приложение работает без HUB: `sync.hub_configured: false` — штатное состояние.

### A.2. F.E.D.O. HUB (синхронизация + API)
* FastAPI-приложение с ролями `hub` / `desktop` из одного кода (`ecosystem/backend`).
* Владелец один; публичная регистрация выключена (`public_registration: false`,
  `POST /api/auth/setup` работает только пока владельца нет).
* Устройства: выдача токена при регистрации, отзыв, ротация, `owner_id` на всех таблицах.
* Синхронизация: журнал изменений с курсором, push идемпотентен по `op_id`,
  pull с `exclude_device`, конфликты с сохранением обеих версий.
* Уведомления и напоминания для бота: `/api/bot/reminders`, `/api/tasks/reminders/due`.
* Роутинг команд на устройства и статус доступности (`online/offline`, метрики).

### A.3. F.E.D.O. Mini (Telegram)
* Aiogram 3 бот: `/start`, `/today`, `/tasks`, `/schedule`, `/devices`, `/ai`, `/status`
  + inline-кнопки (задачи, расписание, устройства, подтверждение опасных команд).
* Привязка Telegram ↔ владелец по одноразовому коду (TTL, одноразовое использование).
* Собственной БД задач нет — только HUB API (`ecosystem/mini/hub_client.py`),
  поэтому Telegram и Desktop видят одни и те же данные.
* Бот не выполняет shell: только типизированные действия из белого списка.

### A.4. F.E.D.O. GPU Core (домашний ПК)
* `ecosystem/agent`: heartbeat со статусом и метриками (CPU/RAM/GPU/AI),
  шлюз `/api/execute`, HMAC-подпись канала, белый список команд
  (`status`, `lock`, `sleep`, `wake`, `volume`, `launch`…), подтверждение опасных,
  Wake-on-LAN, режим симуляции (`--simulate`).
* AI-узел: `--ai-endpoint` (LM Studio/любой OpenAI-совместимый сервер) — heartbeat
  сообщает HUB реальную доступность AI.

### A.5. AI Router 2.0
* Режимы `local_only / hybrid / cloud_preferred / manual`; в `local_only` и `manual`
  облако не вызывается никогда.
* Отдельные согласия: на передачу запроса и на передачу истории чата.
* Лимиты: запросов в минуту/сутки, символов, стоимость; учёт usage.
* Стриминг (SSE), таймауты, отмена (`POST /api/ai/cancel`), fallback без обхода
  приватности, ключи не попадают в логи (маскируются), хранятся в зашифрованном виде.

### A.6. Offline-first Sync Engine
* UUID-идентификаторы, `owner_id`, `version`, UTC `updated_at`, tombstones,
  `origin_device`, `op_id`, outbox, backoff (экспоненциальный, до 12 попыток),
  идемпотентность, обнаружение конфликтов без last-write-wins.
* Никогда не синхронизируются: история чата, секреты, локальные файлы, предпочтения
  интерфейса.
* UI-индикатор: `онлайн/офлайн`, число ожидающих операций, число открытых конфликтов.
* Разрешение конфликта «моя версия» теперь доезжает до HUB (см. D).

### A.7. Расписание и студенческий модуль
* Импорт XLS/XLSX: поиск колонки группы **ИС-21**, несколько листов, объединённые
  ячейки, защита от захвата соседней группы (ИС-22 и т.п.), пустые ячейки,
  распознавание дат, предупреждения (`warnings`) вместо выдуманных пар.
* Задачи: заголовок, описание, приоритет, дедлайн, план/факт времени, статус,
  напоминание, категория; кнопки старт/пауза/стоп трекинга.
* «Сегодня/завтра» — в Desktop и в Telegram.

### A.8. Device Manager + Agent
* Реестр устройств (ThinkPad, домашний ПК, VPS HUB, старый ноутбук как
  WoL-контроллер), статус, метрики CPU/RAM/GPU/доступность AI.
* Только явно разрешённые команды; опасные — требуют подтверждения владельца;
  произвольный shell из Telegram невозможен; режим симуляции для разработки.

### A.9. Безопасность
scrypt-хеширование паролей, opaque-сессии с отзывом и сроком, отдельные токены
устройств (`dev_…`) с ротацией, RBAC (owner / bot-service / device), rate limiting,
строгий CORS, валидация Pydantic, шифрование API-ключей (Fernet + `secret.key`),
аудит-лог действий, отключённая публичная регистрация, `owner_id` на всех таблицах,
отдельный `bot_service_token` для Mini.

### A.10. Развёртывание
`deploy/Dockerfile`, `docker-compose.yml` (проект `fedo`, сеть `fedo_net`,
тома `fedo_data`/`fedo_mini_data`, публикация только `127.0.0.1:8765`,
лимиты 512M/192M), `deploy/nginx/fedo.conf` (отдельный `server{}`, SSE без буфера),
два systemd-юнита с `ProtectSystem=strict`, `scripts/backup-hub.sh`,
`.env.example` без значений, инструкции в `docs/DEPLOY.md`.

---

## B. Проверено (реальные команды и результаты)

| Проверка | Команда | Результат |
|----------|---------|-----------|
| Полный набор тестов | `.venv/bin/python -m pytest` | **110 passed**, 22.8 s |
| TypeScript | `npx tsc -b` | 0 ошибок |
| Сборка UI | `npm run build` | `index.html 0.47 kB`, CSS 12.10 kB, JS 208.08 kB (gzip 63.91) |
| Core не сломан | `printf 'время\nсостояние системы\nвыход\n' \| python main.py --console` | баннер v1.5.10, время, монитор CPU/RAM/диск, корректный выход; `git diff` по `core/`, `ai/`, `interface/`, `config.py`, `main.py` — **0 файлов** |
| Backend живой | `/api/health` | `role: desktop`, `core: v1.5.10`, `sync.hub_configured: false` |
| Первичная настройка | `POST /api/auth/setup` | владелец создан, токен на 30 дней |
| UI и прокси | `GET :5173/api/health` | 200 через Vite-прокси |
| Агент | heartbeat + `POST /api/devices/{id}/commands {"action":"status"}` | `online`, cpu 21.1; команда `done`, вернула hostname/platform/core v1.5.10 |
| Импорт ИС-21 | XLSX с соседней группой ИС-22 | `imported: 3`, `sheets_matched: 1`, `dates: ["2026-10-29"]`, `warnings: []` |
| Два узла синхронизации | HUB :8781 + Desktop :8782 | push/pull работают, конфликт сохранён, разрешение доехало до HUB, третье устройство видит историю |
| Защита API | запросы без токена и с чужим device-токеном | `401` на `/api/tasks`, `/api/sync/pull` |
| Compose-файл | `yaml.safe_load` | services `hub, mini`, volumes `fedo_data, fedo_mini_data`, network `fedo_net`, дублей ключей нет |
| Миграции | старт с пустым каталогом данных | `alembic: Running upgrade -> ef92a32bf0fe`, автобэкап при существующей БД |

---

## C. Осталось подключить (нужны доступы/оборудование)

1. **Сборка Tauri на Windows**: Rust toolchain + MSVC Build Tools → `build-sidecar.ps1`
   → `npm run tauri build`. В песочнице Rust отсутствует, поэтому `.msi`/`.exe`
   не собраны — конфигурация и скрипты готовы и проверены статически.
2. **LM Studio / локальные модели**: указать `FEDO_LOCAL_AI_URL` и
   `--ai-endpoint` на GPU-ПК; реальные генерации не прогонялись.
3. **Gemini/облачный провайдер**: ключ вводится в Настройках Desktop, шифруется;
   сетевые вызовы проверены только мок-транспортом.
4. **Telegram**: токен @BotFather + `FEDO_BOT_SERVICE_TOKEN` + привязка владельца
   одноразовым кодом.
5. **VPS**: развёртывание по `docs/DEPLOY.md` — **не выполнялось**, GGSELL не
   затрагивался; нужен явный запрос владельца.
6. **Wake-on-LAN**: реальный контроллер в той же сети.
7. **Существующий F.E.D.O. Mini 2.1**: подключить `HubClient` к имеющейся логике
   (контракты в `docs/MINI_INTEGRATION.md`).

---

## D. Осталось сделать (ограничения честные)

* Две реальные машины «ноутбук ↔ HUB по сети» не поднимались: логика проверена
  двумя живыми процессами на одной машине + HTTP-тестами.
* Напоминания в Desktop реализованы на уровне API; in-process планировщик
  уведомлений в трее не написан.
* Импорт `.xls` (xlrd-ветка) покрыт кодом и юнит-тестами, но реального
  «колледжного» файла .xls в окружении не было — проверялся на синтетике.
* Миграция данных из старой Mini (если у неё своя БД) не выполнялась — исходников нет.
* Ветка сопровождения: конфликт-резолюция исправлена в этом проходе и покрыта
  двумя регрессионными тестами; остальные расхождения между клиентами
  (например одновременное удаление + правка) обрабатываются тем же механизмом,
  но отдельных тестов на них нет.

---

## E. Как запустить

### Desktop-режим (локально, без HUB)
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-ecosystem.txt
FEDO_ROLE=desktop python -m ecosystem.backend --role desktop --port 8765
cd desktop && npm install && npm run dev               # http://localhost:5173
```
При первом открытии создаётся владелец (логин + пароль ≥ 12 символов).

### HUB + синхронизация
```bash
FEDO_ROLE=hub python -m ecosystem.backend --role hub --port 8765
# на ноутбуке:
FEDO_HUB_URL=https://hub.example.com FEDO_SYNC_DEVICE_TOKEN=dev_xxx \
  FEDO_SYNC_ENABLED=1 python -m ecosystem.backend --role desktop --port 8765
```

### GPU-узел (домашний ПК)
```bash
python -m ecosystem.agent --hub-url http://hub.local:8765 --device-token dev_xxx \
  --gateway-port 8790 --ai-endpoint http://127.0.0.1:1234
# первый запуск можно без железа: добавьте --simulate
```

### Telegram Mini
```bash
FEDO_HUB_URL=http://127.0.0.1:8765 FEDO_BOT_SERVICE_TOKEN=... \
FEDO_TELEGRAM_TOKEN=... python -m ecosystem.mini
```

### Тесты / сборка
```bash
pip install -r requirements-dev.txt && pytest -q
cd desktop && npx tsc -b && npm run build
```

---

## F. Изменённые файлы

**Новые каталоги**
* `ecosystem/backend/` — config, app, db, models, security, deps, миграции Alembic,
  `services/` (ai_router, sync_engine, sync_worker, entities, schedule_import,
  device_service, core_bridge, serializers), `providers/`, `routers/` (auth, tasks,
  calendar, schedule, devices, ai, monitor, preferences, sync, telegram),
  `__main__.py` (CLI `--role/--port`).
* `ecosystem/agent/` — `runtime.py`, `wake.py`, `gateway.py`, `__main__.py`.
* `ecosystem/mini/` — `bot.py`, `hub_client.py`, `keyboards.py`, `formatting.py`, `__main__.py`.
* `desktop/` — Vite/React/TS приложение (`src/App.tsx`, `src/api.ts`, `src/ui.tsx`,
  `src/styles.css`, `src/components/Layout.tsx`, `src/pages/*` — 8 страниц + Login),
  `src-tauri/` (Rust-каркас, иконки), `scripts/`.
* `deploy/` — Dockerfile, compose, nginx, systemd.
* `tests/` — 11 файлов (110 тестов).
* `docs/` — ECOSYSTEM, DESKTOP_BUILD, DEPLOY, MINI_INTEGRATION, ECOSYSTEM_STATUS,
  REPORT_ECOSYSTEM.

**Изменённые файлы**
* `README.md` — раздел об Ecosystem Personal Edition и быстром старте.
* `.gitignore` — данные запуска, `node_modules`, `dist`, `*.db`, `deploy/.env`,
  `src-tauri/binaries/*`.
* Дополнительно созданы `requirements-ecosystem.txt`, `requirements-dev.txt`,
  `.env.example`, `pytest.ini`, `scripts/backup-hub.sh`.

**Не изменялись**: `core/`, `ai/`, `interface/`, `voice/`, `config.py`, `main.py`
(`git diff` пуст), существующая SQLite-база пользователя.

---

## G. Совместимость

* Core v1.5.10 продолжает запускаться как раньше (`main.py --console`, GUI-путь не тронут);
  монитор, личности и команды используются через `core_bridge`.
* Один и тот же backend работает в роли `desktop` и `hub` — кодовая база одна,
  отличия в конфигурации и включённых роутерах.
* БД: Alembic-миграции применяются автоматически, перед изменением существующей
  SQLite делается бэкап в `backups/`; `create_all` остаётся только для тестов.
* Windows 11 — целевая платформа (пути `%APPDATA%`, PowerShell-скрипт сборки);
  Linux/macOS поддержаны на уровне `FEDO_DATA_DIR` и systemd/Docker.
* API стабилен для Mini: `/api/bot/*` и `/api/devices` документированы контрактами.
* Офлайн-режим: без HUB Desktop полностью работоспособен, очередь копится и
  доедет после появления сети.

---

## H. Безопасность

| Требование | Реализация |
|------------|-----------|
| Пароли | scrypt + соль (`hash_password`/`verify_password`) |
| Сессии | случайный opaque-токен, хранение хеша, TTL, отзыв, `logout` |
| Токены устройств | отдельные `dev_…`, хеш в БД, ротация, отзыв, `401` на чужие |
| Роли | owner / bot-service / device, публичная регистрация выключена |
| Ограничение частоты | лимитер на логине и AI-эндпоинтах |
| CORS | только локальные origin Desktop |
| Валидация | Pydantic-модели, лимиты длины, запрет лишних полей |
| Ключи API | шифруются Fernet-ключом из `secret.key` (0600), в логи не попадают |
| Аудит | журнал входов, действий с устройствами, команд, AI-расходов |
| Изоляция владельца | `owner_id` на всех таблицах, проверка в каждом запросе |
| Telegram | никакого shell; только типизированные команды из белого списка, опасные — с подтверждением |
| AI | текст модели не превращается в действия напрямую; `local_only` гарантирует отсутствие сетевых вызовов |
| VPS | отдельные контейнеры, сеть, тома, только `127.0.0.1:8765`; GGSELL не затрагивался |
| Секреты в репозитории | отсутствуют: `.env` в `.gitignore`, `.env.example` пустой |

**Ограничения**: `secret.key` защищён правами файла, но не HSM/DPAPI;
CSP/ключи проверены статически; пентест и нагрузочное тестирование не проводились.
