#!/usr/bin/env bash
# Restores a pg_dump backup into a NEW, separate database on the running
# `db` container -- never overwrites POSTGRES_DB in place. This is
# deliberate: restoring destructively over a live database is a one-way
# action, and the only way to actually prove a backup is restorable is to
# load it somewhere disposable and inspect it, which is also the safest
# way to do an emergency restore (inspect in scratch_restore, then promote
# it, rather than finding out the dump was bad only after wiping prod).
#
# Usage: scripts/restore-db.sh <path-to-dump-file> [target-db-name]
set -euo pipefail

DUMP_FILE="${1:?Usage: scripts/restore-db.sh <path-to-dump-file> [target-db-name]}"
TARGET_DB="${2:-restore_scratch}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

set -a
# shellcheck disable=SC1091
source "$REPO_ROOT/.env"
set +a

CONTAINER="sentinelbank-postgres"

if [ ! -f "$DUMP_FILE" ]; then
    echo "Dump file not found: $DUMP_FILE" >&2
    exit 1
fi

echo "Restoring $DUMP_FILE into new database '$TARGET_DB' on container '$CONTAINER'"
docker exec "$CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "DROP DATABASE IF EXISTS ${TARGET_DB};" \
    -c "CREATE DATABASE ${TARGET_DB};"

docker cp "$DUMP_FILE" "$CONTAINER:/tmp/restore.dump"
# MSYS_NO_PATHCONV scoped to just these two calls -- see backup-db.sh.
MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" pg_restore -U "$POSTGRES_USER" -d "$TARGET_DB" /tmp/restore.dump
MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" rm -f /tmp/restore.dump

echo "Restore complete into database '$TARGET_DB'. Inspect it before promoting:"
echo "  docker exec -it $CONTAINER psql -U $POSTGRES_USER -d $TARGET_DB"
echo
echo "To actually recover the live database from here (DESTRUCTIVE, drops the"
echo "current '$POSTGRES_DB'): stop the backend/migrate containers first, then"
echo "rename databases, e.g.:"
echo "  docker exec $CONTAINER psql -U $POSTGRES_USER -d postgres -c \"ALTER DATABASE $POSTGRES_DB RENAME TO ${POSTGRES_DB}_old;\""
echo "  docker exec $CONTAINER psql -U $POSTGRES_USER -d postgres -c \"ALTER DATABASE $TARGET_DB RENAME TO $POSTGRES_DB;\""
