import type { Handle } from '@sveltejs/kit';
import { LOCALE_COOKIE, detectLocale } from '$lib/i18n';

export const handle: Handle = async ({ event, resolve }) => {
	const locale = detectLocale(
		event.cookies.get(LOCALE_COOKIE),
		event.request.headers.get('accept-language')
	);
	event.locals.locale = locale;
	return resolve(event, { transformPageChunk: ({ html }) => html.replace('%lang%', locale) });
};
