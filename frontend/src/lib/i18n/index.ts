import { de } from './de';
import { en, type MessageKey } from './en';

export const LOCALES = ['en', 'de'] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = 'en';
export const LOCALE_COOKIE = 'locale';

export type { MessageKey };
export const messages: Record<Locale, Record<MessageKey, string>> = { en, de };

export function isLocale(value: unknown): value is Locale {
	return typeof value === 'string' && (LOCALES as readonly string[]).includes(value);
}

/** Cookie wins; otherwise the first supported language in Accept-Language. */
export function detectLocale(cookie: string | undefined, acceptLanguage: string | null): Locale {
	if (isLocale(cookie)) return cookie;
	for (const part of (acceptLanguage ?? '').split(',')) {
		const tag = part.split(';')[0].trim().toLowerCase().split('-')[0];
		if (isLocale(tag)) return tag;
	}
	return DEFAULT_LOCALE;
}

export type Params = Record<string, string | number>;

export function translate(locale: Locale, key: MessageKey, params: Params = {}): string {
	return messages[locale][key].replace(/\{(\w+)\}/g, (match, name: string) =>
		name in params ? String(params[name]) : match
	);
}

export function formatDate(locale: Locale, date: Date): string {
	return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}
