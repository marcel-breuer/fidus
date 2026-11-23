import { describe, expect, it } from 'vitest';
import { formatAmount, formatDay, isEmptyUsage, USAGE_METRICS, USAGE_PERIODS } from './usage';
import { messages } from '$lib/i18n';

describe('usage helpers', () => {
	it('detects an empty period', () => {
		expect(isEmptyUsage({ daily: [] })).toBe(true);
		expect(isEmptyUsage({ daily: [{} as never] })).toBe(false);
	});

	it('formats numbers per locale and keeps one decimal for minutes only', () => {
		expect(formatAmount('en', 'input_tokens', 12345)).toBe('12,345');
		expect(formatAmount('de', 'input_tokens', 12345)).toBe('12.345');
		expect(formatAmount('en', 'transcription_minutes', 1.5)).toBe('1.5');
		expect(formatAmount('en', 'chat_requests', 2.4)).toBe('2');
	});

	it('formats calendar days without a timezone shift', () => {
		expect(formatDay('en', '2026-03-01')).toBe('Mar 1, 2026');
		expect(formatDay('de', '2026-03-01')).toBe('01.03.2026');
	});

	it('has labels in both languages for every metric and period', () => {
		for (const metric of USAGE_METRICS) {
			expect(messages.en[`usage.metric.${metric}`]).toBeTruthy();
			expect(messages.de[`usage.metric.${metric}`]).toBeTruthy();
		}
		for (const days of USAGE_PERIODS) {
			expect(messages.en[`usage.period.${days}`]).toBeTruthy();
			expect(messages.de[`usage.period.${days}`]).toBeTruthy();
		}
	});
});
