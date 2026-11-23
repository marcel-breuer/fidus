import { createApiClient } from './http';

export type TaskStatus = 'open' | 'done' | 'all';
export type Task = {
	id: string;
	title: string;
	notes: string | null;
	due_at: string | null;
	remind_at: string | null;
	done_at: string | null;
	created_at: string;
	updated_at: string;
};
export type Reminder = {
	id: string;
	task_id: string;
	task_title: string;
	due_at: string;
	state: 'pending' | 'shown';
};
export type TaskInput = {
	title: string;
	notes?: string | null;
	due_at?: string | null;
	remind_at?: string | null;
};
export type TaskPage = { items: Task[]; next_cursor: string | null };

// The generated OpenAPI client is refreshed by the maintainer after this API change.
const typedApi = createApiClient(fetch, '') as unknown as {
	GET: (path: string, options?: object) => Promise<{ data?: unknown; response: Response }>;
	POST: (path: string, options?: object) => Promise<{ data?: unknown; response: Response }>;
	PATCH: (path: string, options?: object) => Promise<{ data?: unknown; response: Response }>;
	DELETE: (path: string, options?: object) => Promise<{ response: Response }>;
};

function assertOk(response: Response): void {
	if (!response.ok) throw new Error(`Task request failed: ${response.status}`);
}

export function serializeDateTime(value: string): string | null {
	if (!value) return null;
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) throw new Error('Invalid date');
	return date.toISOString();
}

export function formatTaskDate(value: string | null, locale: string): string {
	if (!value) return '';
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return '';
	return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

export async function getTasks(status: TaskStatus): Promise<TaskPage> {
	const { data, response } = await typedApi.GET('/api/v1/tasks', { params: { query: { status } } });
	assertOk(response);
	return data as TaskPage;
}

export async function createTask(input: TaskInput): Promise<Task> {
	const { data, response } = await typedApi.POST('/api/v1/tasks', { body: input });
	assertOk(response);
	return data as Task;
}

export async function updateTask(id: string, input: Partial<TaskInput>): Promise<Task> {
	const { data, response } = await typedApi.PATCH('/api/v1/tasks/{task_id}', {
		params: { path: { task_id: id } },
		body: input
	});
	assertOk(response);
	return data as Task;
}

export async function completeTask(id: string, done: boolean): Promise<Task> {
	const path = `/api/v1/tasks/${encodeURIComponent(id)}/${done ? 'complete' : 'reopen'}`;
	const { data, response } = await typedApi.POST(path);
	assertOk(response);
	return data as Task;
}

export async function deleteTask(id: string): Promise<void> {
	const { response } = await typedApi.DELETE(`/api/v1/tasks/${encodeURIComponent(id)}`);
	assertOk(response);
}
