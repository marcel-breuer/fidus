import { describe, expect, it } from 'vitest';
import { mergeReminders, parseReminderPayload } from './reminders';

const item = {
	id: 'r1',
	task_id: 't1',
	task_title: 'Call Sam',
	due_at: '2026-11-23T10:00:00Z',
	state: 'pending' as const
};

describe('reminder helpers', () => {
	it('parses only reminder event arrays', () => {
		expect(parseReminderPayload(JSON.stringify([item]))).toEqual([item]);
		expect(parseReminderPayload('{')).toEqual([]);
		expect(parseReminderPayload('{}')).toEqual([]);
	});

	it('uses the latest active snapshot without duplicates', () => {
		expect(mergeReminders([item], [{ ...item, task_title: 'Updated' }])).toEqual([
			{ ...item, task_title: 'Updated' }
		]);
		expect(mergeReminders([item], [])).toEqual([]);
	});
});
