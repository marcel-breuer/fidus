import { describe, expect, it } from 'vitest';
import { detectLocale, messages, translate } from './index';

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe('i18n catalogs', () => {
	it('has identical keys in German and English', () => {
		expect(Object.keys(messages.de).sort()).toEqual(Object.keys(messages.en).sort());
	});

	it('keeps interpolation placeholders identical in both languages', () => {
		for (const key of Object.keys(messages.en) as (keyof typeof messages.en)[]) {
			expect(placeholders(messages.de[key]), key).toEqual(placeholders(messages.en[key]));
		}
	});

	it('has no empty entries', () => {
		for (const locale of ['en', 'de'] as const) {
			for (const [key, value] of Object.entries(messages[locale])) {
				expect(value.trim(), `${locale}:${key}`).not.toBe('');
			}
		}
	});

	it('interpolates parameters and leaves unknown placeholders intact', () => {
		expect(translate('en', 'nav.signedInAs', { email: 'a@b.c' })).toBe('Signed in as a@b.c');
		expect(translate('de', 'nav.signedInAs')).toBe('Angemeldet als {email}');
	});
});

describe('detectLocale', () => {
	it('prefers the cookie', () => expect(detectLocale('de', 'en-US')).toBe('de'));
	it('reads the first supported Accept-Language entry', () =>
		expect(detectLocale(undefined, 'fr-FR,de;q=0.8,en;q=0.5')).toBe('de'));
	it('falls back to English', () => expect(detectLocale('xx', 'fr')).toBe('en'));
});
