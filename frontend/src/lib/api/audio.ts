import { createApiClient } from './http';
import { csrfHeaders } from './csrf';

export const MAX_MEMO_BYTES = 100 * 1024 * 1024;
export const AUDIO_EXTENSIONS = ['.webm', '.ogg', '.oga', '.mp3', '.mpga', '.mpeg', '.m4a', '.mp4', '.wav', '.flac'];

export type MemoStatus = 'pending' | 'transcribing' | 'ready' | 'failed';
export type Memo = {
	id: string;
	title: string;
	status: MemoStatus;
	error_code: string | null;
	mime_type: string;
	size_bytes: number;
	language: string | null;
	document_id: string | null;
	index_status: 'pending' | 'ready' | 'failed' | null;
	index_error_code: string | null;
	created_at: string;
	updated_at: string;
};
export type MemoDetail = Memo & { transcript: string | null };

const api = createApiClient(fetch, '') as unknown as {
	GET: (path: string, options?: object) => Promise<{ data?: unknown; response: Response }>;
	PATCH: (path: string, options?: object) => Promise<{ data?: unknown; response: Response }>;
	POST: (path: string, options?: object) => Promise<{ data?: unknown; response: Response }>;
	DELETE: (path: string, options?: object) => Promise<{ response: Response }>;
};

async function assertOk(response: Response): Promise<void> {
	if (response.ok) return;
	let detail = `HTTP_${response.status}`;
	try { detail = (await response.clone().json()).detail ?? detail; } catch { /* Keep the status error. */ }
	throw new Error(detail);
}

const MIME_CANDIDATES: [string, string][] = [
	['audio/webm;codecs=opus', '.webm'],
	['audio/webm', '.webm'],
	['audio/ogg;codecs=opus', '.ogg'],
	['audio/mp4', '.m4a']
];

/** First recording container the browser supports, with the file extension the server expects. */
export function pickRecorderFormat(isSupported: (mime: string) => boolean): { mime: string; extension: string } | null {
	for (const [mime, extension] of MIME_CANDIDATES) if (isSupported(mime)) return { mime, extension };
	return null;
}

export function validateAudio(file: Pick<File, 'name' | 'size'>): string | null {
	if (file.size === 0) return 'EMPTY_FILE';
	if (file.size > MAX_MEMO_BYTES) return 'FILE_TOO_LARGE';
	const dot = file.name.lastIndexOf('.');
	const extension = dot < 0 ? '' : file.name.slice(dot).toLowerCase();
	return AUDIO_EXTENSIONS.includes(extension) ? null : 'UNSUPPORTED_TYPE';
}

export function formatDuration(seconds: number): string {
	const whole = Math.max(0, Math.floor(seconds));
	const minutes = Math.floor(whole / 60);
	return `${minutes}:${String(whole % 60).padStart(2, '0')}`;
}

export function isActive(memo: Pick<Memo, 'status' | 'index_status'>): boolean {
	return memo.status === 'pending' || memo.status === 'transcribing' || memo.index_status === 'pending';
}

export async function listMemos(): Promise<Memo[]> {
	const { data, response } = await api.GET('/api/v1/audio/memos');
	await assertOk(response);
	return data as Memo[];
}

export async function getMemo(id: string): Promise<MemoDetail> {
	const { data, response } = await api.GET(`/api/v1/audio/memos/${encodeURIComponent(id)}`);
	await assertOk(response);
	return data as MemoDetail;
}

export async function deleteMemo(id: string): Promise<void> {
	const { response } = await api.DELETE(`/api/v1/audio/memos/${encodeURIComponent(id)}`);
	await assertOk(response);
}

export async function retryMemo(id: string): Promise<Memo> {
	const { data, response } = await api.POST(`/api/v1/audio/memos/${encodeURIComponent(id)}/retry`);
	await assertOk(response);
	return data as Memo;
}

/** Returns the spoken transcript as a WAV blob; the server caches it per memo. */
export async function fetchSpeech(id: string): Promise<Blob> {
	const response = await fetch(`/api/v1/audio/memos/${encodeURIComponent(id)}/speech`, {
		method: 'POST',
		headers: csrfHeaders()
	});
	await assertOk(response);
	return response.blob();
}

export function uploadMemo(
	file: File,
	options: { title?: string; language?: string } = {},
	onProgress: (percent: number) => void = () => undefined
): Promise<Memo> {
	return new Promise((resolve, reject) => {
		const request = new XMLHttpRequest();
		request.open('POST', '/api/v1/audio/memos');
		for (const [name, value] of Object.entries(csrfHeaders())) request.setRequestHeader(name, value);
		request.upload.onprogress = (event) => {
			if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
		};
		request.onerror = () => reject(new Error('NETWORK_ERROR'));
		request.onload = () => {
			if (request.status < 200 || request.status >= 300) {
				try { reject(new Error(JSON.parse(request.responseText).detail ?? `HTTP_${request.status}`)); }
				catch { reject(new Error(`HTTP_${request.status}`)); }
				return;
			}
			try { resolve(JSON.parse(request.responseText) as Memo); }
			catch { reject(new Error('INVALID_RESPONSE')); }
		};
		const body = new FormData();
		body.append('file', file, file.name);
		if (options.title?.trim()) body.append('title', options.title.trim());
		if (options.language) body.append('language', options.language);
		request.send(body);
	});
}
