import { redirect } from '@sveltejs/kit';
import { loadModules, loadUser } from '#lib/api/server.ts';
import type { LayoutServerLoad } from './$types';

const PUBLIC_PATHS = ['/login', '/register'];

export const load: LayoutServerLoad = async ({ fetch, request, locals, url }) => {
	const cookie = request.headers.get('cookie');
	const user = await loadUser(fetch, cookie);
	const isPublic = PUBLIC_PATHS.includes(url.pathname);

	if (!user) {
		if (!isPublic) redirect(303, '/login');
		return { locale: locals.locale, user: null, modules: [] };
	}
	if (isPublic) redirect(303, '/');
	return { locale: locals.locale, user, modules: (await loadModules(fetch, cookie)) ?? [] };
};
