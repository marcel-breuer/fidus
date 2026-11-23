#!/bin/sh
# Regenerates backend/requirements.lock (runtime) and backend/requirements-dev.lock (runtime + tests)
# with hashes, resolved for the Python version of the backend image. Run it after changing
# backend/pyproject.toml, review the diff and commit it together with the dependency change.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

docker run --rm -v "$repo_root/backend":/work -w /work python:3.13-slim sh -c '
    pip install --quiet --disable-pip-version-check pip-tools &&
    pip-compile --quiet --generate-hashes --strip-extras --allow-unsafe \
        --output-file requirements.lock pyproject.toml &&
    pip-compile --quiet --generate-hashes --strip-extras --allow-unsafe --extra dev \
        --output-file requirements-dev.lock pyproject.toml
'
printf '%s\n' "Updated backend/requirements.lock and backend/requirements-dev.lock."
