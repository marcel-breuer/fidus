import { createApiClient } from './http';
import { csrfHeaders } from './csrf';

export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
export type FileNode = {
	id: string;
	parent_id: string | null;
	kind: 'folder' | 'file';
	name: string;
	created_at: string;
	updated_at: string;
	size_bytes: number | null;
};
export type FileVersion = {
	id: string;
	version: number;
	size_bytes: number;
	mime_type: string;
	created_at: string;
};
export type Breadcrumb = { id: string | null; name: string };

const typedApi = createApiClient(fetch, '') as unknown as {
	GET: (path: string, options?: object) => Promise<{ data?: unknown; response: Response }>;
	POST: (path: string, options?: object) => Promise<{ data?: unknown; response: Response }>;
	PATCH: (path: string, options?: object) => Promise<{ data?: unknown; response: Response }>;
	DELETE: (path: string, options?: object) => Promise<{ response: Response }>;
};

async function assertOk(response: Response): Promise<void> {
	if (response.ok) return;
	let detail = `HTTP_${response.status}`;
	try {
		detail = (await response.clone().json()).detail ?? detail;
	} catch { /* Keep the status based error. */ }
	throw new Error(detail);
}

export function formatFileSize(bytes: number, locale: string): string {
	if (bytes < 1024) return `${new Intl.NumberFormat(locale).format(bytes)} B`;
	const units = ['KB', 'MB', 'GB', 'TB'];
	let value = bytes;
	let unit = -1;
	do { value /= 1024; unit += 1; } while (value >= 1024 && unit < units.length - 1);
	return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value)} ${units[unit]}`;
}

export function buildBreadcrumbs(
	folderId: string | null,
	knownFolders: ReadonlyMap<string, Pick<FileNode, 'id' | 'parent_id' | 'name'>>,
	rootName: string
): Breadcrumb[] {
	const path: Breadcrumb[] = [{ id: null, name: rootName }];
	const folders: Breadcrumb[] = [];
	const visited = new Set<string>();
	let current = folderId;
	while (current && !visited.has(current)) {
		visited.add(current);
		const folder = knownFolders.get(current);
		if (!folder) {
			folders.unshift({ id: current, name: current });
			break;
		}
		folders.unshift({ id: folder.id, name: folder.name });
		current = folder.parent_id;
	}
	return path.concat(folders);
}

export function validateFile(file: Pick<File, 'name' | 'size' | 'type'>): string | null {
	if (file.size > MAX_UPLOAD_BYTES) return 'FILE_TOO_LARGE';
	const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
	if (!['.txt', '.md', '.markdown', '.pdf', '.docx'].includes(extension)) return 'UNSUPPORTED_TYPE';
	return null;
}

export async function listFileNodes(parentId: string | null): Promise<FileNode[]> {
	const { data, response } = await typedApi.GET('/api/v1/files/nodes', {
		params: { query: parentId ? { parent_id: parentId } : {} }
	});
	await assertOk(response);
	return data as FileNode[];
}

export async function createFolder(name: string, parentId: string | null): Promise<FileNode> {
	const { data, response } = await typedApi.POST('/api/v1/files/folders', { body: { name, parent_id: parentId } });
	await assertOk(response);
	return data as FileNode;
}

export async function renameNode(id: string, name: string): Promise<FileNode> {
	const { data, response } = await typedApi.PATCH(`/api/v1/files/nodes/${encodeURIComponent(id)}`, { body: { name } });
	await assertOk(response);
	return data as FileNode;
}

export async function moveNode(id: string, parentId: string | null): Promise<FileNode> {
	const { data, response } = await typedApi.PATCH(`/api/v1/files/nodes/${encodeURIComponent(id)}`, { body: { parent_id: parentId } });
	await assertOk(response);
	return data as FileNode;
}

export async function deleteNode(id: string): Promise<void> {
	const { response } = await typedApi.DELETE(`/api/v1/files/nodes/${encodeURIComponent(id)}`);
	await assertOk(response);
}

export async function listFileVersions(id: string): Promise<FileVersion[]> {
	const { data, response } = await typedApi.GET(`/api/v1/files/nodes/${encodeURIComponent(id)}/versions`);
	await assertOk(response);
	return data as FileVersion[];
}

export function uploadFile(
	file: File,
	parentId: string | null,
	onProgress: (percent: number) => void = () => undefined
): Promise<FileNode> {
	return new Promise((resolve, reject) => {
		const request = new XMLHttpRequest();
		request.open('POST', '/api/v1/files/upload');
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
			try { resolve(JSON.parse(request.responseText) as FileNode); }
			catch { reject(new Error('INVALID_RESPONSE')); }
		};
		const body = new FormData();
		body.append('file', file, file.name);
		if (parentId) body.append('parent_id', parentId);
		request.send(body);
	});
}
