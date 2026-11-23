# Fidus

Open-source, self-hostable personal assistant: a chat interface with a growing set of modules (chat, files, tasks, later calendar). Multi-user, FastAPI + SvelteKit + PostgreSQL/pgvector, powered by a single OpenAI API key.

Status: early development. The app includes sign-up and sign-in, the module sidebar, row-level security, a background worker, Tasks with reminders, chat Stages 1–2, Files Stages 1–2 (folder and file browser, versioned uploads, downloads, indexing and hybrid search) and the audio module (recording or upload, transcription in the worker with ffmpeg, searchable transcripts, read-aloud). File blobs are stored in the persistent `files_data` Docker volume; include it in backups alongside the database. See [docs/SPEC.md](docs/SPEC.md) for scope and decisions.

## Quick start
```sh
git clone https://github.com/marcel-breuer/fidus
cd fidus
./start.sh
```
`start.sh` checks Docker, creates `.env` with fresh secrets, builds and starts the stack, then prints the address (default `http://localhost:8080`). The first account you register becomes the admin. `REGISTRATION_MODE` (`open`, `invite-only`, `closed`) controls registration afterwards. Set `OPENAI_API_KEY` in `.env` to enable chat and file embeddings.

### Behind a reverse proxy
Set `TRUSTED_PROXIES` in `.env` to the comma-separated IPs or CIDRs of the proxy hops that connect to the gateway. Leave it empty when the gateway is directly exposed. The gateway resolves forwarded client addresses only through those trusted proxies.

## Development
```sh
docker compose exec backend pytest                                   # backend tests
docker compose run --rm frontend-dev npm test                            # frontend tests
docker compose run --rm frontend-dev sh -c "npm run check && npm run build"
```
The frontend uses a shared typed `openapi-fetch` client for browser and server API requests; its schema types come from `frontend/src/lib/api/schema.d.ts`. After changing backend API models, run `./scripts/api-client.sh` to regenerate `frontend/openapi.json` (exported from the backend) and `frontend/src/lib/api/schema.d.ts` (types generated from it) and commit both. `./scripts/api-client.sh check` regenerates them and fails if they differ from the committed files; CI runs it.

The backend tests create a scratch database named `<POSTGRES_DB>_test` and never touch the data database. They need the Postgres role in `DATABASE_OWNER_URL` to be allowed to create databases and roles (the bundled `db` service qualifies).

`BACKEND_INSTALL_DEV=false` in `.env` builds the backend image without pytest.

Backend dependencies are pinned with hashes in `backend/requirements.lock` (runtime) and `backend/requirements-dev.lock` (runtime plus tests); the image and CI install exactly those. After changing `backend/pyproject.toml`, run `./scripts/update-python-lock.sh` (needs Docker), review the diff and commit the lock files with the change.

## Documentation
- [Specification](docs/SPEC.md)
- [Architecture](docs/architecture/overview.md)
- [Contributing](CONTRIBUTING.md)
- [Repository rules](AGENTS.md)
- [Releases](docs/releases.md)

## License
[MIT](LICENSE)
