# Operations runbook

For operators of a Fidus instance started with `./start.sh` (locally or on an own server). All commands run from the repository root and go through Docker Compose. If you run several stacks on one machine, set `COMPOSE_PROJECT_NAME` the same way for every command, including the backup and restore scripts. Do not export `OPENAI_API_KEY` in the shell that runs Compose; the stack reads it from `.env`, and the scripts unset it for you.

## What holds state

| Item | Where | In a backup |
| --- | --- | --- |
| Accounts, conversations, tasks, memories, documents, chunks, tokens (hashed), usage counters, audit log | PostgreSQL, volume `db_data` | yes (`db.dump`) |
| Uploaded files, audio memos, cached read-aloud audio | volume `files_data` (`/data/files`) | yes (`files.tar.gz`) |
| Secrets and settings | `.env` | no, back it up separately and securely |
| Job queue, rate-limit counters, heartbeat | volume `redis_data` | no; queued but unprocessed jobs are lost, counters reset |

A backup contains private user data. Treat it like the database itself: restrictive permissions (the script creates it readable by you only), encrypted storage, off-machine copy.

## Backup

```sh
scripts/backup.sh                 # writes ./backups/fidus-<UTC timestamp>/
scripts/backup.sh -o /mnt/backup  # another target directory
```

The stack has to be running. The script writes `db.dump` (`pg_dump`, custom format), `files.tar.gz`, `manifest.txt` (app version, schema revision) and `SHA256SUMS`. It never overwrites an existing backup directory and removes a half-written one if it fails.

The database dump is transactionally consistent. The file archive is taken afterwards, so a file uploaded in between can be present in the archive but missing from the dump (it then is an unreferenced blob, which is harmless) or the reverse for deletions. For a strictly consistent copy, run the backup during a quiet period or stop the writers first: `docker compose stop backend worker scheduler`, run the backup script after `docker compose start backend` (the script needs the backend container to read the volume), then `docker compose start worker scheduler`.

Schedule it with cron or a systemd timer, keep several generations and test a restore regularly. Example crontab line (daily at 02:30, keep 14 days):

```sh
30 2 * * * cd /srv/fidus && scripts/backup.sh -o /srv/fidus-backups && find /srv/fidus-backups -maxdepth 1 -name 'fidus-*' -mtime +14 -exec rm -rf {} +
```

## Restore

```sh
scripts/restore.sh /path/to/fidus-20260101T020000Z            # refuses if the stack holds data
scripts/restore.sh /path/to/fidus-20260101T020000Z --force    # replaces database and files
```

What it does, in order: verifies the checksums, starts `db` and `redis`, runs the `migrate` service (this creates the application database role, which a dump does not contain), checks whether the stack already holds data (any user or any stored file) and stops there without `--force`. With `--force` it writes a safety backup of the current state to `./backups` (skip with `--no-safety-backup`), stops gateway, frontend, backend, worker and scheduler, drops and recreates the database, loads `db.dump`, replaces the contents of the files volume, runs the migrations again (so a backup from an older version is brought to the current schema) and starts the stack.

Restoring onto a new machine: clone the repository at the version of the backup (`manifest.txt` shows it), copy the old `.env` into place (the database passwords in it are applied by the `migrate` service; a fresh `.env` from `./start.sh` works too as long as `APP_DB_USER` and `POSTGRES_DB` match the old values), run `./start.sh`, then run the restore with `--force`. Users keep their passwords and tokens; sessions stored in the dump stay valid until they expire.

Restoring into a stack of an older code version than the backup is not supported: the migration revision in the backup would be unknown to the code. `manifest.txt` records the revision.

## Upgrade

1. Read the release notes and `CHANGELOG.md`; note breaking changes.
2. Back up: `scripts/backup.sh`. Keep the output until the upgrade has proven itself.
3. Get the new version: `git fetch --tags && git checkout vX.Y.Z` (or `git pull` on `main`).
4. Compare `.env.example` with your `.env` and add new variables. Never overwrite `.env`.
5. `./start.sh`. It rebuilds the images, runs the migrations in the one-shot `migrate` service before backend, worker and scheduler start, and waits until every service is healthy.
6. Check `docker compose ps` (all healthy), sign in, open the Usage page, send a chat message.

Never run `docker compose down --volumes` or `docker volume rm` as part of an upgrade; that deletes the data.

## Rollback

Migrations are not guaranteed to be reversible. The safe rollback is:

