#!/usr/bin/env bash
# Резервная копия базы HUB (SQLite, консистентно через .backup) + ротация.
set -euo pipefail

DATA_DIR="${FEDO_DATA_DIR:-/var/lib/fedo}"
KEEP="${FEDO_BACKUP_KEEP:-14}"
DB="${DATA_DIR}/fedo.db"
STAMP=$(date +%Y%m%d-%H%M%S)
OUT_DIR="${DATA_DIR}/backups"

command -v sqlite3 >/dev/null || { echo "нужен sqlite3 (apt install sqlite3)" >&2; exit 1; }
[[ -f "$DB" ]] || { echo "базы нет: $DB" >&2; exit 1; }
mkdir -p "$OUT_DIR"

sqlite3 "$DB" ".backup '${OUT_DIR}/fedo-${STAMP}.db'"
chmod 640 "${OUT_DIR}/fedo-${STAMP}.db"
echo "копия: ${OUT_DIR}/fedo-${STAMP}.db"

# ключ шифрования ключей провайдеров — отдельно, он не в базе
if [[ -f "${DATA_DIR}/secret.key" ]]; then
  cp "${DATA_DIR}/secret.key" "${OUT_DIR}/secret-${STAMP}.key"
  chmod 600 "${OUT_DIR}/secret-${STAMP}.key"
  echo "ключ:  ${OUT_DIR}/secret-${STAMP}.key (храни отдельно)"
fi

ls -1t "${OUT_DIR}"/fedo-*.db 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  echo "удаляю старую копию $old"
  rm -f "$old"
done | tail -5
