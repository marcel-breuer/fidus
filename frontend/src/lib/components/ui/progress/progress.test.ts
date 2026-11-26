import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Progress from './progress.svelte';

const routeSources = import.meta.glob<string>('/src/routes/**/*.svelte', {
	query: '?raw',
	import: 'default',
	eager: true
});

describe('Progress', () => {
	it('exposes progressbar semantics with aria values and label', () => {
		const { body } = render(Progress, { props: { value: 40, max: 100, 'aria-label': 'Uploading a.txt' } });
		expect(body).toContain('role="progressbar"');
		expect(body).toContain('aria-valuenow="40"');
		expect(body).toContain('aria-valuemax="100"');
		expect(body).toContain('aria-label="Uploading a.txt"');
	});

	it('leaves no native progress or details elements in routes', () => {
		for (const [path, source] of Object.entries(routeSources)) {
			expect(source, path).not.toMatch(/<(progress|details|summary)[\s>]/);
		}
	});
});
