#!/usr/bin/env bash
# Безопасное обновление HUB: бэкап → новый код в релизный каталог → рестарт →
# проверка health → автоматический откат при неудаче.
set -euo pipefail

APP_DIR="${FEDO_DIR:-/opt/fedo}"
DATA_DIR="${FEDO_DATA_DIR:-/var/lib/fedo}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${FEDO_PORT:-8765}"
REL_DIR="${APP_DIR}/releases/$(date +%Y%m%d-%H%M%S)"

log() { printf '\033[1;33m[FEDO]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[FEDO]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "запусти от root (sudo)"
[[ -d "$APP_DIR" ]] || die "сначала установи: scripts/ubuntu/install.sh"

log "1/6 Бэкап базы"
bash "$APP_DIR/current/scripts/ubuntu/backup.sh" || die "бэкап не удался — обновление отменено"

log "2/6 Состояние до обновления"
PREV_REV=$(cd "$APP_DIR/current" && "$APP_DIR/current/.venv/bin/python" -c "
import sqlite3,sys
try:
    print(sqlite3.connect('${DATA_DIR}/fedo.db').execute('select version_num from alembic_version').fetchone()[0])
except Exception:
    print('unknown')
" 2>/dev/null || echo unknown)
echo "$PREV_REV" > "$APP_DIR/.last_revision"

log "3/6 Копирую новую версию в $REL_DIR"
mkdir -p "$REL_DIR"
rsync -a --exclude '.git' --exclude '.venv' --exclude 'node_modules' \
  --exclude 'data*' --exclude '__pycache__' --exclude '*.db' "$REPO_DIR/" "$REL_DIR/"

log "4/6 Обновляю зависимости"
python3 -m venv "$REL_DIR/.venv"
"$REL_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$REL_DIR/.venv/bin/pip" install --quiet -r "$REL_DIR/requirements-ecosystem.txt"

log "5/6 Переключаю симлинк и перезапускаю"
if [[ -L "$APP_DIR/current" ]]; then mv "$APP_DIR/current" "$APP_DIR/previous"; fi
ln -sfn "$REL_DIR" "$APP_DIR/current"
systemctl restart fedo-hub.service

log "6/6 Проверяю health"
OK=0
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then OK=1; break; fi
  sleep 1
done
if [[ $OK -eq 1 ]]; then
  log "Обновление успешно: $(curl -s "http://127.0.0.1:${PORT}/api/health")"
else
  log "Health не прошёл — откатываю"
  bash "$APP_DIR/scripts/ubuntu/rollback.sh" || true
  die "обновление отменено, работает предыдущая версия"
fi
