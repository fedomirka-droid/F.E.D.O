# F.E.D.O. Ecosystem — Personal Edition · итоговый отчёт

Формат **A–L**. Дата: 2026-10-29. Ветка: `arena/3a9f3ab5-f-e-d-o`.
Статус: **Pilot-ready**, не Production. Один владелец, несколько устройств.

---

## A. Что уже существовало до этой работы

* **F.E.D.O. Core v1.5.10** — консольный и GUI-ассистент (`main.py`, `core/`, `ai/`,
  `interface/`, `voice/`): команды, монитор системы, память, характер, GOV-сборка.
* **F.E.D.O. Mini 2.1** — Telegram-бот на aiogram (свой процесс, свой конфиг).
* **Desktop-бэкенд Ecosystem** — FastAPI + SQLAlchemy + Alembic: владелец, сессии,
  задачи, календарь, расписание, устройства, AI Router, аудит, синхронизация.
* **Desktop UI** — React + TypeScript + Vite, тёмная тема, Tauri-обёртка.
* **Агент устройств** — heartbeat/poll, белый список действий, HMAC-подпись.
* **Тесты** — 110 pytest-тестов на момент коммита `236d324`.
* **Student Edition MVP** — в репозитории **отсутствует** (см. раздел J).

Версии на входе: Python 3.11.2, Node 22.22.3, npm 10.9.8, fastapi 0.162.0,
SQLAlchemy 2.1.6, alembic 1.20.1, pytest 9.2.0, pydantic 2.13.5, uvicorn 0.54.0,
backend `2.0.0-personal`, desktop `2.0.0`, Core `v1.5.10`.

> Про «Core 1.5.11 / 1.5.10»: в репозитории **нет** ни одного упоминания 1.5.11 —
> ни в коде, ни в конфигах, ни в документации. Единственный источник истины —
> `config.py: APP_VERSION = "v1.5.10"`, его и отдаёт `/api/health` (`core: v1.5.10`).
> Упоминание 1.5.11 в переписке было ошибочным и здесь исправлено.

---

## B. Что реально сделано (не описано, а работает)

### B.1. Синхронизация и офлайн-первый режим
* Outbox на Desktop, `change_log` + курсор на HUB, идемпотентность по `op_id`.
* Конфликт = несовпадение `base_version`; сохраняются обе версии, владелец решает.
* **Разрешение «Принять мою» доезжает до HUB** (было сломано — см. D.1).
* Backoff при недоступном HUB, авто-повтор после возврата, сброс `next_attempt_at`.
* **Натуральные ключи для сущностей с уникальностью на владельца**
  (`UNIQUE_ENTITY_KEYS`: `preference.key`, профиль студента) — иначе два узла с
  разными `owner_id` падали на `UNIQUE constraint failed`.
* Профиль студента читается и по детерминированному id, и по `owner_id`
  (`find_profile`) — запись, приехавшая с другого узла, больше не «теряется».

### B.2. Расписание
* Импорт XLS/XLSX, поиск столбца группы (`ИС-21`), соседние группы не читаются.
* Исправлен фильтр «шума»: строка с названием группы больше не считается
  служебной подписью; служебные подписи (`звонки`, `понедельник`, `ИС-21`) — считаются.
* `parse_date` понимает ISO (`2026-10-30` из `<input type="date">`), `30.10.2026`,
  `12.05`, `12 мая 2026`; невозможная дата → `None`, а не «сегодня».
* **Новое:** ручное создание занятия `POST /api/schedule` и правка
  `PATCH /api/schedule/{id}`; номер пары выводится из времени начала
  (`slot_for_time`), мусорное время отклоняется (422).
* Напоминания за 10 минут, дедупликация через `localStorage`.

### B.3. Student Edition — совместимый слой (интеграция заблокирована)
* Профиль студента: группа, колледж, специальность, курс, семестр, форма
  обучения, зачётка, заметки; синхронизируется как сущность `student_profile`.
