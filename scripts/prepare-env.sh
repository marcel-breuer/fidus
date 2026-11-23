#!/bin/sh

set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file="$repo_root/.env"
example_file="$repo_root/.env.example"

if [ -f "$env_file" ]; then
    printf '%s\n' "Found .env; leaving the existing file unchanged."
    exit 0
fi

if ! command -v openssl >/dev/null 2>&1; then
    printf '%s\n' "OpenSSL is required to generate local secrets." >&2
    exit 1
fi

if [ ! -f "$example_file" ]; then
    printf '%s\n' ".env.example is missing." >&2
    exit 1
fi

secret_key=$(openssl rand -hex 32)
db_password=$(openssl rand -hex 32)
temporary_file=$(mktemp "$repo_root/.env.XXXXXX")
trap 'rm -f "$temporary_file"' EXIT HUP INT TERM

umask 077
sed \
    -e "s|^SECRET_KEY=.*|SECRET_KEY=$secret_key|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$db_password|" \
    "$example_file" > "$temporary_file"
chmod 600 "$temporary_file"
mv "$temporary_file" "$env_file"
trap - EXIT HUP INT TERM

printf '%s\n' "Created .env with fresh secrets (mode 600). Set OPENAI_API_KEY in .env before using the assistant."
