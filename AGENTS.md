# Repository guidelines

Read `docs/SPEC.md` first; it holds the product decisions.

## Layout
- `backend/` FastAPI app, Alembic migrations, pytest tests
- `frontend/` SvelteKit app
- `docker-compose.yml` local and production-like stack

## Rules
- Work inside the Docker environment where possible; inspect Dockerfiles and Compose files before changing them.
- Every functional change includes or updates tests (expected behaviour, edge cases, regressions).
- Commits and PR titles follow Conventional Commits. Describe what changed, why and how it was tested.
- All user-facing strings go through i18n (German and English).
- Every user-owned table has a `user_id`; all queries are scoped to the current user.
- Secrets only via environment variables; document new ones in `.env.example`.
- Code, comments and docs are written in English.
