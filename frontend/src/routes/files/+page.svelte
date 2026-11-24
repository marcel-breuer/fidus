<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		buildBreadcrumbs, createFolder as createFolderRequest, deleteNode, formatFileSize,
		listFileNodes, listFileVersions, renameNode, uploadFile, validateFile,
		type FileNode, type FileVersion
	} from '$lib/api/files';
	import { debounce, getDocumentStatus, groupCitations, reindexDocument, searchKnowledge, type Citation, type DocumentStatus } from '$lib/api/knowledge';
	import { formatDate } from '$lib/i18n';
	import { getT } from '$lib/i18n/context';
	import { Alert, Button, TextField } from '$lib/ui';

	const t = getT();
	let items = $state<FileNode[]>([]);
	let loading = $state(true);
	let busy = $state(false);
	let error = $state('');
	let folderName = $state('');
	let editingId = $state<string | null>(null);
	let editName = $state('');
	let knownFolders = $state<Map<string, Pick<FileNode, 'id' | 'parent_id' | 'name'>>>(new Map());
	let versions = $state<Record<string, FileVersion[]>>({});
	let documentStates = $state<Record<string, DocumentStatus>>({});
	let searchQuery = $state('');
	let searchResults = $state<Citation[]>([]);
	let searchLoading = $state(false);
	let searchError = $state(false);
	let uploadStates = $state<{ id: number; name: string; progress: number; state: 'uploading' | 'done' | 'error'; reason?: string }[]>([]);
	let uploadCounter = 0;
	let folderId = $derived(page.url.searchParams.get('folder'));
	let breadcrumbs = $derived(buildBreadcrumbs(folderId, knownFolders, t('files.root')));
	let searchGroups = $derived(groupCitations(searchResults));

	const debouncedSearch = debounce((query: string) => {
		if (!query.trim()) { searchResults = []; searchError = false; return; }
		searchLoading = true;
		searchError = false;
		void searchKnowledge(query).then((results) => { searchResults = results; }).catch(() => {
			searchResults = [];
			searchError = true;
		}).finally(() => { searchLoading = false; });
	}, 300);

	function messageFor(code: string): string {
		const keys: Record<string, 'files.invalidName' | 'files.unsupportedType' | 'files.nameConflict' | 'files.notFound' | 'files.moveCycle' | 'files.uploadTooLarge' | 'common.rateLimited'> = {
			INVALID_NAME: 'files.invalidName',
			UNSUPPORTED_TYPE: 'files.unsupportedType',
			NAME_CONFLICT: 'files.nameConflict',
			PARENT_NOT_FOUND: 'files.notFound',
			NODE_NOT_FOUND: 'files.notFound',
			MOVE_CYCLE: 'files.moveCycle',
			FILE_TOO_LARGE: 'files.uploadTooLarge',
			RATE_LIMITED: 'common.rateLimited'
		};
		return t(keys[code] ?? 'files.error');
	}

	async function refresh(currentFolder: string | null = folderId) {
		loading = true;
		error = '';
		try {
			items = await listFileNodes(currentFolder);
			const next = new Map(knownFolders);
			for (const item of items) if (item.kind === 'folder') next.set(item.id, item);
			knownFolders = next;
		} catch (cause) {
			error = messageFor(cause instanceof Error ? cause.message : '');
			items = [];
		} finally {
			loading = false;
		}
	}

	$effect(() => { void refresh(folderId); });

	$effect(() => {
		const pending = items.filter((item) => item.kind === 'file' && (!documentStates[item.id] || documentStates[item.id].status === 'pending'));
		if (!pending.length) return;
		let active = true;
		const poll = async () => {
			for (const item of pending) {
				try {
					const status = await getDocumentStatus(item.id);
					if (active) documentStates = { ...documentStates, [item.id]: status };
				} catch (cause) {
					if (active && cause instanceof Error && cause.message === 'DOCUMENT_NOT_FOUND') {
						documentStates = { ...documentStates, [item.id]: { status: 'failed', chunk_count: 0, error_code: 'DOCUMENT_NOT_FOUND' } };
					}
				}
			}
		};
		void poll();
		const timer = setInterval(() => { void poll(); }, 3000);
		return () => { active = false; clearInterval(timer); };
	});

	function statusLabel(status: DocumentStatus): string {
		if (status.status === 'pending') return t('files.indexPending');
		if (status.status === 'ready') return t('files.indexReady', { count: status.chunk_count });
		const reasonKey: Record<string, 'files.indexAiNotConfigured' | 'files.indexEncryptedPdf' | 'files.indexEmptyText' | 'files.indexTooManyPages' | 'files.indexCorrupt' | 'files.indexFailed'> = {
			AI_NOT_CONFIGURED: 'files.indexAiNotConfigured', ENCRYPTED_PDF: 'files.indexEncryptedPdf',
			EMPTY_TEXT: 'files.indexEmptyText', TOO_MANY_PAGES: 'files.indexTooManyPages',
			CORRUPT_FILE: 'files.indexCorrupt'
		};
		return t('files.indexFailedWithReason', { reason: t(reasonKey[status.error_code ?? ''] ?? 'files.indexFailed') });
	}

	async function reindex(item: FileNode) {
		try { documentStates = { ...documentStates, [item.id]: await reindexDocument(item.id) }; }
		catch { error = t('files.error'); }
	}

	function navigate(id: string | null) {
		void goto(id ? `/files?folder=${encodeURIComponent(id)}` : '/files');
	}

	async function createFolder(event: SubmitEvent) {
		event.preventDefault();
		busy = true;
		error = '';
		try {
			await createFolderRequest(folderName.trim(), folderId);
			folderName = '';
			await refresh();
		} catch (cause) {
			error = messageFor(cause instanceof Error ? cause.message : '');
		} finally { busy = false; }
	}

	async function selectFiles(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const selected = Array.from(input.files ?? []);
		const uploadParent = folderId;
		input.value = '';
		for (const file of selected) {
			const issue = validateFile(file);
			if (issue) {
				uploadStates = [...uploadStates, { id: ++uploadCounter, name: file.name, progress: 0, state: 'error', reason: issue === 'FILE_TOO_LARGE' ? t('files.tooLarge', { name: file.name }) : t('files.unsupportedType') }];
				continue;
			}
			const id = ++uploadCounter;
			uploadStates = [...uploadStates, { id, name: file.name, progress: 0, state: 'uploading' }];
			try {
				await uploadFile(file, uploadParent, (progress) => {
					uploadStates = uploadStates.map((upload) => upload.id === id ? { ...upload, progress } : upload);
				});
				uploadStates = uploadStates.map((upload) => upload.id === id ? { ...upload, state: 'done', progress: 100 } : upload);
				await refresh();
			} catch (cause) {
				const reason = cause instanceof Error ? messageFor(cause.message) : t('files.error');
				uploadStates = uploadStates.map((upload) => upload.id === id ? { ...upload, state: 'error', reason } : upload);
			}
		}
	}

	function beginRename(item: FileNode) {
		editingId = item.id;
		editName = item.name;
	}

	async function saveRename(item: FileNode) {
		try {
			await renameNode(item.id, editName.trim());
			editingId = null;
			await refresh();
		} catch (cause) { error = messageFor(cause instanceof Error ? cause.message : ''); }
	}

	async function remove(item: FileNode) {
		if (!window.confirm(t('files.deleteConfirm', { name: item.name }))) return;
		try {
			await deleteNode(item.id);
			await refresh();
		} catch (cause) { error = messageFor(cause instanceof Error ? cause.message : ''); }
	}

	async function loadVersions(item: FileNode) {
		if (versions[item.id]) return;
		try { versions = { ...versions, [item.id]: await listFileVersions(item.id) }; }
		catch (cause) { error = messageFor(cause instanceof Error ? cause.message : ''); }
	}
