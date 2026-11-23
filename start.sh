#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

fail() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

command -v docker >/dev/null 2>&1 || fail 'Docker is not installed or not on PATH. Install Docker with the Compose plugin, then run ./start.sh again.'
docker compose version >/dev/null 2>&1 || fail 'Docker Compose v2 is unavailable. Install or enable the Compose plugin, then run ./start.sh again.'

if ! docker info >/dev/null 2>&1; then
    printf '%s\n' 'Docker is not ready; attempting to start it.'
    case "$(uname -s)" in
        Darwin) open -a Docker >/dev/null 2>&1 || true ;;
        Linux)
            if command -v systemctl >/dev/null 2>&1; then
                if [[ "$(id -u)" -eq 0 ]]; then
                    systemctl start docker || fail 'Could not start Docker with systemctl.'
                else
                    sudo systemctl start docker || fail 'Could not start Docker. Check that your account can use sudo.'
                fi
            else
                fail 'Docker is not running. Start the Docker service, then run ./start.sh again.'
            fi
            ;;
        *) fail 'Docker is not running. Start Docker, then run ./start.sh again.' ;;
    esac

    ready=0
    for _ in {1..60}; do
        if docker info >/dev/null 2>&1; then ready=1; break; fi
        sleep 1
    done
    [[ "$ready" -eq 1 ]] || fail 'Docker did not become ready within 60 seconds.'
fi

"$script_dir/scripts/prepare-env.sh"

printf '%s\n' 'Validating Docker Compose configuration.'
docker compose --env-file .env config --quiet

if ! grep -Eq '^OPENAI_API_KEY=.+' .env; then
    printf '%s\n' 'Warning: OPENAI_API_KEY is empty in .env. The stack starts, but the assistant cannot answer until it is set.' >&2
fi

printf '%s\n' 'Building Fidus and starting the complete stack. Persistent data is kept.'
docker compose --env-file .env up --detach --build --wait --wait-timeout 180

app_port="${APP_PORT:-$(sed -n 's/^[[:space:]]*APP_PORT[[:space:]]*=[[:space:]]*//p' .env | tail -n 1 | tr -d "\"'[:space:]")}"
app_port="${app_port:-8080}"

printf '\nFidus is ready at http://localhost:%s\n' "$app_port"
printf '%s\n' 'Run ./start.sh again to rebuild and start the stack after a restart or update.'
