import { describe, expect, it, vi } from 'vitest';
import { debounce, groupCitations, type Citation } from './knowledge';

const citation = (node: string, position: number): Citation => ({
	chunk_id: `${node}-${position}`, document_id: `${node}-doc`, node_id: node, folder_id: 'folder',
	file_name: `${node}.txt`, version: 1, position, snippet: 'snippet', score: 0.01
});

describe('knowledge helpers', () => {
	it('groups citations by source file and keeps their order', () => {
		expect(groupCitations([citation('a', 0), citation('b', 0), citation('a', 1)])).toEqual([
			{ nodeId: 'a', fileName: 'a.txt', folderId: 'folder', citations: [citation('a', 0), citation('a', 1)] },
			{ nodeId: 'b', fileName: 'b.txt', folderId: 'folder', citations: [citation('b', 0)] }
		]);
	});

	it('debounces calls and supports cancellation', () => {
		vi.useFakeTimers();
		const callback = vi.fn();
		const later = debounce(callback, 20);
		later('old');
		later('new');
		vi.advanceTimersByTime(20);
		expect(callback).toHaveBeenCalledOnce();
		expect(callback).toHaveBeenCalledWith('new');
		later('cancelled');
		later.cancel();
		vi.advanceTimersByTime(20);
		expect(callback).toHaveBeenCalledOnce();
		vi.useRealTimers();
	});
});