* Сканер `detect_legacy()`: что найдено/чего нет, какие таблицы в найденных базах,
  признаки студенческой базы; **собственная база Ecosystem исключается**.
* Импорт чужой SQLite: задачи (синонимы колонок `name/title`, `prio/priority`,
  `state/status`, `deadline/due_date`, `estimate/spent`), занятия, профиль,
  сопоставление пользователей **без создания второго владельца**.
* Идемпотентность: журнал `legacy_import_records` + сверка по содержимому;
  `dry_run` показывает результат и ничего не пишет.
* Статус честный: `integration: "blocked"`, `POST /api/student/import` без
  источника → **409** с текстом «Исходники Student Edition MVP отсутствуют».

### B.4. Агент устройств (11 действий, least privilege)
Безопасные: `status`, `stats`, `ai_check`. Опасные (подтверждение владельца):
`ai_start`, `ai_stop`, `lock`, `sleep`, `shutdown(delay)`, `launch(app,command)`,
`stop_app(app,command)`, `wol(mac,broadcast)`.

* Команда подписана HMAC (в подписи участвует `expires_at`), TTL 300 с.
* Выдача одноразовая: `executed_at` проставляется в момент выдачи, повторно
  команда не придёт; протухшая не выдаётся и помечается `expired`.
* Агент исполняет **только то, что разрешено локально**: `--allow-lock`,
  `--allow-power`, `--allow-wol`, `--allow-ai-control`, `--allow-app МЕТКА=ПУТЬ`.
  Всё остальное → `failed` с причиной `denied`.
* HUB дополнительно проверяет `command_allowlist` устройства: незаявленное
  приложение отклоняется ещё до постановки в очередь (HTTP 400).
* Привязка нового устройства — **одноразовым кодом** (`/api/devices/pairing-code`
  → `/api/devices/pair`), код живёт 5 минут, повторное использование → 400.
* Все команды и результаты — в `audit_log`.

### B.5. AI Router
* Единый интерфейс: локальная LM Studio → одобренное облако (провайдер+ключ) →
  понятная ошибка. Провайдеры: local, gemini, openai-совместимый, домашний узел.
* Проверка здоровья (`/api/ai/health`): список локальных моделей, доступность
  облака и причина отказа, план fallback.
* Приватность: `local_only` принудительно выключает `allow_cloud`; облако без
  согласия не вызывается; ключи шифруются `SecretBox`, в логи не попадают.
* Системные команды (`время`, `состояние системы`) обслуживает Core, а не модель —
  AI не получает прав на команды.

### B.6. Backup и системная информация
* `POST /api/system/backup` — согласованная копия через SQLite backup API,
  проверка читаемости, SHA-256, ротация (20 последних), аудит.
* `GET /api/system/backups`, `GET /api/system/info` (роль, версия, каталоги,
  настроен ли Telegram; секретов не отдаёт).
* `scripts/ubuntu/restore-hub.sh` — восстановление с `integrity_check`,
  обязательной копией «до» и авто-откатом при неудачном старте.

### B.7. Desktop UI
* Dashboard: HUB, устройства, задачи на сегодня, следующая пара, синхронизация, AI.
* Tasks: CRUD, приоритет, срок, старт/финиш, учёт времени, «+15 минут» (три
  разных действия: план, срок, факт).
* Schedule: сегодня/завтра, импорт XLSX, ручное добавление и удаление,
  напоминания, «всё расписание».
* Assistant: выбор модели, локально/облако, согласие на облако, история диалогов.
* Devices: список, online/offline, CPU/RAM/GPU, белый список приложений, история команд.
* Settings: тема/масштаб, сессии и отзыв, AI Router, синхронизация и конфликты,
  профиль студента, **кнопка создания резервной копии**, Telegram-привязка, аудит.
* Кнопок-украшений нет: каждая либо вызывает API, либо заблокирована.

