# Fidus – Specification

Fidus is an open-source (MIT), self-hostable personal assistant: a chat interface with a growing set of modules.

## Decisions

| Topic | Decision |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy (async), Alembic |
| Frontend | SvelteKit (TypeScript) |
| Database | PostgreSQL with pgvector (relational data and embeddings), row-level security for user separation |
| Queue and cache | Redis |
| Gateway | Nginx, single published port |
| Frontend serving | SvelteKit Node server in its own container |
| Auth | fastapi-users, multi-user from the start, `user_id` on every user-owned table |
| Models | OpenAI only, one `OPENAI_API_KEY`; chat, transcription, embeddings, TTS and web search models are fixed in a config file, not chosen at runtime |
| i18n | UI in German and English from the start; code, docs and repo in English |
| License | MIT |
| Deployment | Docker Compose only (gateway, frontend, backend, worker, scheduler, db, redis); local via `./start.sh` or on an own server or web hosting behind TLS |
| Registration | Open by default after the first admin; invite-only uses admin-created, single-use invitations managed in the admin screen and API; closed rejects further registrations |
| Usage | Tokens, audio minutes and storage are recorded and displayed per user; no quota enforcement in the MVP |
| Clients | Web UI first; native apps (macOS, iOS, iPadOS, Windows) later as API clients |
| Integrations | Versioned REST API (`/api/v1`) and an MCP server (`/mcp`) over the same service layer |
| Architecture | See [architecture/overview.md](architecture/overview.md) |
| Reminders | In-app only (no e-mail, no push) |

## Implementation status
Implemented: Docker Compose stack, authentication with registration modes and sign-out-everywhere, scheduled expired-session cleanup, module registry and sidebar, row-level security, worker with scheduled jobs, German and English UI shell, the Tasks module with in-app reminders, chat Stages 1–2 (`Refs #18`: model configuration, provider interface, conversations/messages persistence, REST routes, SSE chat completion, and chat UI), and Files Stage 1 (`Refs #19`: private storage, folders, streamed uploads, versioning, downloads and browser UI). Conversation memory and durable memories, web search, citations, attachments and agent tools remain unimplemented. Files text extraction, embeddings and search are not implemented yet. Streaming/chat completion, memory, web search, attachments, agent tools and chat UI remain unimplemented, as do audio, tokens and MCP; see [architecture/overview.md](architecture/overview.md) section 0 for details and known gaps.

## MVP scope

### Chat module
- Multiple conversations (sidebar list, rename, delete)
- Streaming responses with Markdown and code rendering
- Source references (documents and web links)
- File attachments on messages (PDF, text, images)
- Knowledge: RAG over uploaded files and notes, conversation history as memory, web search

### Audio
- Browser recording (microphone button), transcript is inserted as a message
- Audio upload as memo: transcribe, store transcript as a searchable document
- Long files: chunking and asynchronous processing (transcription API limit: 25 MB per file)
- Text-to-speech for responses

### Files module
- Folder and file browser, files created by the user or by the agent
- Content feeds the RAG index

Stage 1 (`Refs #19`) implements the user-facing file tree, local volume storage, streamed uploads, versions and attachment downloads. Stage 2 will add text extraction, embeddings and search; none of those are implemented yet.

### Tasks module
- Implemented: user-scoped tasks with notes, due date, reminder time, completion/reopen, soft deletion and open/done/all filtering.
- Implemented: persistent in-app reminders surfaced in the localized UI and dismissible by the user.
- No e-mail or push reminders.

### API and MCP
- Every capability is a typed service operation exposed through REST, the chat agent and MCP
- Personal access tokens with scopes for integrations; OAuth for native apps later

### Module system
- Backend module registry and sidebar entries are generated from enabled entries; admins manage instance-wide module enablement from `/admin`
- Disabled modules are hidden and can be blocked at their API and worker entry points; module data remains stored
- Later modules (e.g. calendar) plug in without changing the core

### Administration
- Admins create, list and revoke invitations and set their expiry from `/admin`; invitation tokens are shown once with a registration link
- Admins can enable or disable registered modules for the instance

## Out of scope for the MVP
- Multiple LLM providers, per-user model selection
- Native apps and offline synchronization (the API prepares a change feed)
- E-mail or push reminders
- Calendar integration

## Open points
- Exact model IDs: verify against current OpenAI documentation when implementing
- Usage limits per user for a hosted service (token and audio-minute budgets)
