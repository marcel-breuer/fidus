import createClient from 'openapi-fetch';
import type { paths } from './schema';
import { csrfHeaders } from './csrf';

export type ApiClientOptions = {
	/** Cookie header to forward from a server-side request. */
	cookie?: string | null;
	/** Override the browser cookie source, primarily for tests. */
	cookieReader?: () => string;
};

export function createApiClient(
	fetchImpl: typeof fetch,
	baseUrl: string,
	options: ApiClientOptions = {}
) {
	const readCookie =
		options.cookieReader ?? (typeof document === 'undefined' ? undefined : () => document.cookie);

	const client = createClient<paths>({ baseUrl, fetch: fetchImpl });
	client.use({
		onRequest({ request }) {
			if (options.cookie) request.headers.set('cookie', options.cookie);

			if (
				readCookie &&
				['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method.toUpperCase())
			) {
				for (const [name, value] of Object.entries(csrfHeaders(readCookie()))) {
					request.headers.set(name, value);
				}
			}

			return request;
		}
	});

	return client;
}
