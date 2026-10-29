#!/usr/bin/env bash
# Резервная копия данных HUB (SQLite + секреты конфигурации).
# Запуск: ./scripts/backup-hub.sh [/var/lib/fedo] [/var/backups/fedo]
set -euo pipefail

DATA_DIR="${1:-/var/lib/fedo}"
BACKUP_DIR="${2:-/var/backups/fedo}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"
if [ -f "$DATA_DIR/fedo.db" ]; then
  # .backup — безопасно даже при работающем приложении (WAL)
  python3 - "$DATA_DIR/fedo.db" "$BACKUP_DIR/fedo-$STAMP.db" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as source, sqlite3.connect(dst) as target:
    source.backup(target)
print(dst)
PY
  gzip -f "$BACKUP_DIR/fedo-$STAMP.db"
  echo "backup: $BACKUP_DIR/fedo-$STAMP.db.gz"
else
  echo "no database at $DATA_DIR/fedo.db"
fi

# храним только 30 последних копий
ls -1t "$BACKUP_DIR"/fedo-*.db.gz 2>/dev/null | tail -n +31 | xargs -r rm -f
