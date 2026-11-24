import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchMessageSpeech, parseSseChunk, transcribeDictation } from './chat';

afterEach(() => vi.unstubAllGlobals());

describe('parseSseChunk', () => {
	it('holds partial records across chunks', () => {
		const first = parseSseChunk('event: del', '');
		expect(first.events).toEqual([]);
		const second = parseSseChunk('ta\ndata: {"text":"hi"}\n\n', first.remainder);
		expect(second.events).toEqual([{ event: 'delta', data: '{"text":"hi"}' }]);
		expect(second.remainder).toBe('');
	});

	it('joins multiline data and ignores comments', () => {
		const parsed = parseSseChunk(': keepalive\nevent: message\ndata: one\ndata: two\n\n');
		expect(parsed.events).toEqual([{ event: 'message', data: 'one\ntwo' }]);
	});

	it('parses multiple records with CRLF delimiters', () => {
		const parsed = parseSseChunk('event: delta\r\ndata: {"text":"a"}\r\n\r\nevent: done\r\ndata: {}\r\n\r\n');
		expect(parsed.events.map((event) => event.event)).toEqual(['delta', 'done']);
	});
});

describe('chat audio requests', () => {
	it('posts a short recording and returns the transcript', async () => {
		const fetchMock = vi.fn(async () => new Response(JSON.stringify({ text: 'hello' }), {
			status: 200, headers: { 'Content-Type': 'application/json' }
		}));
		vi.stubGlobal('fetch', fetchMock);
		vi.stubGlobal('document', { cookie: '' });
		const file = new Blob(['audio'], { type: 'audio/webm' }) as File;
		Object.defineProperty(file, 'name', { value: 'voice.webm' });
		const result = await transcribeDictation('conversation/one', file);
		expect(result).toBe('hello');
		expect(fetchMock).toHaveBeenCalledWith('/api/v1/conversations/conversation%2Fone/dictation', expect.objectContaining({ method: 'POST' }));
	});

	it('fetches message speech as a blob', async () => {
		const wav = new Blob(['wav'], { type: 'audio/wav' });
		const fetchMock = vi.fn(async () => new Response(wav, { status: 200 }));
		vi.stubGlobal('fetch', fetchMock);
		vi.stubGlobal('document', { cookie: '' });
		const result = await fetchMessageSpeech('conversation-id', 'message-id');
		expect(await result.text()).toBe('wav');
		expect(fetchMock).toHaveBeenCalledWith(
			'/api/v1/conversations/conversation-id/messages/message-id/speech', expect.objectContaining({ method: 'POST' })
		);
	});
});
