import { createApiClient } from './http';
import type { components } from './schema';

export type AuthError = 'credentials' | 'exists' | 'closed' | 'invalid' | 'rateLimited' | 'unknown';

const api = createApiClient(fetch, '');

function detail(payload: unknown): unknown {
	return typeof payload === 'object' && payload !== null && 'detail' in payload
		? payload.detail
		: undefined;
}

export async function login(email: string, password: string): Promise<AuthError | null> {
	const { response } = await api.POST('/api/v1/auth/login', {
		parseAs: 'text',
		body: { username: email, password, scope: '' },
		headers: { 'content-type': 'application/x-www-form-urlencoded' },
		bodySerializer: (body) =>
			new URLSearchParams({
				username: body.username,
				password: body.password,
				scope: body.scope
			}).toString()
	});
	if (response.ok) return null;
	if (response.status === 429) return 'rateLimited';
	return response.status === 400 ? 'credentials' : 'unknown';
}

export async function register(
	email: string,
	password: string,
	invitationToken?: string
): Promise<AuthError | null> {
	const { error, response } = await api.POST('/api/v1/auth/register', {
		// The schema lists the defaulted flags (is_active, ...) as required; the server ignores them for
		// registrations, so the client only sends what the form collects.
		body: {
			email,
			password,
			...(invitationToken ? { invitation_token: invitationToken } : {})
		} as components['schemas']['UserCreate']
	});
	if (response.ok) return null;
	if (response.status === 429) return 'rateLimited';
	const reason = detail(error);
	if (reason === 'REGISTER_USER_ALREADY_EXISTS') return 'exists';
	if (reason === 'REGISTRATION_CLOSED') return 'closed';
	if (response.status === 400 || response.status === 422) return 'invalid';
	return 'unknown';
}

export async function logout(): Promise<void> {
	await api.POST('/api/v1/auth/logout', { parseAs: 'text' });
}

export async function logoutAll(): Promise<void> {
	await api.POST('/api/v1/auth/logout-all', { parseAs: 'text' });
}
