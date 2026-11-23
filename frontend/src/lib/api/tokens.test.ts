import { describe, expect, it } from 'vitest';
import { isExpired, mcpEndpoint, TOKEN_SCOPES } from './tokens';
import { messages } from '$lib/i18n';

describe('token helpers', () => {
	it('treats a token as expired once its expiry time has passed', () => {
		const now = new Date('2026-01-10T12:00:00Z');
		expect(isExpired({ expires_at: '2026-01-10T11:59:59Z' }, now)).toBe(true);
		expect(isExpired({ expires_at: '2026-01-10T12:00:00Z' }, now)).toBe(true);
		expect(isExpired({ expires_at: '2026-01-10T12:00:01Z' }, now)).toBe(false);
	});

	it('builds the MCP endpoint from the page origin', () => {
		expect(mcpEndpoint('https://fidus.example')).toBe('https://fidus.example/mcp');
	});

	it('has a label in both languages for every selectable scope', () => {
		for (const scope of TOKEN_SCOPES) {
			expect(messages.en[`tokens.scope.${scope}`]).toBeTruthy();
			expect(messages.de[`tokens.scope.${scope}`]).toBeTruthy();
		}
	});
});
