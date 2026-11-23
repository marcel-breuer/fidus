export type AuthError = 'credentials' | 'exists' | 'closed' | 'invalid' | 'unknown';

async function detail(response: Response): Promise<unknown> {
	try {
		return ((await response.json()) as { detail?: unknown }).detail;
	} catch {
		return undefined;
	}
}

export async function login(email: string, password: string): Promise<AuthError | null> {
	const response = await fetch('/api/v1/auth/login', {
		method: 'POST',
		body: new URLSearchParams({ username: email, password })
	});
	if (response.ok) return null;
	return response.status === 400 ? 'credentials' : 'unknown';
}

export async function register(email: string, password: string): Promise<AuthError | null> {
	const response = await fetch('/api/v1/auth/register', {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ email, password })
	});
	if (response.ok) return null;
	const reason = await detail(response);
	if (reason === 'REGISTER_USER_ALREADY_EXISTS') return 'exists';
	if (reason === 'REGISTRATION_CLOSED') return 'closed';
	if (response.status === 400 || response.status === 422) return 'invalid';
	return 'unknown';
}

export async function logout(): Promise<void> {
	await fetch('/api/v1/auth/logout', { method: 'POST' });
}
