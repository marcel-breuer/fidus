import { describe, expect, it } from 'vitest';
import { actionSummary, parseSources, safeHref } from './agent';

describe('safeHref', () => {
	it('allows http and https only', () => {
		expect(safeHref('https://example.com/a')).toBe('https://example.com/a');
		expect(safeHref('http://example.com')).toBe('http://example.com/');
		expect(safeHref('javascript:alert(1)')).toBeNull();
		expect(safeHref('data:text/html,x')).toBeNull();
		expect(safeHref('not a url')).toBeNull();
	});
});

describe('parseSources', () => {
	it('keeps well-formed entries ordered by ref and drops the rest', () => {
		const parsed = parseSources([
			{ type: 'web', ref: 2, title: 'B', url: 'https://b.test' },
			{ type: 'file', ref: 1, file_name: 'a.txt', node_id: 'n1', folder_id: null, version: 1, position: 0, snippet: 's' },
			{ type: 'web', ref: 3, title: 'no url' },
			{ type: 'unknown', ref: 4 },
			null,
			'text'
		]);
		expect(parsed.map((item) => item.ref)).toEqual([1, 2]);
	});

	it('treats missing or malformed citations as empty', () => {
		expect(parseSources(null)).toEqual([]);
		expect(parseSources({ items: [] })).toEqual([]);
	});
});

describe('actionSummary', () => {
	it('shows the memory text or the task title', () => {
		expect(actionSummary({ tool: 'remember', arguments: { content: 'Likes tea' } })).toBe('Likes tea');
		expect(actionSummary({ tool: 'create_task', arguments: { title: 'Buy milk' } })).toBe('Buy milk');
		expect(actionSummary({ tool: 'create_task', arguments: {} })).toBe('');
	});
});
