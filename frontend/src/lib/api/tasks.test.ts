import { describe, expect, it } from 'vitest';
import { formatTaskDate, serializeDateTime } from './tasks';

describe('task date helpers', () => {
	it('serializes a local date-time to an ISO instant and blank values to null', () => {
		expect(serializeDateTime('')).toBeNull();
		expect(serializeDateTime('2026-11-23T10:15:00.000Z')).toBe('2026-11-23T10:15:00.000Z');
	});

	it('formats valid dates and omits missing or invalid values', () => {
		expect(formatTaskDate(null, 'en')).toBe('');
		expect(formatTaskDate('bad date', 'en')).toBe('');
		expect(formatTaskDate('2026-11-23T10:15:00.000Z', 'en')).not.toBe('');
	});
});
