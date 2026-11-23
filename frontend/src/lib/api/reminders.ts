import type { Reminder } from './tasks';
import { createApiClient } from './http';

const api = createApiClient(fetch, '') as unknown as {
	POST: (path: string, options?: object) => Promise<{ response: Response }>;
};

export function parseReminderPayload(payload: string): Reminder[] {
	try {
		const value: unknown = JSON.parse(payload);
		if (!Array.isArray(value)) return [];
		return value.filter(isReminder);
	} catch {
		return [];
	}
}

function isReminder(value: unknown): value is Reminder {
	if (!value || typeof value !== 'object') return false;
	const item = value as Record<string, unknown>;
	return (
		typeof item.id === 'string' &&
		typeof item.task_id === 'string' &&
		typeof item.task_title === 'string' &&
		typeof item.due_at === 'string' &&
		(item.state === 'pending' || item.state === 'shown')
	);
}

export function mergeReminders(current: Reminder[], incoming: Reminder[]): Reminder[] {
	const previous = new Map(current.map((item) => [item.id, item]));
	return incoming
		.filter((item) => item.state === 'pending' || item.state === 'shown')
		.map((item) => ({ ...previous.get(item.id), ...item }));
}

export async function getActiveReminders(): Promise<Reminder[]> {
	const response = await fetch('/api/v1/reminders');
	if (!response.ok) throw new Error(`Reminder request failed: ${response.status}`);
	return (await response.json()) as Reminder[];
}

export async function dismissReminder(id: string): Promise<void> {
	const { response } = await api.POST(`/api/v1/reminders/${encodeURIComponent(id)}/dismiss`);
	if (!response.ok) throw new Error(`Reminder request failed: ${response.status}`);
}
