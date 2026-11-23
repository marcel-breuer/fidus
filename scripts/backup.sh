#!/usr/bin/env bash
# Back up a running Fidus stack: a PostgreSQL dump plus an archive of the files volume.
#
#   scripts/backup.sh [-o DIR]
#
# Writes <DIR>/fidus-<UTC timestamp>/ containing db.dump (pg_dump custom format), files.tar.gz,
# manifest.txt and SHA256SUMS. DIR defaults to ./backups. An existing backup directory is never
# overwritten. The backup holds private user data and is created readable by the current user only.
# The .env file (secrets) is NOT included; keep it in a separate, secure place.
#
# Honors COMPOSE_PROJECT_NAME and runs everything through `docker compose`.
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd -- "$script_dir/.." && pwd)"
cd "$root"

fail() { printf 'Error: %s\n' "$1" >&2; exit 1; }
usage() { printf 'Usage: %s [-o DIR]\n' "$0" >&2; exit 2; }

out_dir="$root/backups"
while getopts ":o:h" opt; do
    case "$opt" in
        o) out_dir="$OPTARG" ;;
        *) usage ;;
    esac
done

# A key in the shell must never leak into the compose project; the stack reads its own .env.
unset OPENAI_API_KEY
compose=(docker compose --env-file "$root/.env")
[[ -f "$root/.env" ]] || fail '.env not found. Run ./start.sh first.'

"${compose[@]}" exec -T db pg_isready -q >/dev/null 2>&1 || fail 'The db service is not running. Start the stack with ./start.sh.'
"${compose[@]}" exec -T backend true >/dev/null 2>&1 || fail 'The backend service is not running. Start the stack with ./start.sh.'

mkdir -p "$out_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$out_dir/fidus-$stamp"
[[ ! -e "$target" ]] || fail "$target already exists; refusing to overwrite it."

umask 077
mkdir "$target"
trap '[[ -f "$target/SHA256SUMS" ]] || { printf "Backup failed; removing the incomplete directory.\n" >&2; rm -rf "$target"; }' EXIT

printf 'Dumping the database.\n'
"${compose[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner' > "$target/db.dump"
[[ -s "$target/db.dump" ]] || fail 'The database dump is empty.'

printf 'Archiving the files volume.\n'
"${compose[@]}" exec -T backend tar -C /data/files -czf - . > "$target/files.tar.gz"
tar -tzf "$target/files.tar.gz" >/dev/null || fail 'The files archive is not readable.'

revision="$("${compose[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT version_num FROM alembic_version"' | tr -d '[:space:]')"
{
    printf 'created_at=%s\n' "$stamp"
    printf 'app_version=%s\n' "$(tr -d '[:space:]' < "$root/version.txt" 2>/dev/null || echo unknown)"
    printf 'schema_revision=%s\n' "$revision"
    printf 'database_format=pg_dump-custom\n'
} > "$target/manifest.txt"

(cd "$target" && if command -v sha256sum >/dev/null 2>&1; then sha256sum db.dump files.tar.gz manifest.txt; else shasum -a 256 db.dump files.tar.gz manifest.txt; fi > SHA256SUMS)

printf 'Backup written to %s\n' "$target"
printf 'Schema revision %s. Store it off this machine and keep .env separately.\n' "$revision"
