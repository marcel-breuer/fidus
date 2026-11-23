#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh into the stack of this checkout.
#
#   scripts/restore.sh BACKUP_DIR [--force] [--no-safety-backup]
#
# Without --force the script refuses to touch a stack that already holds data (any user account
# or any stored file) and changes nothing. With --force it first writes a safety backup of the
# current state to ./backups (skip with --no-safety-backup), then stops the application services,
# replaces the database and the files volume with the backup, re-runs the migrations so an older
# backup is brought up to the current schema, and starts everything again.
#
# Honors COMPOSE_PROJECT_NAME and runs everything through `docker compose`.
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd -- "$script_dir/.." && pwd)"
cd "$root"

fail() { printf 'Error: %s\n' "$1" >&2; exit 1; }
usage() { printf 'Usage: %s BACKUP_DIR [--force] [--no-safety-backup]\n' "$0" >&2; exit 2; }

backup=""
force=0
safety=1
for arg in "$@"; do
    case "$arg" in
        --force) force=1 ;;
        --no-safety-backup) safety=0 ;;
        -h|--help) usage ;;
        -*) usage ;;
        *) [[ -z "$backup" ]] || usage; backup="$arg" ;;
    esac
done
[[ -n "$backup" ]] || usage
[[ -d "$backup" ]] || fail "$backup is not a directory."
backup="$(cd -- "$backup" && pwd)"

unset OPENAI_API_KEY
[[ -f "$root/.env" ]] || fail '.env not found. Run ./start.sh once (it creates .env), then restore.'
compose=(docker compose --env-file "$root/.env")

for file in db.dump files.tar.gz manifest.txt SHA256SUMS; do
    [[ -f "$backup/$file" ]] || fail "$backup/$file is missing; this is not a complete backup."
done
printf 'Verifying checksums.\n'
(cd "$backup" && if command -v sha256sum >/dev/null 2>&1; then sha256sum -c --quiet SHA256SUMS; else shasum -a 256 -c --quiet SHA256SUMS; fi) \
    || fail 'Checksum verification failed; the backup is damaged or was modified.'
tar -tzf "$backup/files.tar.gz" | grep -Eq '(^|/)\.\.(/|$)|^/' && fail 'The files archive contains unsafe paths.' || true

psql_db() { "${compose[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAq "$@"' sh "$@"; }

printf 'Starting the database and preparing the schema and roles.\n'
"${compose[@]}" up -d --wait db redis
"${compose[@]}" run --rm migrate >/dev/null

has_users="$(psql_db -c "SELECT EXISTS (SELECT 1 FROM users)" | tr -d '[:space:]')"
has_files="$("${compose[@]}" run --rm --no-deps -T backend sh -c 'find /data/files -mindepth 1 -print -quit' | tr -d '[:space:]')"
if [[ ( "$has_users" == "t" || -n "$has_files" ) && "$force" -ne 1 ]]; then
    fail 'This stack already holds data. Nothing was changed. Re-run with --force to replace it (a safety backup is made first).'
fi

if [[ ( "$has_users" == "t" || -n "$has_files" ) && "$safety" -eq 1 ]]; then
    printf 'Writing a safety backup of the current state.\n'
    "${compose[@]}" up -d --wait backend
    "$script_dir/backup.sh" -o "$root/backups"
fi

printf 'Stopping the application services.\n'
"${compose[@]}" stop gateway frontend backend worker scheduler

printf 'Replacing the database.\n'
"${compose[@]}" exec -T db sh -c '
    set -e
    psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
        -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE)" \
        -c "CREATE DATABASE \"$POSTGRES_DB\""
'
"${compose[@]}" exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error' < "$backup/db.dump"

printf 'Replacing the files volume.\n'
"${compose[@]}" run --rm --no-deps -T backend sh -c 'find /data/files -mindepth 1 -delete && tar -xzf - -C /data/files' < "$backup/files.tar.gz"

printf 'Applying migrations and starting the stack.\n'
"${compose[@]}" up -d --build --wait --wait-timeout 300

printf 'Restore complete from %s\n' "$backup"