### B.8. Telegram Mini
`/start /today /tomorrow /tasks /devices /status /ai` + inline-кнопки:
начать, завершить, +15 минут, пропустить, проверить ПК, обновить статус.
Работает через HUB API (`HubClient`), **не открывает SQLite другого процесса**.

---

## C. Изменённые и созданные файлы

**Создано:**
```
ecosystem/backend/services/student.py                     совместимый слой Student Edition
ecosystem/backend/routers/student.py                      профиль, статус, импорт
ecosystem/backend/routers/system.py                       backup/list/info
ecosystem/backend/migrations/versions/a7c41d90e2b5_*.py   профиль + коды привязки + replay
ecosystem/backend/migrations/versions/c3f81a5d7e42_*.py   журнал импорта
tests/test_ecosystem_integration.py                       29 интеграционных тестов
desktop/src/api.test.ts                                   11 frontend-тестов (vitest)
docs/STUDENT_EDITION_GAP.md                               точный список недостающего
scripts/ubuntu/{install,update,rollback,backup,restore-hub}.sh
scripts/windows/{start-desktop,install-autostart,backup-desktop}.ps1
```

**Изменено (ключевое):**
```
ecosystem/backend/models.py                 StudentProfile, LegacyImportRecord, PairingCode, replay-поля
ecosystem/backend/services/sync_engine.py   UNIQUE_ENTITY_KEYS + resolve_unique_entity
ecosystem/backend/services/schedule_import.py  фильтр шума, ISO-даты
ecosystem/backend/routers/schedule.py       POST/PATCH занятия, slot_for_time
ecosystem/backend/app.py                    роутер system
ecosystem/backend/routers/{devices,tasks,ai}.py, services/{device_service,ai_router,core_bridge}.py
ecosystem/agent/{__main__,runtime}.py       новые действия и политика
ecosystem/mini/{bot,keyboards}.py           команды и кнопки
desktop/src/api.ts, pages/{Dashboard,Tasks,Schedule,Devices,Assistant,Settings}.tsx
desktop/{package.json,vite.config.ts}       vitest, конфиг тестов
tests/{test_sync,test_schedule_import,test_devices_agent}.py
docs/{ECOSYSTEM_STATUS,REPORT_ECOSYSTEM,DEPLOY}.md
```

Diff по незакоммиченному состоянию: **31 файл, +3004 / −107** (плюс 9 новых
файлов и каталоги скриптов).

---

## D. Найденные и исправленные проблемы

1. **Разрешение конфликта «моя версия» не доходило до HUB.** Локальное применение
   писалось в outbox, но при роли HUB не создавало `change_log`; третье устройство
   оставалось со старыми данными. Исправлено: HUB-ветка пишет `SyncOperation` и
   `change_log`, а не outbox.
2. **Импорт расписания отбрасывал все занятия.** `_is_noise_cell()` считал «шумом»
   любую строку, где предмет совпадает с нормализованным названием группы.
   Исправлено: точное сравнение с `NOISE_LABELS` + регулярка заголовка группы
   `[А-ЯЁA-Z]{2,5}[\s\-–—]*\d{1,2}`.
3. **ISO-дата не распознавалась** — `<input type="date">` присылает `2026-10-30`,
   парсер его не понимал и занятия уходили в «дата не определена».
   Добавлен `ISO_DATE_RE`, невозможные даты (`2026-13-45`) отбрасываются.
4. **Смена профиля студента не уезжала на HUB**: `update_profile` писала ORM
   напрямую, минуя outbox. Переведено на `entities.update_entity`, добавлен
   `source` (`manual` / `legacy_import`).
5. **`UNIQUE constraint failed: student_profiles.owner_id` при pull.** id профиля
   выводился из `owner_id`, а он у каждого узла свой. Добавлены `UNIQUE_ENTITY_KEYS`
   и `resolve_unique_entity()` в обе ветки (HUB `apply_operation` и клиент
   `apply_remote_change`), ответ помечается `resolved: "natural_key"`.
