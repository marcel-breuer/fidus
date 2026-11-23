# Skill: Release and Dependencies

**Purpose:** Reproducible versioned releases and dependency maintenance. **Use when:** editing Dependabot, release automation, changelog, image publishing or tags.

**Procedure:**
1. Apply Semantic Versioning with the pre-1.0 policy: `feat` and breaking changes bump MINOR, `fix` bumps PATCH.
2. Keep release-please config, manifest and `version.txt` consistent; changelog comes from Conventional Commits.
3. Review dependency updates weekly; keep updates grouped and reviewed manually.
4. Gate publishing on green required checks; document migration and rollback.

**Constraints:** Never auto-merge unreviewed dependency changes; never publish real releases or tags while testing the workflow.
