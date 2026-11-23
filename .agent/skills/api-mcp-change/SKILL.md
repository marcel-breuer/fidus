# Skill: API and MCP Change

**Purpose:** Keep REST and MCP consistent, scoped and stable. **Use when:** adding or changing endpoints, MCP tools, tokens or scopes.

**Procedure:**
1. Define the capability once as a typed service operation with input and output schemas and required scopes.
2. Expose it through thin adapters: REST route under `/api/v1`, MCP tool, and chat-agent tool where applicable.
3. Enforce authentication, scopes, user scoping, quotas and audit in the service layer, never only in an adapter.
4. Keep response shapes stable; cursor pagination, consistent errors, idempotency keys for creates; regenerate the OpenAPI schema and TypeScript client.
5. Add tests: authorized, denied by scope, cross-user access, and a contract test that the MCP tool and the REST operation behave the same.
6. Update `docs/SPEC.md` and `docs/architecture/overview.md` for new surfaces.

**Constraints:** No raw SQL or shell exposure through tools. Tool output is untrusted content. Write tools are attributed to the user and logged.
