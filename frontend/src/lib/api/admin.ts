import { createApiClient } from './http';
import type { components } from './schema';

export type AdminModule = components['schemas']['AdminModuleOut'];
export type AdminInvitation = Pick<components['schemas']['InvitationOut'], 'id' | 'expires_at'>;
export type CreatedInvitation = AdminInvitation & { token: string };

export type AdminUser = components['schemas']['AdminUserOut'];
export type AdminUserChange = components['schemas']['AdminUserUpdate'];
export type RegistrationSetting = components['schemas']['RegistrationOut'];
export type RegistrationMode = RegistrationSetting['mode'];
export const REGISTRATION_MODES: RegistrationMode[] = ['open', 'invite-only', 'closed'];

const api = createApiClient(fetch, '');

/** Carries the backend's machine-readable `detail` code so screens can explain the refusal. */
export class AdminError extends Error {
	constructor(
		readonly status: number,
		readonly code: string | null
	) {
		super(`Admin request failed: ${status}`);
	}
}

function assertOk(response: Response, error?: unknown): void {
	if (response.ok) return;
	const detail = (error as { detail?: unknown } | undefined)?.detail;
	throw new AdminError(response.status, typeof detail === 'string' ? detail : null);
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

export const getAdminUsers = async (): Promise<AdminUser[]> => {
	const { data, response, error } = await api.GET('/api/v1/admin/users');
	assertOk(response, error);
	return data as AdminUser[];
};

export const updateAdminUser = async (id: string, change: AdminUserChange): Promise<AdminUser> => {
	const { data, response, error } = await api.PATCH('/api/v1/admin/users/{user_id}', {
		params: { path: { user_id: id } },
		body: change
	});
	assertOk(response, error);
	return data as AdminUser;
};

export const getRegistration = async (): Promise<RegistrationSetting> => {
	const { data, response, error } = await api.GET('/api/v1/admin/registration');
	assertOk(response, error);
	return data as RegistrationSetting;
};

export const setRegistrationMode = async (mode: RegistrationMode): Promise<RegistrationSetting> => {
	const { data, response, error } = await api.PUT('/api/v1/admin/registration', { body: { mode } });
	assertOk(response, error);
	return data as RegistrationSetting;
};

/** Message key explaining a refused user change; anything unexpected falls back to the generic error. */
export function userChangeErrorKey(
	error: unknown
): 'admin.users.error.self' | 'admin.users.error.lastAdmin' | 'common.error' {
	if (error instanceof AdminError) {
		if (error.code === 'CANNOT_MODIFY_SELF') return 'admin.users.error.self';
		if (error.code === 'LAST_ADMIN_REQUIRED') return 'admin.users.error.lastAdmin';
	}
	return 'common.error';
}

export function buildInviteLink(origin: string, token: string): string {
	return `${origin}/register?invite=${encodeURIComponent(token)}`;
}
