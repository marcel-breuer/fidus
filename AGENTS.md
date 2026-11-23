# Fidus — Repository Agent Rules

These rules apply to every human or automated coding agent working in this repository, regardless of tool. This file is the canonical source for repository-wide rules. Tool-specific adapters reference it instead of duplicating it. Product decisions live in [docs/SPEC.md](docs/SPEC.md). Read the nearest local `AGENTS.md` if present, plus only the [skills](.agent/skills/README.md) relevant to the task.

## Instruction priority
1. Explicit task requirements and acceptance criteria.
2. Security, privacy and legal requirements.
3. Nearest local `AGENTS.md`, then this file.
4. Existing architecture and established patterns.
5. Repository configuration, tests, documentation.
6. Official framework documentation.

Do not invent requirements. On conflicting instructions, report the conflict and apply the stricter rule.

## Product boundaries — do not violate
1. **Multi-user from the start.** Every user-owned table has a `user_id`; every query is scoped to the authenticated user. No data access across users.
2. **One provider key.** Model access uses a single `OPENAI_API_KEY` from the environment. Models are fixed in the config file, not selectable at runtime.
3. **Private data stays private.** No sensitive values in logs, tests, docs or prompts by default. Uploaded files, transcripts and memory belong to their owner only.
4. **Agent actions are permission-bound.** Only typed, registered server-side tools; no model-provided raw SQL or arbitrary command execution. Writes by the agent (files, tasks) are attributed to the user and auditable.
5. **Modules are independent.** A module must not depend unconditionally on another module. Backend registry, API and sidebar enforce the same module policy.
6. **No private deployments in git.** No real hostnames, credentials, server paths or unrelated project references. Use placeholders and environment variables.
7. **Do not claim unimplemented behavior.** Docs and PRs describe only what exists.

## Architecture
- Backend: Python, FastAPI, SQLAlchemy (async), Alembic, fastapi-users, pytest. Business logic lives in services, not in route handlers.
- Frontend: SvelteKit, TypeScript, strict mode, accessible and mobile-first.
- Database: PostgreSQL with pgvector. Schema changes only through Alembic migrations.
- Runtime: Docker Compose with `db`, `backend`, `worker`, `frontend`. Only one service publishes a host port. Long-running work (transcription, indexing, reminders) runs in the worker.
- Internal and external knowledge access (RAG, web search) goes through service boundaries so it can be tested with fakes.

## Docker first
- Build, run and test inside Docker whenever possible. Inspect Dockerfiles and Compose files before changing them.
- `./start.sh` is the single entry point for a local stack: checks Docker, creates `.env` with fresh secrets from `.env.example` if missing, validates the Compose file, builds and starts everything, waits for health.
- Run Alembic migrations only inside the `backend` container.
- Host commands are allowed only when Docker is unavailable; state the exception and the remaining risk.
- Keep images multi-stage and minimal, run as non-root, add healthchecks, persist data in named volumes, never bake secrets into images.

Validation commands (once the stack exists):

| Purpose | Command |
| --- | --- |
| Start / rebuild stack | `./start.sh` |
| Validate Compose | `docker compose --env-file .env.example config --quiet` |
| Backend tests | `docker compose exec backend pytest` |
| Targeted backend test | `docker compose exec backend pytest tests/test_tasks.py -k reminder` |
| Migrations | `docker compose exec backend alembic upgrade head` |
| New migration | `docker compose exec backend alembic revision --autogenerate -m "<message>"` |
| Frontend tests | `docker compose run --rm frontend npm test` |
| Frontend type check and build | `docker compose run --rm frontend npm run check && docker compose run --rm frontend npm run build` |

## Testing
- Every functional change includes or updates tests: expected behavior, edge cases, regressions.
- Bug fixes start with a regression test that fails before the fix.
- Include negative tests for authorization: user A must never reach user B's data.
- Tests are deterministic and isolated. No live network calls; fake the OpenAI client, web search and clock.
- Never weaken, skip or rewrite tests only to make a change pass. Never claim a test passed that was not run.

## Code quality
- Keep route handlers thin, functions focused, abstractions justified by real duplication or risk.
- Type everything: Python type hints on public interfaces, strict TypeScript.
- Remove dead code, commented-out code and unused imports. Comments explain why, not what.
- Do not introduce unrequested public API or schema changes; call out breaking changes.
- Prefer existing patterns over personal preference.

## Frontend and i18n
- Every visible or assistive string goes through the i18n layer with German and English entries. No hard-coded UI copy.
- Reuse components in `frontend/src/lib/ui` before creating new markup. Provide loading, empty and error states.
- Keep accessibility: labels, focus handling, keyboard use, responsive layout.

## Security and privacy
- Secrets only via environment variables; document each in `.env.example`; never commit `.env`.
- Validate input at trust boundaries; parameterized queries only.
- Secure cookies, rate limits on auth endpoints, safe error messages.
- Treat uploaded files and transcribed audio as untrusted input.
- Do not send repository or user data to external services without explicit approval; the OpenAI API is the only approved external service.

## Dependencies
- Add a dependency only when the framework or existing code cannot reasonably solve the problem. Consider security, maintenance, license and size.
- Do not change lockfiles without a matching dependency operation. No unrelated or unrequested major upgrades.

## Git and workflow
1. Record concrete work as a GitHub Issue first. One focused pull request per issue, referencing it with `Closes #N`.
2. Branches: `feat/issue-N-description`, `fix/...`, `test/...`, `docs/...`.
3. Commits and PR titles use Conventional Commits and Semantic Versioning. Describe what changed, why, and how it was tested.
4. Keep changes small and reviewable. No unrelated refactors or formatting of untouched files. Preserve changes you did not make.
5. No destructive Git commands unless explicitly requested. Do not commit, push, tag or release unless asked.
6. Do not include assistant, automation or code-generation branding in code, comments, docs, commit messages, PR text or branch names.
7. Update docs (README, SPEC, `.env.example`) together with behavior or setup changes.

## CI/CD
Pipeline is intentionally minimal: unit tests, releases, tags.
- `quality-gates.yml` (PR and push to `main`): backend tests and frontend tests.
- `release-please.yml` (push to `main`): release PR, tags, GitHub releases; changelog from Conventional Commits.

**Rule: run every pipeline step locally before opening a PR** and report the exact commands and results in the PR description. Report steps that cannot run and why.

## Agent workflow
1. Read the task and acceptance criteria; read this file and relevant skills.
2. Inspect only relevant files; prefer targeted searches over full scans.
3. Plan the smallest viable change, implement it, add tests and docs.
4. Run validation, review the diff for unintended changes.
5. Report what changed, validation executed, assumptions and remaining risks concisely.

Be token-efficient: do not restate the task, do not narrate routine tool use, prefer diffs over full rewrites.

## Definition of done
Acceptance criteria met; architecture and security rules followed; tests exist and pass (or skipped checks are disclosed with risk); docs updated; no unintended files changed; assumptions and risks stated.
