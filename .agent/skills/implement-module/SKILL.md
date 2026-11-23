# Skill: Implement Module

**Purpose:** Build a self-contained module that plugs into the registry. **Use when:** adding or changing a module (chat, files, tasks, calendar).

**Procedure:**
1. Define module key, sidebar entry, routes, schema and optional dependencies; register it in the backend module registry.
2. Implement typed services, validation, user-scoped persistence and API routes; keep handlers thin.
3. Add the accessible, localized SvelteKit screens; the sidebar is generated from the registry.
4. Expose agent capabilities only as typed, registered tools with user attribution.
5. Add authorized, denied and cross-user regression tests plus persistence tests.
6. Update `docs/SPEC.md` for the module surface.

**Constraints:** A module must not depend unconditionally on another module.

**Completion:** The module works for its owner and is inaccessible to everyone else.
