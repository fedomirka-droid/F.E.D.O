# F.E.D.O. HUB — развёртывание

> Всё ниже — **инструкции**. Агент не менял VPS, firewall, SSH, VPN и не
> трогал другие проекты (например GGSELL). Перед применением — подтверждение владельца.

Связанные документы: [`.env.example`](../.env.example) (шаблон без секретов),
[`ECOSYSTEM_STATUS.md`](ECOSYSTEM_STATUS.md) (что проверено, а что нет),
[`DESKTOP_BUILD.md`](DESKTOP_BUILD.md) (ThinkPad на Windows 11),
[`MINI_INTEGRATION.md`](MINI_INTEGRATION.md) (Telegram-бот).

## Что где живёт

| Роль | Машина | Что запущено | Порт |
|------|--------|--------------|------|
| HUB | VPS Ubuntu 24.04 | `fedo-hub` (API+sync) и `fedo-mini` (Telegram) | `127.0.0.1:8765`, наружу через nginx+TLS |
| Desktop | ThinkPad, Windows 11 | `fedo-desktop` + WebView-окно | `127.0.0.1:8765` |
| GPU-агент | домашний ПК, RTX 3080 | `python -m ecosystem.agent` + LM Studio | исходящие к HUB |

HUB никогда не слушает публичный интерфейс: только loopback + nginx.

## Вариант A: Docker Compose (рекомендуется)

Изоляция: своя сеть `fedo_net`, свои тома `fedo_data`/`fedo_mini_data`,
свои имена контейнеров, порт публикуется только на `127.0.0.1:8765`.
Другие проекты не затрагиваются.

```bash
# 1. код
sudo install -d -o fedo -g fedo /opt/fedo
sudo -u fedo git clone <repo> /opt/fedo/app
cd /opt/fedo/app/deploy

# 2. окружение (секреты — только здесь, файл 0600)
sudo -u fedo cp ../.env.example .env
sudo -u fedo python3 -c "import secrets; print(secrets.token_urlsafe(48))"  # FEDO_SECRET_KEY
sudo -u fedo python3 -c "import secrets; print(secrets.token_urlsafe(32))"  # FEDO_BOT_SERVICE_TOKEN
sudo -u fedo chmod 600 .env

# 3. запуск
sudo docker compose up -d --build
sudo docker compose ps
curl -s http://127.0.0.1:8765/api/health

# 4. владелец (один раз). Если задан FEDO_SETUP_TOKEN — передай заголовок.
curl -X POST http://127.0.0.1:8765/api/auth/setup \
  -H 'Content-Type: application/json' \
  -H "X-Setup-Token: $FEDO_SETUP_TOKEN" \
  -d '{"username":"owner","password":"<длинный пароль>"}'
```

Проверка ограничений ресурсов:

```bash
sudo docker stats --no-stream fedo_hub fedo_mini
sudo docker compose logs --tail=100 hub
```

## Вариант B: systemd (без Docker)

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin fedo
sudo install -d -o fedo -g fedo /opt/fedo/app /opt/fedo/data /opt/fedo/data-mini
sudo -u fedo git clone <repo> /opt/fedo/app
cd /opt/fedo/app
sudo -u fedo python3 -m venv /opt/fedo/venv
sudo -u fedo /opt/fedo/venv/bin/pip install -r requirements-ecosystem.txt

sudo -u fedo cp .env.example /opt/fedo/.env
sudo -u fedo chmod 600 /opt/fedo/.env
# заполни FEDO_SECRET_KEY, FEDO_BOT_SERVICE_TOKEN, FEDO_TELEGRAM_BOT_TOKEN

