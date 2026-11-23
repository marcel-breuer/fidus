import { describe, expect, it } from 'vitest';
import { csrfHeaders, readCsrfToken } from './csrf';

describe('readCsrfToken', () => {
	it('reads the token among other cookies and decodes its value', () => {
		expect(readCsrfToken('theme=dark; fidus_csrf=abc%2B123; session=x')).toBe('abc+123');
	});

	it('returns null when the CSRF cookie is missing', () => {
		expect(readCsrfToken('theme=dark; fidus_session=secret')).toBeNull();
	});

	it('does not match cookies with a similar name', () => {
		expect(readCsrfToken('not_fidus_csrf=wrong')).toBeNull();
	});

	it('builds the request header for a write', () => {
		expect(csrfHeaders('fidus_csrf=token')).toEqual({ 'X-CSRF-Token': 'token' });
	});
});
