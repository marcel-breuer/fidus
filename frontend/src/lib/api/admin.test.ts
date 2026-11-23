import { describe, expect, it } from 'vitest';
import { AdminError, buildInviteLink, userChangeErrorKey } from './admin';

describe('buildInviteLink', () => {
	it('creates a registration link containing the one-time token', () => {
		expect(buildInviteLink('https://fidus.example', 'token+value')).toBe(
			'https://fidus.example/register?invite=token%2Bvalue'
		);
	});
});

describe('userChangeErrorKey', () => {
	it('explains self-lockout and last-admin refusals', () => {
		expect(userChangeErrorKey(new AdminError(409, 'CANNOT_MODIFY_SELF'))).toBe('admin.users.error.self');
		expect(userChangeErrorKey(new AdminError(409, 'LAST_ADMIN_REQUIRED'))).toBe(
			'admin.users.error.lastAdmin'
		);
	});

	it('falls back to the generic error for anything else', () => {
		expect(userChangeErrorKey(new AdminError(500, null))).toBe('common.error');
		expect(userChangeErrorKey(new Error('network'))).toBe('common.error');
	});
});