1. `git checkout` the previous tag.
2. If the failed upgrade changed the schema, restore the backup from step 2 of the upgrade: `scripts/restore.sh <backup> --force`. This restores database and files together and rebuilds the stack from the checked-out code.
3. If no migration ran (the upgrade failed before `migrate` completed), `./start.sh` on the previous tag is enough.

## Secret rotation

All secrets live in `.env`. After editing, apply with `docker compose --env-file .env up -d` (recreates the affected containers).

| Secret | How to rotate | Effect |
| --- | --- | --- |
| `OPENAI_API_KEY` | Create a new key at the provider, replace it in `.env`, `docker compose up -d backend worker`, revoke the old key. | None for users. |
| `APP_DB_PASSWORD` | Replace the value in `.env`, then `docker compose up -d`. The `migrate` service runs `ALTER ROLE` with the new password before the other services start. | Brief restart of backend, worker and scheduler. |
| `POSTGRES_PASSWORD` | Open `docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'`, run `\password <POSTGRES_USER value>` and enter the new password, then put the same value in `.env` and `docker compose up -d`. | Brief restart. |
| `SECRET_KEY` | Replace the value in `.env`, `docker compose up -d`. | It salts the hashed rate-limit keys only; sessions are random database-backed tokens and stay valid. Rate-limit counters reset. |
| User sessions | A user signs out everywhere in the app, or an admin deactivates the account (this revokes all its sessions). | |
| Personal access tokens | The owner revokes and recreates them in the settings. | |

If a secret leaked, rotate it first and investigate afterwards. A leaked `.env` means rotating all four values and revoking the provider key.

## Logs

Backend, worker and scheduler write one JSON object per line to stdout: `ts`, `level`, `service`, `logger`, `message`, and where available `request_id`, `route` (the route template, never the raw URL), `method`, `status`, `duration_ms`, `user_id`. Message text, prompts, answers, transcripts, file names, tokens, cookies and API keys are never logged; exceptions are logged as type and stack locations only. Every HTTP response carries an `X-Request-ID` header; send it when reporting a problem and search the logs for it. Jobs in the worker use their task id as `request_id`.

```sh
docker compose logs --no-log-prefix backend | grep '"request_id":"<id>"'
docker compose logs --no-log-prefix backend | jq -c 'select(.level != "INFO")'      # needs jq on the host
```

Health checks are not logged. Taskiq's own two start-up lines in the worker's main process are not JSON.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `./start.sh` stops with "port is already allocated" | Another process uses `APP_PORT`; change `APP_PORT` and `APP_URL` in `.env`. |
| Sign-in works but the next request is unauthorized over HTTPS | `COOKIE_SECURE=true` and `APP_URL=https://...` must be set when TLS is terminated in front of the gateway; with `COOKIE_SECURE=true` over plain HTTP the browser drops the cookie. |
| Requests from the browser return 403 `Cross-origin request refused` | `APP_URL` does not match the address in the browser (scheme, host, port). |
| `migrate` exits with an error, the stack does not come up | `docker compose logs migrate`. A wrong `APP_DB_USER` or `POSTGRES_PASSWORD` after a change in `.env` is the usual cause (see secret rotation). The database is untouched; fix `.env` and run `./start.sh` again. |
| Chat answers fail, file indexing shows `AI_NOT_CONFIGURED` | `OPENAI_API_KEY` is empty in `.env`; set it and `docker compose up -d backend worker`, then retry the item in the UI. |
| Uploads stay "pending" | Worker unhealthy: `docker compose ps worker`, `docker compose logs worker`; check Redis (`docker compose ps redis`). |
| Login rate limits do not apply | Redis is down; the limiters fail open by design and log a warning. |
| Restore fails with `role "fidus_app" does not exist` | The migrate step did not run; run `docker compose run --rm migrate` and retry. If you changed `APP_DB_USER` since the backup, set it back to the old value for the restore. |
| Disk full | `docker system df`; the large items are `db_data` and `files_data`. Prune only images and build cache: `docker image prune`, `docker builder prune`. Do not prune volumes. |
| Audio memo stuck in "transcribing" | A job died mid-way (tracked in issue #58). Retry the memo in the UI. |
| Reverse proxy shows every user with the proxy address | Set `TRUSTED_PROXIES` (see README). |

## TLS and headers

The gateway speaks plain HTTP. Terminate TLS in a reverse proxy in front of it and send `Strict-Transport-Security` there once HTTPS works for good (for example `max-age=31536000`), because the gateway cannot know the scheme the browser used. The gateway itself sets `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` and `Cross-Origin-Opener-Policy`; the frontend sets a Content-Security-Policy.
