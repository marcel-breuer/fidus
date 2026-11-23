# Skill: Database Change

**Purpose:** Safe schema evolution. **Use when:** models, migrations, indexes or vector columns change.

**Procedure:**
1. Add a new Alembic migration; never edit a migration that was already shared or executed.
2. Every user-owned table has `user_id` with an index and a foreign key, `ENABLE` and `FORCE ROW LEVEL SECURITY` and a policy on `current_setting('app.user_id')`; add constraints and defaults deliberately. Migrations run with the owner role, the application role has no `BYPASSRLS`.
3. Vector columns and indexes use pgvector; enable the extension in a migration; fix the embedding dimension in config and document changing it.
4. Make migrations transaction-safe and compatible with backup and upgrade.
5. Update models, schemas and tests together; run migrations only inside the `backend` container.

**Validation:** `alembic upgrade head` on an empty database, downgrade where supported, full test suite.
