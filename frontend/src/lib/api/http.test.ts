import { describe, expect, it, vi } from 'vitest';
import { createApiClient } from './http';

function fakeFetch(response = new Response(null, { status: 204 })) {
	const requests: Request[] = [];
	const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
		requests.push(new Request(input, init));
		return response.clone();
	}) as typeof fetch;
	return { fetchImpl, requests };
}

describe('createApiClient', () => {
	it('adds CSRF only to unsafe methods', async () => {
		const { fetchImpl, requests } = fakeFetch();
		const api = createApiClient(fetchImpl, 'https://app.example', {
			cookieReader: () => 'fidus_csrf=csrf%20token'
		});

		await api.GET('/api/v1/health');
		await api.POST('/api/v1/auth/logout');
		await api.PUT('/api/v1/admin/modules/{key}', {
			params: { path: { key: 'chat' } },
			body: { enabled: true }
		});
		await api.DELETE('/api/v1/invitations/{invitation_id}', {
			params: { path: { invitation_id: 'invite-id' } }
		});
		const patch = api as unknown as {
			PATCH: (path: string) => Promise<unknown>;
		};
		await patch.PATCH('/api/v1/test');

		expect(requests.map((request) => request.headers.get('x-csrf-token'))).toEqual([
			null,
			'csrf token',
			'csrf token',
			'csrf token',
			'csrf token'
		]);
		expect(requests.map((request) => request.method)).toEqual([
			'GET',
			'POST',
			'PUT',
			'DELETE',
			'PATCH'
		]);
	});

	it('uses the server base URL and forwards the incoming cookie', async () => {
		const { fetchImpl, requests } = fakeFetch();
		const api = createApiClient(fetchImpl, 'http://backend:8000', {
			cookie: 'fidus_session=session-token'
		});

		await api.GET('/api/v1/users/me');

		expect(requests[0].url).toBe('http://backend:8000/api/v1/users/me');
		expect(requests[0].headers.get('cookie')).toBe('fidus_session=session-token');
		expect(requests[0].headers.has('x-csrf-token')).toBe(false);
	});

	it('preserves a typed API error body', async () => {
		const { fetchImpl } = fakeFetch(
			new Response(JSON.stringify({ detail: 'invalid request' }), {
				status: 422,
				headers: { 'content-type': 'application/json' }
			})
		);
		const api = createApiClient(fetchImpl, 'http://api.test');

		const result = await api.PUT('/api/v1/admin/modules/{key}', {
			params: { path: { key: 'chat' } },
			body: { enabled: true }
		});

		expect(result.error).toEqual({ detail: 'invalid request' });
		expect(result.response.status).toBe(422);
	});
});
