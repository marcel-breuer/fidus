import { env } from '$env/dynamic/private';
import type { ModuleEntry, User } from './types';

type Fetch = typeof fetch;

async function backendGet<T>(fetchFn: Fetch, cookie: string | null, path: string): Promise<T | null> {
	const base = env.BACKEND_URL ?? 'http://localhost:8000';
	const response = await fetchFn(`${base}${path}`, { headers: cookie ? { cookie } : {} });
	if (response.status === 401) return null;
	if (!response.ok) throw new Error(`Backend ${path} responded ${response.status}`);
	return (await response.json()) as T;
}

export const loadUser = (f: Fetch, cookie: string | null) => backendGet<User>(f, cookie, '/api/v1/users/me');
export const loadModules = (f: Fetch, cookie: string | null) =>
	backendGet<ModuleEntry[]>(f, cookie, '/api/v1/modules');
