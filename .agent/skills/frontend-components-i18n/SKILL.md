# Skill: Frontend Components and i18n

**Purpose:** Consistent, reusable, accessible, fully localized SvelteKit UI. **Use when:** any frontend change.

**Components:**
1. Inspect `frontend/src/lib/ui` and nearby feature components before adding markup; reuse the closest fit.
2. Create a typed, accessible component only when a reusable pattern has no fit. Cross-feature primitives go in `lib/ui`; domain behavior stays with its feature.
3. Preserve native semantics, keyboard behavior, labels, focus handling and responsive layout.
4. Provide loading, empty, validation and error states.

**Localization:**
1. Every visible or assistive string is localizable: headings, labels, placeholders, buttons, errors, empty states, tooltips, accessible names.
2. Use the shared `t` helper; no hard-coded copy. Add German and English entries together and keep interpolation values intact.
3. Use locale-aware date, number and time formatters.

**Validation:** Type check, unit tests, build; check both languages render.
