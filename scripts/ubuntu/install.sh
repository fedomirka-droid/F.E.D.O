#!/usr/bin/env bash
# F.E.D.O. HUB на Ubuntu 24.04 — установка в изолированный каталог.
#
# ВАЖНО: скрипт НЕ трогает другие сервисы (например GGSELL):
#   * свой каталог /opt/fedo, свои юниты fedo-hub.service / fedo-mini.service;
#   * свой venv, свой пользователь fedo, свои тома PostgreSQL/SQLite;
#   * порт 8765 слушается только на 127.0.0.1 — снаружи через nginx/HTTPS.
#
# Запуск: sudo bash scripts/ubuntu/install.sh
set -euo pipefail

APP_USER="${FEDO_USER:-fedo}"
APP_DIR="${FEDO_DIR:-/opt/fedo}"
DATA_DIR="${FEDO_DATA_DIR:-/var/lib/fedo}"
ENV_FILE="${FEDO_ENV_FILE:-/etc/fedo/fedo.env}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${FEDO_PORT:-8765}"

log() { printf '\033[1;33m[FEDO]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[FEDO] ОШИБКА:\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "запусти от root (sudo)"

log "Проверяю окружение"
command -v python3 >/dev/null || die "нужен python3 (apt install python3 python3-venv)"
python3 - <<'PY' || die "нужен Python 3.11+"
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY

if ss -ltn "sport = :${PORT}" 2>/dev/null | grep -q LISTEN; then
  die "порт ${PORT} уже занят другим сервисом — задай FEDO_PORT"
fi

log "Создаю пользователя ${APP_USER} (без shell-доступа к чужим каталогам)"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$APP_USER"

REL_DIR="${APP_DIR}/releases/$(date +%Y%m%d-%H%M%S)"
log "Копирую код в ${REL_DIR}"
install -d -o root -g root -m 755 "$APP_DIR" "${APP_DIR}/releases"
mkdir -p "$REL_DIR"
rsync -a --delete \
  --exclude '.git' --exclude '.venv' --exclude 'node_modules' --exclude 'data*' \
  --exclude '__pycache__' --exclude '*.db' \
  "$REPO_DIR/" "$REL_DIR/"
ln -sfn "$REL_DIR" "$APP_DIR/current"

log "Виртуальное окружение"
python3 -m venv "$REL_DIR/.venv"
"$REL_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$REL_DIR/.venv/bin/pip" install --quiet -r "$REL_DIR/requirements-ecosystem.txt"

log "Каталоги данных"
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$DATA_DIR"
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$DATA_DIR/backups"
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "${DATA_DIR}-mini"
install -d -o root -g "$APP_USER" -m 750 "$(dirname "$ENV_FILE")"

if [[ ! -f "$ENV_FILE" ]]; then
  log "Создаю ${ENV_FILE} со случайными секретами (права 640)"
  SECRET=$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')
  BOT_TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')
  cat >"$ENV_FILE" <<ENV
FEDO_ROLE=hub
FEDO_DATA_DIR=${DATA_DIR}
FEDO_HOST=127.0.0.1
FEDO_PORT=${PORT}
FEDO_SECRET_KEY=${SECRET}
FEDO_BOT_SERVICE_TOKEN=${BOT_TOKEN}
# Токен Telegram-бота: вписать вручную из @BotFather
FEDO_TELEGRAM_TOKEN=
# Публичный адрес HUB (для ссылок и Mini)
FEDO_PUBLIC_URL=
ENV
  chown root:"$APP_USER" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
else
  log "Конфигурация уже есть — не перезаписываю"
fi

log "systemd-юниты (только свои имена, чужие юниты не трогаются)"
for unit in fedo-hub fedo-mini; do
  sed -e "s|@APP_DIR@|${APP_DIR}|g" \
      -e "s|@DATA_DIR@|${DATA_DIR}|g" \
      -e "s|@ENV_FILE@|${ENV_FILE}|g" \
      -e "s|@PORT@|${PORT}|g" \
      "$REL_DIR/deploy/systemd/${unit}.service" > "/etc/systemd/system/${unit}.service"
  chmod 644 "/etc/systemd/system/${unit}.service"
done
systemctl daemon-reload
systemctl enable --now fedo-hub.service

log "Ждём health-check"
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    curl -s "http://127.0.0.1:${PORT}/api/health"; echo
    break
  fi
  sleep 1
done

cat <<INFO

Готово. Дальше:
  1) владелец создаётся один раз: POST /api/auth/setup (см. docs/DEPLOY.md);
  2) Telegram: вписать FEDO_TELEGRAM_TOKEN в ${ENV_FILE}, затем
     systemctl start fedo-mini.service;
  3) наружу — только через nginx из deploy/nginx/fedo.conf + сертификат;
  4) бэкапы: scripts/ubuntu/backup.sh (по cron), обновление: update.sh,
     откат: rollback.sh.
INFO
