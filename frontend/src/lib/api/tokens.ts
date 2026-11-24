import { createApiClient } from './http';
import { csrfHeaders } from './csrf';
import type { components } from './schema';

export type ApiToken = components['schemas']['TokenOut'];
export type CreatedToken = components['schemas']['TokenCreated'];
export type TokenScope = ApiToken['scopes'][number];
export type OAuthGrant = {
	id: string;
	client_name: string;
	resource: string;
	scopes: TokenScope[];
	created_at: string;
	expires_at: string;
	last_used_at: string | null;
};

export const TOKEN_SCOPES: readonly TokenScope[] = [
	'tasks:read',
	'tasks:write',
	'files:read',
	'files:write',
	'chat:use',
	'audio:read',
	'audio:write'
];
export const DEFAULT_EXPIRY_DAYS = 90;
export const MAX_EXPIRY_DAYS = 365;

/** Thrown when the user already holds the maximum number of active tokens. */
export class TokenLimitError extends Error {}

const api = createApiClient(fetch, '');

export const getTokens = async (): Promise<ApiToken[]> => {
	const { data, response } = await api.GET('/api/v1/tokens');
	if (!response.ok) throw new Error(`Token request failed: ${response.status}`);
	return data as ApiToken[];
};

export const createToken = async (
	name: string,
	scopes: TokenScope[],
	expiresInDays: number
): Promise<CreatedToken> => {
	const { data, response } = await api.POST('/api/v1/tokens', {
		body: { name, scopes, expires_in_days: expiresInDays }
	});
	if (response.status === 409) throw new TokenLimitError();
	if (!response.ok) throw new Error(`Token request failed: ${response.status}`);
	return data as CreatedToken;
};

export const revokeToken = async (id: string): Promise<void> => {
	const { response } = await api.DELETE('/api/v1/tokens/{token_id}', {
		params: { path: { token_id: id } }
	});
	if (!response.ok) throw new Error(`Token request failed: ${response.status}`);
};

export const getOAuthGrants = async (): Promise<OAuthGrant[]> => {
	const response = await fetch('/api/v1/oauth/grants');
	if (!response.ok) throw new Error(`OAuth grant request failed: ${response.status}`);
	return (await response.json()) as OAuthGrant[];
};

export const revokeOAuthGrant = async (id: string): Promise<void> => {
	const response = await fetch(`/api/v1/oauth/grants/${encodeURIComponent(id)}`, {
		method: 'DELETE',
		headers: csrfHeaders()
	});
	if (!response.ok) throw new Error(`OAuth grant request failed: ${response.status}`);
};

export const isExpired = (token: Pick<ApiToken, 'expires_at'>, now: Date = new Date()): boolean =>
	new Date(token.expires_at).getTime() <= now.getTime();

export const mcpEndpoint = (origin: string): string => `${origin}/mcp`;