sudo cp deploy/systemd/fedo-hub.service /etc/systemd/system/
sudo cp deploy/systemd/fedo-mini.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fedo-hub fedo-mini
sudo systemctl status fedo-hub --no-pager
```

## Nginx (свой домен, свой server-блок)

```bash
sudo cp deploy/nginx/fedo.conf /etc/nginx/sites-available/fedo.conf
# поправь server_name и пути к сертификатам
sudo ln -s /etc/nginx/sites-available/fedo.conf /etc/nginx/sites-enabled/fedo.conf
sudo nginx -t && sudo systemctl reload nginx
```

Никаких изменений в конфигурации других проектов не требуется: это
отдельный `server {}` для отдельного домена.

## Обновление

```bash
cd /opt/fedo/app
sudo -u fedo git pull --ff-only
sudo -u fedo /opt/fedo/venv/bin/python -c "from ecosystem.backend.config import get_settings; from ecosystem.backend.db import run_migrations; print(run_migrations(get_settings()))"
sudo systemctl restart fedo-hub fedo-mini    # или docker compose up -d --build
```

Миграции Alembic перед применением **автоматически делают копию SQLite**
в `backups/`.

## Проверка после установки (health checks)

```bash
# 1. процесс и версия
curl -s http://127.0.0.1:8765/api/health | jq '{status,version,role,core}'
# 2. миграции применены
sqlite3 /var/lib/fedo/fedo.db "select version_num from alembic_version;"
# 3. владелец существует (не должно быть пусто)
sqlite3 /var/lib/fedo/fedo.db "select username, created_at from owners;"
# 4. наружу по HTTPS (после nginx)
curl -s https://fedo.example.com/api/health | jq .status
# 5. бот отвечает только своим сервисным токеном
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/api/bot/today   # 401 без X-Bot-Token
```

Проверка из Desktop: Настройки → «Роль backend», «Версия экосистемы», «Ядро Core»
должны показать значения, а «Синхронизация» — `online: true`.

## Резервные копии

Три независимых уровня:

```bash
# 1. копия из UI: Настройки → «Создать копию сейчас» (SQLite backup API)
# 2. скрипт на сервере
sudo /opt/fedo/app/scripts/backup-hub.sh /opt/fedo/data /var/backups/fedo
# cron: 0 4 * * * /opt/fedo/app/scripts/backup-hub.sh
# 3. перед каждой миграцией Alembic копирует базу сам в data/backups/
```

Восстановление (останавливает сервис, сохраняет текущую базу, проверяет
`integrity_check`, при неудаче откатывается сам):

```bash
sudo -u fedo /opt/fedo/app/scripts/ubuntu/restore-hub.sh \
     /var/lib/fedo/backups/fedo-20261029-041500.db
```

Откат релиза (предыдущий каталог `releases/<ts>`):

```bash
sudo /opt/fedo/app/scripts/ubuntu/rollback.sh
```

## Windows 11: ноутбук

```powershell
# 1. Python 3.11+ и Node.js 20+ уже установлены
cd C:\FEDO\app
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements-ecosystem.txt
cd desktop; npm ci; npm run build; cd ..

# 2. первый запуск (создаст %APPDATA%\FEDO\fedo.db)
.venv\Scripts\python -m ecosystem.backend --role desktop

# 3. автозапуск при входе в систему
powershell -ExecutionPolicy Bypass -File scripts\windows\install-autostart.ps1
```

Проверка: <http://127.0.0.1:8765/api/health> → `role: desktop`, `core: v1.5.10`.
Остановить автозапуск: `powershell -ExecutionPolicy Bypass -File scripts\windows\install-autostart.ps1 -Uninstall`.

## Ограничения маленького VPS

* HUB — только API/синхронизация/бот; LLM на VPS **не запускаются**;
* лимиты в compose: hub 512 MB / 1 CPU, mini 192 MB / 0.5 CPU;
* SQLite + WAL достаточно для одного владельца и нескольких устройств;
* в systemd — `MemoryMax`, `CPUQuota`, `ProtectSystem=strict`.

## Что потребуется от владельца

| Что | Где взять |
|-----|-----------|
| Домен + TLS | certbot для своего домена |
| `FEDO_SECRET_KEY`, `FEDO_BOT_SERVICE_TOKEN` | сгенерировать, хранить в `.env` (0600) |
| Токен Telegram-бота | @BotFather |
| Токен устройства для Desktop | Desktop → Устройства → «＋ Устройство» |
| Адрес HUB | `FEDO_HUB_URL` на ноутбуке |
