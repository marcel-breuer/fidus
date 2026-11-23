#!/bin/sh
# Regenerates frontend/openapi.json (exported from the backend code) and
# frontend/src/lib/api/schema.d.ts (types generated from it).
# With the argument "check" it also fails when either file differs from the committed version.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

# Build output must not reach the generated files, which are written from stdout.
docker compose build backend frontend-dev >&2

docker compose run --rm --no-deps -T backend python -m app.export_openapi > frontend/openapi.json
# The tools image carries its own copy of the sources, so write the result back through stdout.
docker compose run --rm -T frontend-dev npx --no-install openapi-typescript openapi.json > frontend/src/lib/api/schema.d.ts

if [ "${1:-}" = "check" ]; then
    git diff --exit-code -- frontend/openapi.json frontend/src/lib/api/schema.d.ts
fi
