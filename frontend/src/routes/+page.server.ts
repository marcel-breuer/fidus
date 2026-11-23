import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ parent }) => {
	const { modules } = await parent();
	redirect(303, modules[0]?.route ?? '/chat');
};
