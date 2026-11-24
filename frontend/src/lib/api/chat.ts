import type { components } from './schema';
import { csrfHeaders } from './csrf';
import { createApiClient } from './http';

export type Conversation = components['schemas']['ConversationOut'];
export type ChatMessage = components['schemas']['MessageOut'];
type Page<T> = { items: T[]; next_cursor: string | null };

const api = createApiClient(fetch, '');

function assertOk(response: Response): void {
	if (!response.ok) throw new Error(`Chat request failed: ${response.status}`);
}

export async function listConversations(): Promise<Conversation[]> {
	const { data, response } = await api.GET('/api/v1/conversations');
	assertOk(response);
	return (data as Page<Conversation>).items;
}

export async function createConversation(): Promise<Conversation> {
	const { data, response } = await api.POST('/api/v1/conversations', { body: {} });
	assertOk(response);
	return data as Conversation;
}

export async function renameConversation(id: string, title: string): Promise<Conversation> {
	const { data, response } = await api.PATCH('/api/v1/conversations/{conversation_id}', {
		params: { path: { conversation_id: id } },
		body: { title }
	});
	assertOk(response);
	return data as Conversation;
}

export async function deleteConversation(id: string): Promise<void> {
	const { response } = await api.DELETE('/api/v1/conversations/{conversation_id}', {
		params: { path: { conversation_id: id } }
	});
	assertOk(response);
}

export async function listMessages(id: string): Promise<ChatMessage[]> {
	const { data, response } = await api.GET('/api/v1/conversations/{conversation_id}/messages', {
		params: { path: { conversation_id: id } }
	});
	assertOk(response);
	return (data as Page<ChatMessage>).items;
}

export type StreamEvent =
	| { event: 'message'; data: ChatMessage }
	| { event: 'delta'; data: { text: string } }
	| { event: 'tool'; data: { name: string; status: 'running' | 'done' | 'error' | 'awaiting_confirmation' } }
	| { event: 'citations'; data: { items: unknown[] } }
	| { event: 'action'; data: { id: string; tool: string; arguments: Record<string, unknown>; status: string } }
	| { event: 'done'; data: { message_id: string; title: string } }
	| { event: 'error'; data: { code: string } };

export type ParsedSseEvent = { event: string; data: string };

/** Parse complete SSE records while returning the unconsumed tail for the next chunk. */
export function parseSseChunk(
	chunk: string,
	remainder = ''
): { events: ParsedSseEvent[]; remainder: string } {
	const input = `${remainder}${chunk}`.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
	const records = input.split('\n\n');
	const tail = records.pop() ?? '';
	const events: ParsedSseEvent[] = [];
	for (const record of records) {
		let event = 'message';
		const data: string[] = [];
		for (const line of record.split('\n')) {
			if (!line || line.startsWith(':')) continue;
			const separator = line.indexOf(':');
			const field = separator < 0 ? line : line.slice(0, separator);
			const value = separator < 0 ? '' : line.slice(separator + 1).replace(/^ /, '');
			if (field === 'event') event = value;
			if (field === 'data') data.push(value);
		}
		if (data.length) events.push({ event, data: data.join('\n') });
	}
	return { events, remainder: tail };
}

export async function streamMessage(
	conversationId: string,
	content: string,
	signal: AbortSignal,
	onEvent: (event: StreamEvent) => void,
	attachmentIds: string[] = []
): Promise<void> {
	const response = await fetch(`/api/v1/conversations/${encodeURIComponent(conversationId)}/messages/stream`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json', ...csrfHeaders() },
		body: JSON.stringify({ content, attachment_ids: attachmentIds }),
		signal
	});
	if (!response.ok) throw new Error(`Chat request failed: ${response.status}`);
	if (!response.body) throw new Error('Chat response has no stream');
	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let remainder = '';
	const dispatch = (event: ParsedSseEvent) => {
		try {
			onEvent({ event: event.event, data: JSON.parse(event.data) } as StreamEvent);
		} catch {
			throw new Error('Invalid chat stream event');
		}
	};
	try {
		while (true) {
			const { done, value } = await reader.read();
			const parsed = parseSseChunk(done ? '' : decoder.decode(value, { stream: true }), remainder);
			remainder = parsed.remainder;
			parsed.events.forEach(dispatch);
			if (done) break;
		}
		const final = parseSseChunk('\n\n', remainder);
		final.events.forEach(dispatch);
	} finally {
		reader.releaseLock();
	}
}

export async function uploadAttachment(conversationId: string, file: File): Promise<{ id: string; filename: string }> {
	const form = new FormData();
	form.append('file', file);
	const response = await fetch(`/api/v1/conversations/${encodeURIComponent(conversationId)}/attachments`, {
		method: 'POST', headers: csrfHeaders(), body: form
	});
	assertOk(response);
	return await response.json() as { id: string; filename: string };
}

/** Transcribe a short recording for the composer without creating a memo. */
export async function transcribeDictation(conversationId: string, file: File): Promise<string> {
	const form = new FormData();
	form.append('file', file, file.name);
	const response = await fetch(`/api/v1/conversations/${encodeURIComponent(conversationId)}/dictation`, {
		method: 'POST', headers: csrfHeaders(), body: form
	});
	assertOk(response);
	return (await response.json() as { text: string }).text;
}

/** Fetch speech for an assistant message; the server caches the WAV by message. */
export async function fetchMessageSpeech(conversationId: string, messageId: string): Promise<Blob> {
	const response = await fetch(
		`/api/v1/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/speech`,
		{ method: 'POST', headers: csrfHeaders() }
	);
	assertOk(response);
	return response.blob();
}

export async function continueAfterAction(
	conversationId: string, actionId: string, signal: AbortSignal, onEvent: (event: StreamEvent) => void
): Promise<void> {
	const response = await fetch(`/api/v1/conversations/${encodeURIComponent(conversationId)}/actions/${encodeURIComponent(actionId)}/continue`, {
		method: 'POST', headers: csrfHeaders(), signal
	});
	if (!response.ok) throw new Error(`Chat continuation failed: ${response.status}`);
	if (!response.body) throw new Error('Chat response has no stream');
	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let remainder = '';
	try {
		while (true) {
			const { done, value } = await reader.read();
			const parsed = parseSseChunk(done ? '' : decoder.decode(value, { stream: true }), remainder);
			remainder = parsed.remainder;
			for (const item of parsed.events) onEvent({ event: item.event, data: JSON.parse(item.data) } as StreamEvent);
			if (done) break;
		}
		for (const item of parseSseChunk('\n\n', remainder).events) onEvent({ event: item.event, data: JSON.parse(item.data) } as StreamEvent);
	} finally { reader.releaseLock(); }
}
