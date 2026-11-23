import { describe, expect, it } from 'vitest';
import { buildInviteLink } from './admin';

describe('buildInviteLink', () => {
	it('creates a registration link containing the one-time token', () => {
		expect(buildInviteLink('https://fidus.example', 'token+value')).toBe(
			'https://fidus.example/register?invite=token%2Bvalue'
		);
	});
});
