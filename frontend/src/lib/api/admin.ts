import { createApiClient } from './http';
import type { components } from './schema';

export type AdminModule = components['schemas']['AdminModuleOut'];
export type AdminInvitation = Pick<components['schemas']['InvitationOut'], 'id' | 'expires_at'>;
export type CreatedInvitation = AdminInvitation & { token: string };

const api = createApiClient(fetch, '');

function assertOk(response: Response): void {
	if (!response.ok) throw new Error(`Admin request failed: ${response.status}`);
}

export const getAdminModules = async (): Promise<AdminModule[]> => {
	const { data, response } = await api.GET('/api/v1/admin/modules');
	assertOk(response);
	return data as AdminModule[];
};

export const setModuleEnabled = async (key: string, enabled: boolean): Promise<AdminModule> => {
	const { data, response } = await api.PUT('/api/v1/admin/modules/{key}', {
		params: { path: { key } },
		body: { enabled }
	});
	assertOk(response);
	return data as AdminModule;
};

export const getInvitations = async (): Promise<AdminInvitation[]> => {
	const { data, response } = await api.GET('/api/v1/invitations');
	assertOk(response);
	return data as AdminInvitation[];
};

export const createInvitation = async (expiresInDays: number): Promise<CreatedInvitation> => {
	const { data, response } = await api.POST('/api/v1/invitations', {
		body: { expires_in_days: expiresInDays }
	});
	assertOk(response);
	return data as CreatedInvitation;
};

export const revokeInvitation = async (id: string): Promise<void> => {
	const { response } = await api.DELETE('/api/v1/invitations/{invitation_id}', {
		params: { path: { invitation_id: id } }
	});
	assertOk(response);
};

export function buildInviteLink(origin: string, token: string): string {
	return `${origin}/register?invite=${encodeURIComponent(token)}`;
}
