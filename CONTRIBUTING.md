# Contributing to Fidus

Fidus is MIT-licensed. Contributions to code, documentation, tests and accessibility are welcome.

## Before you begin
- Read [README.md](README.md), [AGENTS.md](AGENTS.md) and [docs/SPEC.md](docs/SPEC.md).
- Search existing issues; open an issue before implementing larger features or changing module contracts.
- Never include credentials, private instance details or personal data in commits, screenshots, issues or PRs.

## Workflow
1. Branch from `main`: `feat/issue-N-description`, `fix/issue-N-description`, `test/issue-N-description` or `docs/issue-N-description`.
2. Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) for commits and PR titles.
3. Open one focused PR per issue, describing behavior, implementation, tests and risk.
4. Merge only with green required checks and no bypass of branch protection.
5. Update docs and tests together with behavior changes.

## Local start
```sh
./start.sh
```
The script checks Docker, creates `.env` with fresh secrets, builds and starts the stack. Set `OPENAI_API_KEY` in `.env` to use the assistant.

## Validation
Run the pipeline steps locally before opening a PR:
```sh
docker compose --env-file .env.example config --quiet
docker compose exec backend pytest
docker compose run --rm frontend-dev npm test
docker compose run --rm frontend-dev npm run check
docker compose run --rm frontend-dev npm run build
./scripts/api-client.sh check
```

## License
By submitting a contribution you agree it may be distributed under the [MIT License](LICENSE).
