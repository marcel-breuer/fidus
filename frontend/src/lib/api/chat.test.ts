import { describe, expect, it } from 'vitest';
import { parseSseChunk } from './chat';

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
