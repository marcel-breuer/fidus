# Security review

Scope: the whole repository at the hardening step for the first release (issue #23), with the admin audit/invitation database boundary reviewed for issues #62 and #63. Date: 2026-11-24. Method: code reading, schema inspection on a migrated database, header and cookie inspection against a running stack, `pip-audit`, `npm audit`. A review at one point in time, not a penetration test; re-run it for releases that touch authentication, storage or the gateway.

## Summary

| # | Finding | Severity | Status |
| --- | --- | --- | --- |
| 1 | Security headers were missing on `/api` and `/mcp` responses (nginx does not inherit `add_header` into a location that sets its own) | medium | fixed |
| 2 | No password policy (fastapi-users accepts any password) | medium | fixed: 12 to 256 characters |
| 3 | No Content-Security-Policy on the web UI | medium | fixed in `svelte.config.js` (not checked in a browser, see below) |
| 4 | No `Permissions-Policy`, no cross-origin opener policy | low | fixed |
| 5 | SvelteKit advisories (open redirect via enhanced forms, XSS via cache-control in prerendered pages, form-data DoS) in 2.x; fix only in 3.x | high (see note) | open, issue #66 |
| 6 | No per-user rate limit on chat, uploads and transcription | medium | open, issue #67 |
| 7 | SECURITY DEFINER functions for invitations were not named in the architecture document | info | documented below |
| 8 | Registration reveals whether an e-mail address exists (`REGISTER_USER_ALREADY_EXISTS`) | low | accepted, rate limited |
| 9 | Swagger UI at `/api/docs` is public and loads its assets from a CDN | low | accepted, documented |
| 10 | Redis has no password and `config.py` carries development default secrets | low | accepted, documented |
| 11 | Dev tooling advisories (vitest, tinypool, @vitest/mocker) | low | open, in issue #66 |

Note on 5: `npm audit --omit=dev` reports nothing because SvelteKit is declared as a dev dependency, but its runtime is bundled into the production build, so the advisories apply to the frontend container. Exposure is limited: the app uses no prerendered pages and no form actions with `use:enhance` (it talks to the API through a typed fetch client), which are the affected features, and the Node server sits behind the gateway with a 100 MB body limit. The major upgrade was not done here because the task forbids unrequested major upgrades.

## Product boundaries

1. **Multi-user.** Every table with a `user_id` column except `sessions` has `ENABLE` and `FORCE ROW LEVEL SECURITY` and at least one policy. `tests/test_security_inventory.py` fails if a new `user_id` table lacks them, if a table without `user_id` is not on the reviewed list, or if the exemption list drifts. The application role is `NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE`, owns no object and cannot delete from append-only token, code, grant, audit or usage tables (also tested). Services filter by `user_id` in addition to the policy. Cross-user negative tests cover tasks, files, conversations, memos, personal tokens, OAuth grants and usage. Admin database functions reject a missing, member or inactive admin context. `invitations` retains forced RLS by `created_by`; cross-admin listing/revocation uses only the reviewed functions below.
2. **One provider key.** `OPENAI_API_KEY` is read from the environment only; models come from `backend/app/ai/models.toml`. The key is not part of any API response or log line (the log formatter also scrubs `sk-` shaped values). Only `backend` and `worker` join the `egress` network. Result: no finding.
3. **Private data stays private.** Logging was reworked: an allow-list of structured fields, route templates instead of URLs, exception type and stack locations without messages, secret scrubbing. Tests assert that prompts, search text, e-mail addresses, passwords, session cookies, provider messages and tokens do not appear. Backups are created with mode 600 and the runbook says to protect them. Result: no open finding.
4. **Agent actions are permission-bound.** Tools are typed and registered; writes default to ask-before-write and are audited in the same transaction. MCP writes are audited with the token id. No raw SQL or command execution path from model output exists (the only subprocess is ffmpeg with fixed arguments and a temp file path). Result: no finding.
5. **Modules independent.** Registry, API dependencies, worker guard and sidebar read the same enablement. Result: no finding.
6. **No private deployments in git.** Scripts and docs use placeholders and environment variables; the backup script writes to `./backups`, which is in `.gitignore` and `.dockerignore`.
7. **One service layer.** The new usage counters are written by services (`app/services/usage.py`) and read through a thin REST adapter. MCP counting happens in the protocol handler before dispatch.
8. **No claims beyond the code.** Documentation was updated in this step; known gaps are listed here and in the architecture document.

## SECURITY DEFINER inventory

Eleven functions, all in schema `public`, `SET search_path = public`, owned by the migration role, `EXECUTE` revoked from PUBLIC and granted to the application role only. The set is pinned by `test_security_definer_inventory_is_exactly_the_reviewed_set`; adding another fails the test until it is reviewed and listed here.

| Function | Purpose | Exposure |
| --- | --- | --- |
| `invitation_is_valid(p_token_hash text)` | Registration checks an invitation before any user exists | boolean only; input is a SHA-256 hash of a 256-bit token |
| `consume_invitation(p_token_hash text, p_user_id text)` | Marks the invitation used in the registration transaction | boolean only |
| `users_with_due_tasks(p_now timestamptz)` | Reminder worker finds users with due tasks without a user context | user ids only; the worker then continues in per-user contexts |
| `authenticate_api_token(p_token_hash text)` | Bearer authentication for `/mcp` before any user context exists | owner id, token id and scopes of a valid token of an active user; updates `last_used_at` at most once a minute |
| `authenticate_oauth_access(p_token_hash text, p_resource text)` | OAuth bearer authentication before any user context exists | returns the owner and scopes only for an active, unexpired, unrevoked token bound to the requested resource URI |
| `oauth_lookup_code(p_hash text)` | Authorization-code exchange before a user context exists | valid unexpired, unused code owner, client, redirect URI, scopes and PKCE challenge |
| `oauth_lookup_refresh(p_hash text)` | Refresh-token exchange before a user context exists | valid unexpired refresh-grant owner, client and scopes |
| `oauth_revoke_token(p_hash text)` | RFC 7009 revocation without a browser session | accepts only a hash, reveals no owner and writes the matching owner's audit row |
| `admin_list_invitations()` | Active admins share the outstanding invitation list | invitation id and expiry only; checks the active admin against transaction-local `app.user_id`; omits used and expired invitations |
| `admin_revoke_invitation(p_invitation_id text)` | Active admins revoke an outstanding invitation created by any admin | boolean only; checks the active admin against `app.user_id`; deletes only an unused invitation |
| `admin_list_audit_entries(p_before_created_at timestamptz, p_before_id text, p_row_limit integer)` | Admin instance audit viewer | paginated audit metadata only; checks the active admin against `app.user_id`; never returns `details` |

The admin functions are called only by the shared invitation/audit services in a transaction established with the authenticated admin's RLS context. Invitation rows continue to have `FORCE ROW LEVEL SECURITY` and the `created_by` policy; the functions do not broaden that policy or add direct cross-admin application-role table access. Audit rows retain their per-owner policy and append-only table grants. Audit instance reads expose ids, actor, action, target type/id and timestamp; arbitrary `details` JSON remains hidden. API tests cover a second admin listing and revoking another admin's invitation, while a member context gets no rows/cannot revoke; the RLS inventory also tests exact function grants and the app-role boundary.

`users` and `sessions` are not row-level-secured because authentication reads them before a user context exists; the application role can select, insert and update `users` and select, insert and delete `sessions`, nothing else. `module_settings`, `instance_settings` and `oauth_clients` hold instance-wide data; OAuth clients contain public registration metadata only.

## HTTP headers and transport

Verified against a running stack after the fix, on a page route and an API route:

| Header | Page | API |
| --- | --- | --- |
| `X-Content-Type-Options: nosniff` | yes | yes |
| `X-Frame-Options: DENY` | yes | yes |
| `Referrer-Policy: strict-origin-when-cross-origin` | yes | yes |
| `Permissions-Policy: camera=(), geolocation=(), microphone=(self)` | yes | yes |
| `Cross-Origin-Opener-Policy: same-origin` | yes | yes |
| `Content-Security-Policy` (default-src 'self', nonce-based script-src, `frame-ancestors 'none'`, `object-src 'none'`) | yes | n/a (JSON) |
| `Strict-Transport-Security` | no | no |

HSTS is intentionally left to the TLS terminator, because the gateway only sees plain HTTP (see the runbook). The CSP allows inline styles (components use style attributes) and `blob:` for audio recording and playback. It was verified by inspecting the response header; the UI itself could not be exercised in a browser in this environment, so a manual pass over login, chat, files and audio is part of the release checklist (issue #17 covers browser verification).

`X-Request-ID` is generated by the gateway, validated by the backend (8 to 64 characters of `[A-Za-z0-9_-]`, otherwise replaced) and returned on every response.

## Authentication, sessions, cookies

- Session cookie `fidus_session`: random opaque token, only its SHA-256 is stored, `HttpOnly`, `SameSite=Lax`, `Secure` when `COOKIE_SECURE=true`, 14-day lifetime, revocable server side, cleared on logout and sign-out-everywhere.
- CSRF cookie `fidus_csrf`: readable by design (double-submit), `SameSite=Lax`, same `Secure` switch; checked on unsafe methods together with the Origin check against `APP_URL`.
- `COOKIE_SECURE` defaults to false so that `./start.sh` works on `http://localhost`. Operators exposing the instance must set it (runbook, README). Finding 10 relates: nothing forces it.
- Passwords: hashed with Argon2 by fastapi-users; length 12 to 256 enforced (finding 2). No breached-password check.
- Bearer tokens: `fidus_pat_` secrets shown once, SHA-256 only in the database, scoped, expiring (default 90 days), revocable, only valid on `/mcp`; a token cannot mint tokens.

## Rate limits

| Surface | Limit | Notes |
| --- | --- | --- |
| Login, registration | `AUTH_RATE_LIMIT_ATTEMPTS` per window per client IP and per hashed account identifier | Redis fixed window, fails open when Redis is down (logged) |
| MCP | `MCP_RATE_LIMIT_REQUESTS` per token per window, failed tokens per client address | same behavior |
| Chat, uploads, transcription, search | none | finding 6, issue #67; usage counters now make consumption visible but do not limit it |

## Dependencies

- Backend: `pip-audit --require-hashes -r backend/requirements.lock` on 2026-11-23: no known vulnerabilities.
- Frontend: `npm audit` reports six advisories (SvelteKit 2.70.4, cookie, vitest, @vitest/mocker, tinypool, adapter-node). All need major upgrades (SvelteKit 3, adapter-node 6, vitest 5). No lockfile or dependency was changed in this step; tracked in issue #66.
- Images: `nginxinc/nginx-unprivileged`, `pgvector/pgvector:pg17`, `redis:7-alpine` are pinned by tag, not digest. Containers drop all capabilities, set `no-new-privileges`, and backend, frontend and gateway run as non-root; only the gateway publishes a port, `internal` has no outbound route.

## Accepted risks and notes

- 8: account enumeration through registration is inherent to open registration and is mitigated by the rate limit; with `invite-only` or `closed` it disappears.
- 9: `/api/docs` and `/api/v1/openapi.json` describe the API, which is public in the repository anyway. Operators who do not want it can block `/api/docs` in their reverse proxy.
- 10: Redis and PostgreSQL are reachable only on the `internal` network. `config.py` defaults (`change-me`) exist for tests and are overridden by Compose, which refuses to start without generated values (`${VAR:?...}`).
- Usage counters are written when a chat turn finishes or fails; a turn the client abandons mid-stream is not counted. Audio minutes are derived from the size of the constant-bitrate segments sent to the provider, so they are accurate to about a second per segment. Tokens are counted only when the provider reports them.
