# syntax=docker/dockerfile:1
FROM python:3.13-slim AS builder
ARG INSTALL_DEV=true
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml ./
# Resolve dependencies from the project metadata only, so this layer is cached until they change.
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/python - <<'PY' > requirements.txt
import os, tomllib
data = tomllib.load(open("pyproject.toml", "rb"))["project"]
print("\n".join(data["dependencies"]))
print("\n".join(data["optional-dependencies"]["dev"]) if os.environ["INSTALL_DEV"] == "true" else "")
PY
RUN /opt/venv/bin/pip install -r requirements.txt

FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH=/opt/venv/bin:$PATH
RUN groupadd --system --gid 10001 fidus && useradd --system --uid 10001 --gid fidus --no-create-home fidus
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
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
