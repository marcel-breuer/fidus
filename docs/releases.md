# Releases

Fidus is pre-1.0. Use `v0.MINOR.PATCH` Git tags and matching GitHub Releases. Before 1.0.0, MINOR increments for new features and breaking changes, PATCH for compatible fixes. Do not reuse a version.

## Automated releases
1. Use Conventional Commit PR titles and commit subjects. `feat` and breaking changes bump MINOR, `fix` bumps PATCH; docs, chore, CI and test-only changes do not trigger a release.
2. After a push to `main`, the Release Please workflow opens or updates one release PR with the version manifest, `version.txt` and a dated changelog section.
3. Merging the release PR creates the `vMAJOR.MINOR.PATCH` tag and the GitHub Release.

## GitHub Actions setup
Add a repository-scoped fine-grained token as the Actions secret `RELEASE_PLEASE_TOKEN_FIDUS` with **Contents: read and write** and **Pull requests: read and write**. The built-in `GITHUB_TOKEN` cannot be used because GitHub does not start follow-up workflows for events it creates. The workflow fails with a direct error when the secret is missing.

## Upgrade and rollback
Back up the PostgreSQL database and the file storage volume before an upgrade. To roll back, restore the previous version in `.env`, run `docker compose pull && docker compose up -d --wait`, and restore the matching backups if a migration was not backward-compatible. Never run `docker compose down --volumes` during an upgrade or rollback; it deletes persistent data.
