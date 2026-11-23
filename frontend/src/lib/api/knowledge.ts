import { createApiClient } from './http';

export type Citation = {
	chunk_id: string;
	document_id: string;
	node_id: string;
	folder_id: string | null;
	file_name: string;
	version: number;
	position: number;
	snippet: string;
	score: number;
};

export type DocumentStatus = { status: 'pending' | 'ready' | 'failed'; chunk_count: number; error_code: string | null };

const api = createApiClient(fetch, '') as unknown as {
	GET: (path: string, options?: object) => Promise<{ data?: unknown; response: Response }>;
	POST: (path: string, options?: object) => Promise<{ data?: unknown; response: Response }>;
};

async function assertOk(response: Response): Promise<void> {
	if (response.ok) return;
	let detail = `HTTP_${response.status}`;
	try { detail = (await response.clone().json()).detail ?? detail; } catch { /* Keep the status error. */ }
	throw new Error(detail);
}

export function debounce<Args extends unknown[]>(
	callback: (...args: Args) => void,
	delay: number
): ((...args: Args) => void) & { cancel: () => void } {
	let timer: ReturnType<typeof setTimeout> | undefined;
	const debounced = ((...args: Args) => {
		if (timer) clearTimeout(timer);
		timer = setTimeout(() => callback(...args), delay);
	}) as ((...args: Args) => void) & { cancel: () => void };
	debounced.cancel = () => { if (timer) clearTimeout(timer); };
	return debounced;
}

export type CitationGroup = { nodeId: string; fileName: string; folderId: string | null; citations: Citation[] };

export function groupCitations(citations: Citation[]): CitationGroup[] {
	const groups = new Map<string, CitationGroup>();
	for (const citation of citations) {
		let group = groups.get(citation.node_id);
		if (!group) {
			group = { nodeId: citation.node_id, fileName: citation.file_name, folderId: citation.folder_id, citations: [] };
			groups.set(citation.node_id, group);
		}
		group.citations.push(citation);
	}
	return [...groups.values()];
}

export async function getDocumentStatus(nodeId: string): Promise<DocumentStatus> {
	const { data, response } = await api.GET(`/api/v1/files/nodes/${encodeURIComponent(nodeId)}/document`);
	await assertOk(response);
	return data as DocumentStatus;
}

export async function reindexDocument(nodeId: string): Promise<DocumentStatus> {
	const { data, response } = await api.POST(`/api/v1/files/nodes/${encodeURIComponent(nodeId)}/reindex`);
	await assertOk(response);
	return data as DocumentStatus;
}

export async function searchKnowledge(query: string, limit?: number): Promise<Citation[]> {
	const { data, response } = await api.GET('/api/v1/knowledge/search', {
		params: { query: limit === undefined ? { q: query } : { q: query, limit } }
	});
	await assertOk(response);
	return (data as { results: Citation[] }).results;
}
