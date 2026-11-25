# Fidus

Open-source, self-hostable personal assistant: a chat interface with a growing set of modules (chat, files, tasks, later calendar). Multi-user, FastAPI + SvelteKit + PostgreSQL/pgvector, powered by a single OpenAI API key.

The app includes sign-up and sign-in with registration modes and an admin screen, the module sidebar, row-level security, a background worker, Tasks with reminders, chat (streaming chat with memories, web search, citations, attachments, confirmed agent actions, read-aloud for assistant messages, short-clip dictation and a private agent activity log), Files (folder and file browser, versioned uploads, downloads, indexing and hybrid search), the audio module (recording or upload, transcription in the worker with ffmpeg, searchable transcripts, read-aloud), personal access tokens and OAuth 2.1 for MCP clients at `/mcp`, per-user usage counters (display only) and structured JSON logs. Admins can search and paginate users, share invitation management and review instance audit metadata. MCP exposes scoped task and file tools plus file and memo transcript resources. Quotas are not implemented. See [docs/SPEC.md](docs/SPEC.md) for scope and decisions.

Requirements: Docker with the Compose plugin and an OpenAI API key. Deployment is supported only through the provided Docker configuration.

## Quick start
```sh
git clone https://github.com/marcel-breuer/fidus
cd fidus
./start.sh
```
`start.sh` checks Docker, creates `.env` with fresh secrets, builds and starts the stack, then prints the address (default `http://localhost:8080`). The first account you register becomes the admin. `REGISTRATION_MODE` (`open`, `invite-only`, `closed`) is the default for registration afterwards; admins can change the mode at runtime in `/admin`. Set `OPENAI_API_KEY` in `.env` to enable chat and file embeddings.

Redis enforces configurable per-user request limits for chat (`CHAT_RATE_LIMIT_*`), file uploads (`FILE_UPLOAD_RATE_LIMIT_*`) and audio transcription uploads or chat dictation (`TRANSCRIPTION_RATE_LIMIT_*`). Requests above a limit return HTTP 429 with `Retry-After`; limits fail open if Redis is unavailable. The scheduler retries memos left pending or transcribing longer than `MEMO_TRANSCRIPTION_TIMEOUT_SECONDS` (default 30 minutes).

### Behind a reverse proxy
Set `TRUSTED_PROXIES` in `.env` to the comma-separated IPs or CIDRs of the proxy hops that connect to the gateway. Leave it empty when the gateway is directly exposed. The gateway resolves forwarded client addresses only through those trusted proxies.

### On a server
Put a TLS-terminating reverse proxy in front of the gateway, set `APP_URL` to the public `https://` address and `COOKIE_SECURE=true`, and consider `REGISTRATION_MODE=invite-only` or `closed`: with open registration every account can use your OpenAI key. The [runbook](docs/runbook.md) covers backup and restore (`scripts/backup.sh`, `scripts/restore.sh`), upgrade and rollback, secret rotation, logs and troubleshooting.

### Backups
```sh
scripts/backup.sh                                  # database dump + files volume into ./backups
scripts/restore.sh backups/fidus-<timestamp>       # refuses to overwrite a stack that holds data
scripts/restore.sh backups/fidus-<timestamp> --force
```
Backups contain private data and not `.env`; store both safely. Details in the [runbook](docs/runbook.md).

## Development
```sh
docker compose exec backend pytest                                   # backend tests
docker compose run --rm frontend-dev npm test                            # frontend tests
docker compose run --rm frontend-dev sh -c "npm run check && npm run build"
```
The frontend UI is built from [shadcn-svelte](https://shadcn-svelte.com) components (Tailwind CSS v4, bits-ui) under `frontend/src/lib/components/ui`, themed with the glass design in `frontend/src/app.css` (accent `#A4DDF5`, dark mode follows the system setting). New UI elements come from shadcn-svelte first: `cd frontend && npx shadcn-svelte add <component>` (see `components.json`), then adjust the glass classes if needed. The generated imports use the `#lib` alias. App-specific compositions built on those components (sidebar navigation, reminder banner, module icons, `ConfirmDialog` for destructive actions) live in `frontend/src/lib/components/app`. The glass look comes from the `glass-panel`, `glass-chrome`, `glass-inset`, `glass-control` and `glass-dialog` utility classes and the `--glass-*` tokens in `app.css`; the `markdown` class styles rendered chat Markdown.

The frontend uses a shared typed `openapi-fetch` client for browser and server API requests; its schema types come from `frontend/src/lib/api/schema.d.ts`. After changing backend API models, run `./scripts/api-client.sh` to regenerate `frontend/openapi.json` (exported from the backend) and `frontend/src/lib/api/schema.d.ts` (types generated from it) and commit both. `./scripts/api-client.sh check` regenerates them and fails if they differ from the committed files; CI runs it.

The backend tests create a scratch database named `<POSTGRES_DB>_test` and never touch the data database. They need the Postgres role in `DATABASE_OWNER_URL` to be allowed to create databases and roles (the bundled `db` service qualifies).

`BACKEND_INSTALL_DEV=false` in `.env` builds the backend image without pytest.

Backend dependencies are pinned with hashes in `backend/requirements.lock` (runtime) and `backend/requirements-dev.lock` (runtime plus tests); the image and CI install exactly those. After changing `backend/pyproject.toml`, run `./scripts/update-python-lock.sh` (needs Docker), review the diff and commit the lock files with the change.

## Documentation
- [Specification](docs/SPEC.md)
- [Architecture](docs/architecture/overview.md)
- [Operations runbook](docs/runbook.md)
- [Security review](docs/security-review.md)
- [Contributing](CONTRIBUTING.md)
- [Repository rules](AGENTS.md)
- [Releases](docs/releases.md)

## License
[MIT](LICENSE)
