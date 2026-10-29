#!/usr/bin/env bash
# Восстановление HUB из резервной копии.
#
# Безопасность прежде всего: скрипт НЕ запускается автоматически, всегда
# делает копию текущей базы перед заменой и требует явного подтверждения.
#
#   sudo -u fedo scripts/ubuntu/restore-hub.sh /var/lib/fedo/backups/fedo-20261029-071500.db
#
# Переменные:
#   FEDO_DATA_DIR  — каталог данных (по умолчанию /var/lib/fedo)
#   FEDO_SERVICE   — имя systemd-юнита (по умолчанию fedo-hub)
#   FEDO_YES=1     — не спрашивать подтверждение (для автоматизации)
set -euo pipefail

DATA_DIR="${FEDO_DATA_DIR:-/var/lib/fedo}"
SERVICE="${FEDO_SERVICE:-fedo-hub}"
DB="${DATA_DIR}/fedo.db"

SOURCE="${1:-}"
if [[ -z "${SOURCE}" ]]; then
  echo "Использование: $0 <путь к копии .db>" >&2
  echo "Доступные копии:" >&2
  ls -1t "${DATA_DIR}/backups"/*.db 2>/dev/null | head -10 >&2 || true
  exit 2
fi

if [[ ! -f "${SOURCE}" ]]; then
  echo "Файл копии не найден: ${SOURCE}" >&2
  exit 2
fi

# Копия должна быть настоящей базой Ecosystem, иначе восстановление бессмысленно.
if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "Нужен sqlite3 (apt install sqlite3)" >&2
  exit 3
fi
if ! sqlite3 "${SOURCE}" "select count(*) from sqlite_master where type='table' and name='owners'" \
     | grep -qx '1'; then
  echo "В файле нет таблицы owners — это не база Ecosystem. Отказ." >&2
  exit 4
fi

if [[ "${FEDO_YES:-0}" != "1" ]]; then
  echo "Текущая база: ${DB}"
  echo "Будет заменена копией: ${SOURCE}"
  read -r -p "Продолжить? (введите yes): " answer
  [[ "${answer}" == "yes" ]] || { echo "Отменено."; exit 1; }
fi

STAMP="$(date -u +%Y%m%d-%H%M%S)"
SAFETY="${DATA_DIR}/backups/pre-restore-${STAMP}.db"
mkdir -p "${DATA_DIR}/backups"

echo "1/5 Останавливаю сервис ${SERVICE}"
sudo systemctl stop "${SERVICE}" || true

echo "2/5 Сохраняю текущую базу в ${SAFETY}"
if [[ -f "${DB}" ]]; then
  sqlite3 "${DB}" ".backup '${SAFETY}'"
fi

echo "3/5 Проверяю целостность копии"
CHECK="$(sqlite3 "${SOURCE}" "pragma integrity_check;")"
if [[ "${CHECK}" != "ok" ]]; then
  echo "Копия повреждена: ${CHECK}" >&2
  echo "Возвращаю всё как было." >&2
  sudo systemctl start "${SERVICE}" || true
  exit 5
fi

echo "4/5 Заменяю базу (WAL-файлы убираются)"
rm -f "${DB}-wal" "${DB}-shm"
sqlite3 "${SOURCE}" ".backup '${DB}'"
chmod 640 "${DB}" 2>/dev/null || true

echo "5/5 Запускаю сервис и проверяю health"
sudo systemctl start "${SERVICE}"
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
    echo "Готово. HUB отвечает. Копия «до восстановления»: ${SAFETY}"
    exit 0
  fi
  sleep 1
done

echo "HUB не ответил за 30 с. Откат на копию «до восстановления»." >&2
sudo systemctl stop "${SERVICE}" || true
if [[ -f "${SAFETY}" ]]; then
  sqlite3 "${SAFETY}" ".backup '${DB}'"
  sudo systemctl start "${SERVICE}" || true
  echo "Откат выполнен. Проверь журнал: journalctl -u ${SERVICE} -n 50" >&2
fi
exit 6