</script>

<svelte:head><title>{t('files.title')} · {t('app.name')}</title></svelte:head>
<section class="glass-panel files">
	<h1>{t('files.title')}</h1>
	<nav aria-label={t('files.title')} class="breadcrumbs">
		{#each breadcrumbs as crumb, index (crumb.id ?? 'root')}
			{#if index > 0}<span aria-hidden="true">/</span>{/if}
			{#if index === breadcrumbs.length - 1}<span aria-current="page">{crumb.name}</span>
			{:else}<button type="button" class="crumb" onclick={() => navigate(crumb.id)}>{crumb.name}</button>{/if}
		{/each}
	</nav>
	<div class="tools">
		<form class="create" onsubmit={createFolder}>
			<TextField label={t('files.folderName')} bind:value={folderName} maxlength={255} required />
			<Button disabled={busy || !folderName.trim()}>{t('files.createFolder')}</Button>
		</form>
		<label class="file-picker"><span>{t('files.chooseFiles')}</span><input type="file" multiple accept=".txt,.md,.markdown,.pdf,.docx" onchange={selectFiles} /></label>
	</div>
	{#if error}<Alert>{error}</Alert>{/if}
	<section class="search" aria-labelledby="knowledge-heading">
		<h2 id="knowledge-heading">{t('files.searchTitle')}</h2>
		<TextField label={t('files.searchLabel')} placeholder={t('files.searchPlaceholder')} bind:value={searchQuery} oninput={() => debouncedSearch(searchQuery)} />
		{#if searchLoading}<p role="status">{t('files.searching')}</p>
		{:else if searchError}<p role="alert">{t('files.searchError')}</p>
		{:else if searchQuery.trim() && searchResults.length === 0}<p class="empty">{t('files.searchEmpty')}</p>
		{:else if searchGroups.length}
			<ul class="search-results">
				{#each searchGroups as group (group.nodeId)}
					<li><a href={group.memoId ? '/audio' : group.folderId ? `/files?folder=${encodeURIComponent(group.folderId)}` : '/files'}>{group.fileName}</a>
						<ol>{#each group.citations as citation (citation.chunk_id)}<li><span>{citation.version === null ? t('audio.memoSource') : t('files.resultPosition', { position: citation.position + 1, version: citation.version })}</span><p>{citation.snippet}</p></li>{/each}</ol>
					</li>
				{/each}
			</ul>
		{/if}
	</section>
	{#if uploadStates.length}
		<ul class="uploads" aria-label={t('files.upload')}>
			{#each uploadStates as upload (upload.id)}
				<li role="status">
					{#if upload.state === 'uploading'}{t('files.uploading', { name: upload.name, progress: upload.progress })}
					{:else if upload.state === 'done'}{t('files.uploaded', { name: upload.name })}
					{:else}{t('files.uploadFailed', { name: upload.name, reason: upload.reason ?? t('files.error') })}{/if}
					{#if upload.state === 'uploading'}<progress max="100" value={upload.progress} aria-label={t('files.uploading', { name: upload.name, progress: upload.progress })}></progress>{/if}
				</li>
			{/each}
		</ul>
	{/if}
	{#if loading}<p role="status">{t('files.loading')}</p>
	{:else if items.length === 0}<p class="empty">{t('files.empty')}</p>
	{:else}
		<ul class="items">
			{#each items as item (item.id)}
				<li>
					<div class="entry">
						{#if editingId === item.id}
							<div class="rename"><TextField label={t('files.rename')} bind:value={editName} maxlength={255} /><Button onclick={() => saveRename(item)}>{t('files.save')}</Button><Button variant="quiet" onclick={() => editingId = null}>{t('files.cancel')}</Button></div>
						{:else if item.kind === 'folder'}
							<button type="button" class="name folder" onclick={() => navigate(item.id)}>{item.name}</button>
						{:else}
							<a class="name" href={`/api/v1/files/nodes/${encodeURIComponent(item.id)}/download`}>{item.name}</a>
						{/if}
						<dl><div><dt>{t('files.size')}</dt><dd>{item.size_bytes === null ? t('files.notAvailable') : formatFileSize(item.size_bytes, page.data.locale)}</dd></div><div><dt>{t('files.modified')}</dt><dd>{formatDate(page.data.locale, new Date(item.updated_at))}</dd></div></dl>
					</div>
					<div class="actions">
						{#if editingId !== item.id}<Button variant="quiet" onclick={() => beginRename(item)}>{t('files.rename')}</Button>{/if}
						{#if item.kind === 'file'}
							{#if documentStates[item.id]}<span class="index-status" role="status">{statusLabel(documentStates[item.id])}</span>{#if documentStates[item.id].status === 'failed'}<Button variant="quiet" onclick={() => reindex(item)}>{t('files.reindex')}</Button>{/if}{/if}
							<a class="button-link" href={`/api/v1/files/nodes/${encodeURIComponent(item.id)}/download`}>{t('files.download')}</a>
							<details ontoggle={(event) => { if ((event.currentTarget as HTMLDetailsElement).open) void loadVersions(item); }}><summary>{t('files.versions')}</summary>{#if versions[item.id]}<ol>{#each versions[item.id] as version (version.id)}<li><a href={`/api/v1/files/nodes/${encodeURIComponent(item.id)}/download?version=${version.version}`}>{t('files.versions')} {version.version}</a><span>{formatFileSize(version.size_bytes, page.data.locale)} · {formatDate(page.data.locale, new Date(version.created_at))}</span></li>{/each}</ol>{/if}</details>
						{/if}
						<Button variant="quiet" onclick={() => remove(item)}>{t('files.delete')}</Button>
					</div>
				</li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	.files { padding: clamp(1rem, 3vw, 1.5rem); display: grid; gap: 1rem; }
	.search { display: grid; gap: .7rem; border-top: 1px solid var(--glass-rim); padding-top: 1rem; }
	.search h2 { margin: 0; font-size: 1.15rem; }
	.search-results { list-style: none; padding: 0; margin: 0; display: grid; gap: .8rem; }
	.search-results > li { border: 1px solid var(--glass-rim); border-radius: .8rem; padding: .8rem; }
	.search-results a { color: var(--accent); font-weight: 650; }
	.search-results ol { display: grid; gap: .5rem; padding-left: 1.4rem; }
	.search-results p, .index-status { margin: .2rem 0; color: var(--muted); overflow-wrap: anywhere; }
	h1 { margin: 0; }
	.breadcrumbs, .tools, .create, .actions, .rename { display: flex; flex-wrap: wrap; align-items: end; gap: .65rem; }
	.breadcrumbs { align-items: center; overflow-wrap: anywhere; }
	.crumb { border: 0; background: transparent; color: var(--accent); font: inherit; text-decoration: underline; cursor: pointer; padding: .2rem; }
	.tools { align-items: end; justify-content: space-between; }
	.create { flex: 1 1 18rem; }
	.file-picker { display: inline-flex; flex-wrap: wrap; align-items: center; gap: .5rem; min-width: 0; font-weight: 600; }
	.file-picker input { width: 100%; max-width: 100%; font: inherit; }
	.uploads, .items { list-style: none; padding: 0; margin: 0; display: grid; gap: .7rem; }
	.uploads li, .items > li { border: 1px solid var(--glass-rim); border-radius: .8rem; padding: .8rem; }
	.uploads li { display: grid; gap: .4rem; }
	progress { width: 100%; accent-color: var(--accent); }
	.items > li { display: flex; flex-wrap: wrap; justify-content: space-between; gap: .8rem; }
	.entry { display: grid; gap: .5rem; min-width: min(100%, 16rem); flex: 1 1 20rem; }
	.name { color: var(--ink); font-weight: 650; overflow-wrap: anywhere; }
	.folder { text-align: left; border: 0; background: none; padding: 0; font: inherit; cursor: pointer; }
	dl { display: flex; flex-wrap: wrap; gap: .5rem 1rem; margin: 0; color: var(--muted); font-size: .875rem; }
	dl div { display: flex; gap: .3rem; }
	dt { font-weight: 600; } dd { margin: 0; }
	.actions { align-items: center; }
	.button-link { color: var(--accent); border: 1px solid var(--glass-rim); border-radius: .625rem; padding: .55rem .8rem; font-weight: 600; }
	details { align-self: center; }
	details summary { cursor: pointer; }
	details ol { padding-left: 1.2rem; min-width: min(18rem, 75vw); }
	details li { display: grid; gap: .2rem; padding: .3rem 0; }
	details li span, .empty { color: var(--muted); }
	.rename { align-items: end; }
	@media (max-width: 40rem) { .items > li { display: grid; } .actions { align-items: stretch; } }
</style>
