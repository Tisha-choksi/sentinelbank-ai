#!/usr/bin/env bash
# Backs up the running `db` container's database to a timestamped
# custom-format pg_dump file under backups/. Safe to run against a live
# database -- pg_dump takes a consistent snapshot without blocking writers.
#
# Usage: scripts/backup-db.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$REPO_ROOT/backups"
mkdir -p "$BACKUP_DIR"

set -a
# shellcheck disable=SC1091
source "$REPO_ROOT/.env"
set +a

CONTAINER="sentinelbank-postgres"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="$BACKUP_DIR/sentinelbank_${TIMESTAMP}.dump"

echo "Backing up database '$POSTGRES_DB' from container '$CONTAINER' -> $OUT_FILE"
# MSYS_NO_PATHCONV scoped to just this call: Git Bash on Windows otherwise
# rewrites /tmp/backup.dump (a path INSIDE the Linux container) into a
# Windows host path. It must stay unset for `docker cp`'s local-side
# destination argument just below, which needs normal conversion.
MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F c -f /tmp/backup.dump
docker cp "$CONTAINER:/tmp/backup.dump" "$OUT_FILE"
MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" rm -f /tmp/backup.dump

echo "Backup complete: $OUT_FILE"
