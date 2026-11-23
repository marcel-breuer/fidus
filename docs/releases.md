# Releases

Fidus uses Semantic Versioning with `vMAJOR.MINOR.PATCH` Git tags and matching GitHub Releases: MAJOR for breaking changes, MINOR for new features, PATCH for compatible fixes. Do not reuse a version. Release Please currently runs with `bump-minor-pre-major`; check `release-please-config.json` before publishing the first stable release.

## Automated releases
1. Use Conventional Commit PR titles and commit subjects. `feat` and breaking changes bump MINOR, `fix` bumps PATCH; docs, chore, CI and test-only changes do not trigger a release.
2. After a push to `main`, the Release Please workflow opens or updates one release PR with the version manifest, `version.txt` and a dated changelog section.
3. Merging the release PR creates the `vMAJOR.MINOR.PATCH` tag and the GitHub Release.

## GitHub Actions setup
Add a repository-scoped fine-grained token as the Actions secret `RELEASE_PLEASE_TOKEN_FIDUS` with **Contents: read and write** and **Pull requests: read and write**. The built-in `GITHUB_TOKEN` cannot be used because GitHub does not start follow-up workflows for events it creates. The workflow fails with a direct error when the secret is missing.

## Upgrade and rollback
Back up with `scripts/backup.sh` before an upgrade, upgrade with `./start.sh` on the new version and roll back by checking out the previous tag and restoring the backup with `scripts/restore.sh --force`. The steps, including secret rotation and troubleshooting, are in [runbook.md](runbook.md). Never run `docker compose down --volumes` during an upgrade or rollback; it deletes persistent data.
