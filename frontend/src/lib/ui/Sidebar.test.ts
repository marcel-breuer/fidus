import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import type { ModuleEntry } from '$lib/api/types';
import { translate, type Locale } from '$lib/i18n';
import Harness from './SidebarHarness.test.svelte';

const modules: ModuleEntry[] = [
	{ key: 'chat', name_key: 'modules.chat', icon: 'chat', route: '/chat', scopes: ['chat:use'] },
	{ key: 'files', name_key: 'modules.files', icon: 'files', route: '/files', scopes: [] },
	{ key: 'tasks', name_key: 'modules.tasks', icon: 'tasks', route: '/tasks', scopes: [] }
];

const html = (locale: Locale, list: ModuleEntry[], current = '') =>
	render(Harness, { props: { locale, modules: list, current } }).body;

describe('Sidebar', () => {
	it('renders one link per module from the API list, in order', () => {
		const out = html('en', modules);
		const labels = [...out.matchAll(/data-module="(\w+)"[^>]*>.*?<span>([^<]+)<\/span>/gs)];
		expect(labels.map((m) => [m[1], m[2]])).toEqual([
			['chat', 'Chat'],
			['files', 'Files'],
			['tasks', 'Tasks']
		]);
		expect(out).toContain('href="/chat"');
	});

	it('translates module names into German', () => {
		expect(html('de', modules)).toContain('Aufgaben');
	});

	it('marks the current module', () => {
		expect(html('en', modules, '/files')).toMatch(/href="\/files"[^>]*aria-current="page"|aria-current="page"[^>]*href="\/files"/);
	});

	it('shows the empty state without modules', () => {
		expect(html('en', [])).toContain(translate('en', 'nav.empty'));
	});

	it('exposes a labelled navigation landmark', () => {
		expect(html('de', modules)).toContain(`aria-label="${translate('de', 'nav.primary')}"`);
	});
});
