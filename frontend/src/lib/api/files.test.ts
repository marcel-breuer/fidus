import { describe, expect, it } from 'vitest';
import { buildBreadcrumbs, formatFileSize, MAX_UPLOAD_BYTES, validateFile } from './files';

describe('file helpers', () => {
	it('formats sizes with locale aware numbers', () => {
		expect(formatFileSize(512, 'en')).toBe('512 B');
		expect(formatFileSize(1536, 'en')).toBe('1.5 KB');
		expect(formatFileSize(1536, 'de')).toBe('1,5 KB');
	});

	it('builds root to leaf folder breadcrumbs and stops cycles', () => {
		const folders = new Map([
			['a', { id: 'a', name: 'First', parent_id: null }],
			['b', { id: 'b', name: 'Second', parent_id: 'a' }]
		]);
		expect(buildBreadcrumbs('b', folders, 'Files')).toEqual([
			{ id: null, name: 'Files' }, { id: 'a', name: 'First' }, { id: 'b', name: 'Second' }
		]);
	});

	it('checks extension and upload size', () => {
		expect(validateFile({ name: 'notes.MD', size: 5, type: '' })).toBeNull();
		expect(validateFile({ name: 'script.exe', size: 5, type: '' })).toBe('UNSUPPORTED_TYPE');
		expect(validateFile({ name: 'large.txt', size: MAX_UPLOAD_BYTES + 1, type: '' })).toBe('FILE_TOO_LARGE');
	});
});
