# syntax=docker/dockerfile:1
FROM python:3.13-slim AS builder
ARG INSTALL_DEV=true
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
# Exact, hash-verified versions from the lock files (see scripts/update-python-lock.sh).
COPY requirements.lock requirements-dev.lock ./
RUN python -m venv /opt/venv \
    && if [ "$INSTALL_DEV" = "true" ]; then lock=requirements-dev.lock; else lock=requirements.lock; fi \
    && /opt/venv/bin/pip install --require-hashes -r "$lock"

FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH=/opt/venv/bin:$PATH
RUN groupadd --system --gid 10001 fidus \
    && useradd --system --uid 10001 --gid fidus --no-create-home fidus \
    && mkdir -p /data/files \
    && chown -R fidus:fidus /data/files
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=fidus:fidus alembic.ini ./
COPY --chown=fidus:fidus alembic ./alembic
COPY --chown=fidus:fidus app ./app
COPY --chown=fidus:fidus tests ./tests
COPY --chown=fidus:fidus pyproject.toml ./
USER fidus
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
