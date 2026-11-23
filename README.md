# Fidus

Open-source, self-hostable personal assistant: a chat interface with a growing set of modules (chat, files, tasks, later calendar). Multi-user, FastAPI + SvelteKit + PostgreSQL/pgvector, powered by a single OpenAI API key.

Status: early development. See [docs/SPEC.md](docs/SPEC.md) for scope and decisions; the specified features are not all implemented yet.

## Quick start
```sh
git clone https://github.com/marcel-breuer/fidus
cd fidus
./start.sh
```
`start.sh` checks Docker, creates `.env` with fresh secrets, builds and starts the stack. Set `OPENAI_API_KEY` in `.env` to use the assistant.

## Documentation
- [Specification](docs/SPEC.md)
- [Contributing](CONTRIBUTING.md)
- [Repository rules](AGENTS.md)
- [Releases](docs/releases.md)

## License
[MIT](LICENSE)
