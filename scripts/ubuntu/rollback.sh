#!/usr/bin/env bash
# Откат на предыдущую версию (симлинк previous) + проверка health.
set -euo pipefail

APP_DIR="${FEDO_DIR:-/opt/fedo}"
PORT="${FEDO_PORT:-8765}"

log() { printf '\033[1;33m[FEDO]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[FEDO]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "запусти от root (sudo)"
[[ -d "$APP_DIR/previous" ]] || die "нет предыдущей версии ($APP_DIR/previous)"

log "Переключаю на $APP_DIR/previous"
ln -sfn "$(readlink -f "$APP_DIR/previous")" "$APP_DIR/current"
systemctl restart fedo-hub.service

for _ in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    log "Откат выполнен: $(curl -s "http://127.0.0.1:${PORT}/api/health")"
    exit 0
  fi
  sleep 1
done
die "после отката health не отвечает — смотри journalctl -u fedo-hub -n 100"