6. **`/api/student/status` терял синхронизированный профиль** — читал только по
   детерминированному id. Добавлен `find_profile()` (id → `owner_id`).
7. **`slot` занятия не сохранялся при ручном создании** — в модели это `int`
   (номер пары), а передавалась строка времени, и `normalize_value` превращал её
   в 0. Добавлен `slot_for_time()` по сетке звонков.
8. **Своя база считалась источником импорта** (пользователь «импортировал» сам
   себя). `inspect_database()` отбрасывает базы с таблицами
   `owners/devices/outbox/change_log/sync_operations`.
9. **Дубли строк внутри legacy-базы** давали две задачи. Дедупликация по
   названию/тройке `дата+время+предмет` + журнал импорта.

---

## E. Тесты и проверки — фактические результаты

```
$ .venv/bin/python -m pytest
149 passed in 32.63s

$ cd desktop && npx tsc --noEmit
(0 ошибок)

$ cd desktop && npx vitest run
Test Files  1 passed (1)
     Tests  11 passed (11)

$ cd desktop && npm run build
dist/index.html                   0.47 kB │ gzip:  0.30 kB
dist/assets/index-D7dsnY0m.css   12.10 kB │ gzip:  3.28 kB
dist/assets/index-DskMCoR5.js   226.90 kB │ gzip: 68.86 kB
✓ built in 1.11s
```

Базовая точка (`git worktree` на `236d324`): **110 passed**, файла
`test_ecosystem_integration.py` ещё не было, `test_sync.py` — 13 тестов,
`test_schedule_import.py` — 17.

**Арифметика роста** (раньше расхождение объяснялось параметризацией — теперь
сверены оба счётчика: сумма по файлам = итог запуска):

| Файл | Было | Стало |
|------|------|-------|
| `test_ecosystem_integration.py` | — | 29 |
| `test_sync.py` | 13 | 20 |
| `test_schedule_import.py` | 17 | 20 |
| остальные (8 файлов) | 80 | 80 |
| **Итого** | **110** | **149** |

`110 + 29 + 7 + 3 = 149`. `pytest --collect-only` даёт те же 149.

### Живые проверки (реальные процессы, не моки)

| Проверка | Что сделано | Результат |
|----------|-------------|-----------|
| Core не сломан | `printf 'время\nсостояние системы\nвыход\n' \| python main.py --console` | «Текущее время», платформа, CPU/RAM/диск, корректный выход; `git diff` по Core — 0 файлов |
| SPA отдаётся | `GET :8788/`, `/assets/index-DskMCoR5.js`, `/tasks` | 200 / 200 (234 301 B) / 200 (fallback) |
| Профиль | `PUT /api/student/profile` → HUB | `ИС-21`, курс 3, зачётка `21-ИС-042` |
| Занятие вручную | `POST /api/schedule` | `Сети`, пара 1; `/tomorrow` → `[('09:00','Сети')]` |
| Бэкап | `POST /api/system/backup` | 364 544 B, SHA-256 `6e0c82363495…`, копия открывается, `tasks` внутри есть |
| Привязка устройства | код → `/api/devices/pair` | устройство создано; **повторный код → 400** |
| Агент, разрешённые действия | lock / launch / shutdown / wol | `done` (с подтверждением владельца) |
| Агент, запрещённые | незаявленное приложение / питание без флага | HUB → 400 «не разрешено»; агент → `failed`, `denied: true` |
| AI Router локально | заглушка LM Studio на :1234 | `provider: local`, модель `stub-llama-3.1-8b` |
| AI Router без ключа | `cloud_preferred`, ключа нет | `trace: cloud failed («Gemini API-ключ не настроен») → local ok` |
| Приватность | `local_only` + `allow_cloud=true` | после сохранения `allow_cloud` → `False` |
| Два узла | hub :8795 + desktop :8796 | `pushed 2 / applied 2`, конфликт, `resolve local` → HUB получил «Версия ноутбука» |
| Офлайн | HUB остановлен, 4 правки на ноутбуке | `ok: false`, `pending_operations: 4`, очередь `task×3 + student_profile` |
| Восстановление | HUB поднят, `POST /api/sync/run` | `pushed 4 / applied 4`, задачи и `semester: 6` на HUB, outbox пуст |
| Миграции | `alembic upgrade head` на копии с данными | `a7c41d90e2b5 → c3f81a5d7e42`, задача «До миграции» на месте, новая таблица создана |
| Защита API | запросы без токена | `401` на `/api/system/backup`, `/api/tasks`, `/api/sync/pull` |

