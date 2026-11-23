import { csrfHeaders } from './csrf';

export type AdminModule = { key: string; name_key: string; enabled: boolean };
export type AdminInvitation = { id: string; expires_at: string };
export type CreatedInvitation = AdminInvitation & { token: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	const response = await fetch(path, init);
	if (!response.ok) throw new Error(`Admin request failed: ${response.status}`);
	if (response.status === 204) return undefined as T;
	return (await response.json()) as T;
}

export const getAdminModules = () => request<AdminModule[]>('/api/v1/admin/modules');

export const setModuleEnabled = (key: string, enabled: boolean) =>
	request<AdminModule>(`/api/v1/admin/modules/${encodeURIComponent(key)}`, {
		method: 'PUT',
		headers: { ...csrfHeaders(), 'content-type': 'application/json' },
		body: JSON.stringify({ enabled })
	});

export const getInvitations = () => request<AdminInvitation[]>('/api/v1/invitations');

export const createInvitation = (expiresInDays: number) =>
	request<CreatedInvitation>('/api/v1/invitations', {
		method: 'POST',
		headers: { ...csrfHeaders(), 'content-type': 'application/json' },
		body: JSON.stringify({ expires_in_days: expiresInDays })
	});

export const revokeInvitation = (id: string) =>
	request<void>(`/api/v1/invitations/${encodeURIComponent(id)}`, {
		method: 'DELETE',
		headers: csrfHeaders()
	});

export function buildInviteLink(origin: string, token: string): string {
	return `${origin}/register?invite=${encodeURIComponent(token)}`;
}
