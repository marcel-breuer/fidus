import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import { translate, type Locale } from '#lib/i18n/index.ts';
import Harness from './MemoriesHarness.test.svelte';

const html = (locale: Locale) => render(Harness, { props: { locale } }).body;

describe('memories page', () => {
	it('labels the write-mode radio group and its options', () => {
		const out = html('en');
		expect(out).toMatch(/role="radiogroup"[^>]*aria-labelledby="write-mode-label"|aria-labelledby="write-mode-label"[^>]*role="radiogroup"/);
		expect(out).toContain(translate('en', 'memory.writeModeTitle'));
		expect(out).toContain(translate('en', 'memory.writeModeAsk'));
		expect(out).toContain(translate('en', 'memory.writeModeAllow'));
	});

	it('associates the new-memory label with its textarea and keeps the add button disabled when empty', () => {
		const out = html('de');
		expect(out).toMatch(/<label[^>]*for="memory-new"/);
		expect(out).toContain('id="memory-new"');
		const add = out.match(/<button[^>]*>[\s\S]*?<\/button>/g)?.find((button) => button.includes(translate('de', 'memory.add')));
		expect(add).toContain('type="submit"');
		expect(add).toContain('disabled');
	});
});
