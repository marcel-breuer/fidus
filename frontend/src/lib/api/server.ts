import { env } from '$env/dynamic/private';
import { createApiClient } from './http';
import type { ModuleEntry, User } from './types';

type Fetch = typeof fetch;

function createServerClient(fetchFn: Fetch, cookie: string | null) {
	return createApiClient(fetchFn, env.BACKEND_URL ?? 'http://localhost:8000', { cookie });
}

export async function loadUser(f: Fetch, cookie: string | null): Promise<User | null> {
	const { data, response } = await createServerClient(f, cookie).GET('/api/v1/users/me');
	if (response.status === 401) return null;
	if (!response.ok) throw new Error(`Backend /api/v1/users/me responded ${response.status}`);
	return data ?? null;
}

export async function loadModules(f: Fetch, cookie: string | null): Promise<ModuleEntry[] | null> {
	const { data, response } = await createServerClient(f, cookie).GET('/api/v1/modules');
	if (response.status === 401) return null;
	if (!response.ok) throw new Error(`Backend /api/v1/modules responded ${response.status}`);
	return data ?? null;
}