---

## F. Что требует внешних подключений и устройств

1. **Rust toolchain + MSVC Build Tools** → `npm run tauri build` и `.msi`/`.exe`.
   В песочнице Rust нет: **инсталлятор не собран**, и это не заявляется.
2. **LM Studio на RTX 3080** (`FEDO_LOCAL_AI_URL`, `--ai-endpoint`) → реальные
   генерации; сейчас проверено на локальной заглушке с OpenAI-контрактом.
3. **Ключ Gemini / OpenAI-совместимого провайдера** → облачные ответы
   (`POST /api/ai/keys/{provider}`). Без ключа Router честно уходит в локал.
4. **Токен @BotFather** → живой Telegram. Код и контракт проверены тестами.
5. **VPS Ubuntu 24.04** → деплой по `docs/DEPLOY.md`; **не выполнялся**.
6. **Домашний ПК + WoL** → реальные lock/sleep/shutdown/launch и пробуждение.
7. **Исходники/архив Student Edition** → полная интеграция (раздел J).

---

## G. Windows 11: ThinkPad

```powershell
# prerequisites: Python 3.11+, Node.js 20+, (для инсталлятора) Rust + MSVC
git clone <repo> C:\FEDO\app; cd C:\FEDO\app
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements-ecosystem.txt
cd desktop; npm ci; npm run build; cd ..

# запуск backend + окно
powershell -ExecutionPolicy Bypass -File scripts\windows\start-desktop.ps1 -Build
# автозапуск при входе (Планировщик, задача FEDO-Desktop)
powershell -ExecutionPolicy Bypass -File scripts\windows\install-autostart.ps1
# отключить
powershell -ExecutionPolicy Bypass -File scripts\windows\install-autostart.ps1 -Uninstall
```

Данные: `%APPDATA%\FEDO\` (база, `secret.key`, `backups\`, `logs\`).
Проверка: <http://127.0.0.1:8765/api/health> → `role: desktop`, `core: v1.5.10`.
Подключение к HUB: `FEDO_HUB_URL` + `FEDO_SYNC_DEVICE_TOKEN` (выдаётся в
Desktop → Устройства → привязка по коду).

---

## H. Ubuntu 24.04: VPS (HUB + Telegram)

Полный текст — `docs/DEPLOY.md`. Кратко:

```bash
sudo bash scripts/ubuntu/install.sh          # /opt/fedo, пользователь fedo, юниты, venv
sudo -u fedo nano /etc/fedo/fedo.env         # FEDO_SECRET_KEY, FEDO_BOT_SERVICE_TOKEN, FEDO_TELEGRAM_BOT_TOKEN
sudo systemctl enable --now fedo-hub fedo-mini
curl -s http://127.0.0.1:8765/api/health | jq
```

Изоляция: свой каталог `/opt/fedo`, свои юниты `fedo-hub`/`fedo-mini`, свой
пользователь, свой venv, порт только на loopback, наружу — отдельный
`server {}` в nginx. **GGSELL и чужие сервисы не затрагиваются**: firewall, SSH,
VPN и production-сервисы не менялись. Обновление — `scripts/ubuntu/update.sh`
(миграции с автобэкапом, health-проверка, авто-откат), откат —
`scripts/ubuntu/rollback.sh`, восстановление —
`scripts/ubuntu/restore-hub.sh`.

---

## I. Telegram и LM Studio

**Telegram:**
1. `FEDO_TELEGRAM_BOT_TOKEN` и `FEDO_BOT_SERVICE_TOKEN` в `/etc/fedo/fedo.env`.
2. `systemctl restart fedo-mini`.
3. Desktop → Настройки → «Создать код» → в боте `/link КОД` (код одноразовый, 10 мин).
4. Проверка: `/today`, `/devices` → «Проверить компьютер», кнопки задач.
Бот ходит только в HUB API через сервисный токен; владельческие эндпоинты ему
недоступны; чужие SQLite он не открывает.

**LM Studio:**
1. На ПК с RTX 3080: LM Studio → Developer → Start Server (по умолчанию :1234).
2. Desktop → Настройки → AI Router → `FEDO_LOCAL_AI_URL=http://127.0.0.1:1234/v1`.
3. Кнопка «Проверить» → список моделей; выбор модели; режим `local_only`.
4. Облако — только после явного согласия (галочка «Согласие на облако»),
   ключ шифруется, в логи не пишется.

