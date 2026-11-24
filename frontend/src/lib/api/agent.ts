import type { components } from './schema';
import { createApiClient } from './http';

export type Memory = components['schemas']['MemoryOut'];
export type AgentAction = components['schemas']['AgentActionOut'];
export type WriteMode = components['schemas']['AgentSettingsOut']['write_mode'];

/** A source the assistant relied on; `ref` matches the [n] markers in the answer. */
export type SourceReference =
	| { type: 'file'; ref: number; file_name: string; node_id: string; folder_id: string | null; version: number; position: number; snippet: string }
	| { type: 'web'; ref: number; title: string; url: string }
	| { type: 'conversation'; ref: number; message_id: string; conversation_id: string; snippet: string }
	| { type: 'attachment'; ref: number; filename: string };

const api = createApiClient(fetch, '');

function assertOk(response: Response): void {
	if (!response.ok) throw new Error(`Agent request failed: ${response.status}`);
}

export async function listMemories(): Promise<Memory[]> {
	const { data, response } = await api.GET('/api/v1/memories');
	assertOk(response);
	return data as Memory[];
}

export async function createMemory(content: string): Promise<Memory> {
	const { data, response } = await api.POST('/api/v1/memories', { body: { content } });
	assertOk(response);
	return data as Memory;
}

export async function updateMemory(id: string, content: string): Promise<Memory> {
	const { data, response } = await api.PATCH('/api/v1/memories/{memory_id}', {
		params: { path: { memory_id: id } },
		body: { content }
	});
	assertOk(response);
	return data as Memory;
}

export async function deleteMemory(id: string): Promise<void> {
	const { response } = await api.DELETE('/api/v1/memories/{memory_id}', {
		params: { path: { memory_id: id } }
	});
	assertOk(response);
}

export async function getWriteMode(): Promise<WriteMode> {
	const { data, response } = await api.GET('/api/v1/agent/settings');
	assertOk(response);
	return (data as { write_mode: WriteMode }).write_mode;
}

export async function setWriteMode(writeMode: WriteMode): Promise<WriteMode> {
	const { data, response } = await api.PUT('/api/v1/agent/settings', { body: { write_mode: writeMode } });
	assertOk(response);
	return (data as { write_mode: WriteMode }).write_mode;
}

export async function listActions(conversationId: string): Promise<AgentAction[]> {
	const { data, response } = await api.GET('/api/v1/conversations/{conversation_id}/actions', {
		params: { path: { conversation_id: conversationId } }
	});
	assertOk(response);
	return data as AgentAction[];
}

export async function decideAction(id: string, approve: boolean): Promise<AgentAction> {
	const path = approve ? '/api/v1/agent/actions/{action_id}/approve' : '/api/v1/agent/actions/{action_id}/reject';
	const { data, response } = await api.POST(path, { params: { path: { action_id: id } } });
	assertOk(response);
	return data as AgentAction;
}

/** Only http(s) links may become anchors; anything else is shown as plain text. */
export function safeHref(url: string): string | null {
	try {
		const parsed = new URL(url);
		return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : null;
	} catch {
		return null;
	}
}

/** Persisted citations are untyped JSON; keep only well-formed entries, ordered by ref. */
export function parseSources(value: unknown): SourceReference[] {
	if (!Array.isArray(value)) return [];
	const result: SourceReference[] = [];
	for (const item of value) {
		if (!item || typeof item !== 'object' || typeof item.ref !== 'number') continue;
		if (item.type === 'web' && typeof item.url === 'string' && typeof item.title === 'string') result.push(item);
		else if (item.type === 'file' && typeof item.node_id === 'string' && typeof item.file_name === 'string') result.push(item);
		else if (item.type === 'conversation' && typeof item.conversation_id === 'string') result.push(item);
		else if (item.type === 'attachment' && typeof item.filename === 'string') result.push(item);
	}
	return result.sort((a, b) => a.ref - b.ref);
}

/** Where a file citation leads: the folder that holds the file, or the file root. */
export function fileSourceHref(source: { folder_id: string | null }): string {
	return source.folder_id ? `/files?folder=${encodeURIComponent(source.folder_id)}` : '/files';
}

const SUMMARY_PREVIEW_LENGTH = 120;

function preview(text: string): string {
	const flat = text.replace(/\s+/g, ' ').trim();
	return flat.length > SUMMARY_PREVIEW_LENGTH ? `${flat.slice(0, SUMMARY_PREVIEW_LENGTH)}…` : flat;
}

export function actionSummary(action: Pick<AgentAction, 'tool' | 'arguments'>): string {
	const args = action.arguments as Record<string, unknown>;
	if (action.tool === 'create_file' || action.tool === 'update_file') {
		const content = typeof args.content === 'string' ? preview(args.content) : '';
		const name = typeof args.name === 'string' ? args.name : '';
		return [name, content].filter(Boolean).join(': ');
	}
	const text = action.tool === 'remember' ? args.content : args.title;
	return typeof text === 'string' ? text : '';
}
