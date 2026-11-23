# Skill: Docker Change

**Purpose:** Reproducible Docker Compose installation with a one-command start. **Use when:** Dockerfiles, Compose, `start.sh`, environment, healthchecks or image CI change.

**Procedure:**
1. Keep `./start.sh` working from a fresh clone: checks Docker, creates `.env` with generated secrets, validates Compose, builds, starts, waits for health.
2. Keep services separate: `db` (pgvector), `backend`, `worker`, `frontend`. Publish only one host port.
3. Use multi-stage builds, non-root users, healthchecks, `cap_drop: ALL`, `no-new-privileges`, named volumes for persistent data.
4. Run migrations as a one-shot service that other services wait for.
5. Keep hostnames, credentials and keys in `.env` only; every variable documented in `.env.example`.
6. Document generic install, upgrade and rollback steps.

**Validation:** `docker compose --env-file .env.example config --quiet`, image builds, healthy startup, persistence across restart. Report unrun checks honestly.

**Constraints:** No hard-coded deployment details. No required external services except the OpenAI API.