---

## J. Что осталось

1. **Student Edition:** исходников нет → интеграция **blocked**. Нужен любой из
   артефактов: `student_edition/`, `student_edition.db`, `data/student_edition.db`,
   `F.E.D.O-Student-Edition-MVP.zip`. Точный список — `docs/STUDENT_EDITION_GAP.md`.
   Слой совместимости и импортёр готовы и проверены на синтетической базе.
2. Сборка Tauri-инсталлятора на Windows (нужен Rust).
3. Реальный деплой VPS (нужно подтверждение владельца).
4. Живые проверки: LM Studio, Gemini, Telegram, WoL, WebView2-уведомления.
5. Автослияние конфликтов по полям (сейчас выбор версии целиком).
6. Экспорт данных (CSV/ICS) — не реализовано, в отчёте не заявляется.

---

## K. Ограничения и риски

* **Не Production.** Один владелец, SQLite+WAL, отсутствие горизонтального
  масштабирования, нет миграции на PostgreSQL.
* **No public exposure:** HUB слушает `127.0.0.1`; публикация только через
  nginx+TLS. Открывать `/api/admin` или агентов в интернет нельзя.
* **Core GUI** в песочнице не запускался (нет `tkinter`/дисплея). Файлы Core не
  менялись, консольный режим проверен.
* **Импорт Student Edition** эвристический по именам колонок: при необычной схеме
  часть полей может не перенестись — предупреждения выводятся, данные не выдумываются.
* **Агент** без флагов `--allow-*` почти всё запрещает — это by design, но при
  настройке легко забыть, и действие вернёт `denied`.
* **Резервные копии** локальные: копия на том же диске не спасает от отказа диска,
  нужна выгрузка (rsync/внешний диск) — скрипт этого не делает.
* **Секреты** живут в `.env` (0600) и `secret.key`; потеря `secret.key` =
  потеря расшифровки API-ключей.
* **Конфликты**: «моя»/«серверная» версия целиком; частичного слияния нет.

---

## L. Git и артефакты

* Кодовая база и скрипты: коммит **`4e5974e`** (эта ветка).
* Документация (этот отчёт, `ECOSYSTEM_STATUS.md`, `DEPLOY.md`,
  `STUDENT_EDITION_GAP.md`): следующий коммит этой же ветки.
* Базовая точка для сравнения: `236d324` (110 тестов, Core v1.5.10).
* Собранный frontend: `desktop/dist/` (пересобран, 226.90 kB JS).
* Тестовые артефакты: `data-dev/`, `/tmp/final-live` (одноразовые, в Git не входят).
* Инструкции: `docs/DEPLOY.md`, `docs/DESKTOP_BUILD.md`, `docs/MINI_INTEGRATION.md`,
  `docs/STUDENT_EDITION_GAP.md`, `.env.example`.
