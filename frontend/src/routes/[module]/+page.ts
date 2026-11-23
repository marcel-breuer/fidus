import { error } from '@sveltejs/kit';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, parent }) => {
	const { modules } = await parent();
	const entry = modules.find((m) => m.route === `/${params.module}`);
	if (!entry) error(404, 'Not found');
	return { entry };
};
