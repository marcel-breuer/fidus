<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		buildBreadcrumbs, createFolder as createFolderRequest, deleteNode, formatFileSize,
		listFileNodes, listFileVersions, renameNode, uploadFile, validateFile,
		type FileNode, type FileVersion
	} from '#lib/api/files.ts';
	import { debounce, getDocumentStatus, groupCitations, reindexDocument, searchKnowledge, type Citation, type DocumentStatus } from '#lib/api/knowledge.ts';
	import { formatDate } from '#lib/i18n/index.ts';
	import { getT } from '#lib/i18n/context.ts';
	import { Alert, AlertDescription } from '#lib/components/ui/alert/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Card } from '#lib/components/ui/card/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { Label } from '#lib/components/ui/label/index.ts';
	import * as Table from '#lib/components/ui/table/index.ts';

	const t = getT();
	let items = $state<FileNode[]>([]);
	let loading = $state(true);
	let busy = $state(false);
	let error = $state('');
	let pendingDelete = $state<FileNode | null>(null);
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

	async function confirmRemove() {
		const item = pendingDelete;
		pendingDelete = null;
		if (!item) return;
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
<Card class="gap-4 p-[clamp(1rem,3vw,1.5rem)]">
	<h1 class="m-0">{t('files.title')}</h1>
	<nav aria-label={t('files.title')} class="flex flex-wrap items-center gap-2.5 [overflow-wrap:anywhere]">
		{#each breadcrumbs as crumb, index (crumb.id ?? 'root')}
			{#if index > 0}<span aria-hidden="true">/</span>{/if}
			{#if index === breadcrumbs.length - 1}<span aria-current="page">{crumb.name}</span>
			{:else}<Button type="button" variant="link" class="h-auto min-h-11 px-1 underline" onclick={() => navigate(crumb.id)}>{crumb.name}</Button>{/if}
		{/each}
	</nav>
	<div class="flex flex-wrap items-end justify-between gap-2.5">
		<form class="flex flex-[1_1_18rem] flex-wrap items-end gap-2.5" onsubmit={createFolder}>
			<div class="grid gap-1.5"><Label for="folder-name" class="font-semibold">{t('files.folderName')}</Label><Input id="folder-name" bind:value={folderName} maxlength={255} required /></div>
			<Button type="submit" disabled={busy || !folderName.trim()}>{t('files.createFolder')}</Button>
		</form>
		<div class="grid min-w-0 gap-1.5"><Label for="file-picker" class="font-semibold">{t('files.chooseFiles')}</Label><Input id="file-picker" type="file" multiple accept=".txt,.md,.markdown,.pdf,.docx" onchange={selectFiles} class="h-auto max-w-full py-2" /></div>
	</div>
	{#if error}<Alert variant="destructive"><AlertDescription class="text-foreground">{error}</AlertDescription></Alert>{/if}
	<section class="grid gap-3 border-t border-(--glass-rim) pt-4" aria-labelledby="knowledge-heading">
		<h2 id="knowledge-heading" class="m-0 text-lg">{t('files.searchTitle')}</h2>
		<div class="grid gap-1.5"><Label for="knowledge-search" class="font-semibold">{t('files.searchLabel')}</Label><Input id="knowledge-search" placeholder={t('files.searchPlaceholder')} bind:value={searchQuery} oninput={() => debouncedSearch(searchQuery)} /></div>
		{#if searchLoading}<p role="status" class="m-0">{t('files.searching')}</p>
		{:else if searchError}<p role="alert" class="m-0">{t('files.searchError')}</p>
		{:else if searchQuery.trim() && searchResults.length === 0}<p class="m-0 text-muted-foreground">{t('files.searchEmpty')}</p>
		{:else if searchGroups.length}
			<ul class="m-0 grid list-none gap-3 p-0">
				{#each searchGroups as group (group.nodeId)}
					<li class="glass-inset rounded-xl p-3"><a class="font-semibold text-primary underline" href={group.memoId ? '/audio' : group.folderId ? `/files?folder=${encodeURIComponent(group.folderId)}` : '/files'}>{group.fileName}</a>
						<ol class="grid gap-2 pl-6">{#each group.citations as citation (citation.chunk_id)}<li><span>{citation.version === null ? t('audio.memoSource') : t('files.resultPosition', { position: citation.position + 1, version: citation.version })}</span><p class="my-1 text-muted-foreground [overflow-wrap:anywhere]">{citation.snippet}</p></li>{/each}</ol>
					</li>
				{/each}
			</ul>
		{/if}
	</section>
	{#if uploadStates.length}
		<ul class="m-0 grid list-none gap-3 p-0" aria-label={t('files.upload')}>
			{#each uploadStates as upload (upload.id)}
				<li role="status" class="glass-inset grid gap-1.5 rounded-xl p-3">
					{#if upload.state === 'uploading'}{t('files.uploading', { name: upload.name, progress: upload.progress })}
					{:else if upload.state === 'done'}{t('files.uploaded', { name: upload.name })}
					{:else}{t('files.uploadFailed', { name: upload.name, reason: upload.reason ?? t('files.error') })}{/if}
					{#if upload.state === 'uploading'}<progress class="w-full accent-primary" max="100" value={upload.progress} aria-label={t('files.uploading', { name: upload.name, progress: upload.progress })}></progress>{/if}
				</li>
			{/each}
		</ul>
	{/if}
	{#if loading}<p role="status" class="m-0">{t('files.loading')}</p>
	{:else if items.length === 0}<p class="m-0 text-muted-foreground">{t('files.empty')}</p>
	{:else}
		<Table.Root>
			<Table.Header>
				<Table.Row>
					<Table.Head>{t('files.title')}</Table.Head>
					<Table.Head class="hidden sm:table-cell">{t('files.size')}</Table.Head>
					<Table.Head class="hidden sm:table-cell">{t('files.modified')}</Table.Head>
				</Table.Row>
			</Table.Header>
			<Table.Body>
				{#each items as item (item.id)}
					<Table.Row>
						<Table.Cell class="min-w-48 whitespace-normal align-top [overflow-wrap:anywhere]">
							{#if editingId === item.id}
								<div class="flex flex-wrap items-end gap-2.5"><div class="grid gap-1.5"><Label for={`rename-${item.id}`} class="font-semibold">{t('files.rename')}</Label><Input id={`rename-${item.id}`} bind:value={editName} maxlength={255} /></div><Button type="button" onclick={() => saveRename(item)}>{t('files.save')}</Button><Button type="button" variant="outline" onclick={() => editingId = null}>{t('files.cancel')}</Button></div>
							{:else if item.kind === 'folder'}
								<Button type="button" variant="link" class="h-auto min-h-11 whitespace-normal px-0 text-left font-semibold text-foreground" onclick={() => navigate(item.id)}>{item.name}</Button>
							{:else}
								<a class="inline-flex min-h-11 items-center font-semibold text-foreground" href={`/api/v1/files/nodes/${encodeURIComponent(item.id)}/download`}>{item.name}</a>
							{/if}
							<dl class="m-0 flex flex-wrap gap-x-4 text-sm text-muted-foreground sm:hidden"><div class="flex gap-1"><dt class="font-semibold">{t('files.size')}</dt><dd class="m-0">{item.size_bytes === null ? t('files.notAvailable') : formatFileSize(item.size_bytes, page.data.locale)}</dd></div><div class="flex gap-1"><dt class="font-semibold">{t('files.modified')}</dt><dd class="m-0">{formatDate(page.data.locale, new Date(item.updated_at))}</dd></div></dl>
							<div class="mt-1 flex flex-wrap items-center gap-2.5">
								{#if editingId !== item.id}<Button type="button" variant="outline" onclick={() => beginRename(item)}>{t('files.rename')}</Button>{/if}
								{#if item.kind === 'file'}
									{#if documentStates[item.id]}<span class="my-1 text-muted-foreground [overflow-wrap:anywhere]" role="status">{statusLabel(documentStates[item.id])}</span>{#if documentStates[item.id].status === 'failed'}<Button type="button" variant="outline" onclick={() => reindex(item)}>{t('files.reindex')}</Button>{/if}{/if}
									<Button variant="outline" href={`/api/v1/files/nodes/${encodeURIComponent(item.id)}/download`}>{t('files.download')}</Button>
									<details class="self-center" ontoggle={(event) => { if ((event.currentTarget as HTMLDetailsElement).open) void loadVersions(item); }}><summary class="min-h-11 cursor-pointer leading-[2.75rem]">{t('files.versions')}</summary>{#if versions[item.id]}<ol class="min-w-[min(18rem,75vw)] pl-5">{#each versions[item.id] as version (version.id)}<li class="grid gap-1 py-1"><a class="text-primary underline" href={`/api/v1/files/nodes/${encodeURIComponent(item.id)}/download?version=${version.version}`}>{t('files.versions')} {version.version}</a><span class="text-muted-foreground">{formatFileSize(version.size_bytes, page.data.locale)} · {formatDate(page.data.locale, new Date(version.created_at))}</span></li>{/each}</ol>{/if}</details>
								{/if}
								<Button type="button" variant="outline" onclick={() => pendingDelete = item}>{t('files.delete')}</Button>
							</div>
						</Table.Cell>
						<Table.Cell class="hidden align-top text-muted-foreground sm:table-cell">{item.size_bytes === null ? t('files.notAvailable') : formatFileSize(item.size_bytes, page.data.locale)}</Table.Cell>
						<Table.Cell class="hidden align-top text-muted-foreground sm:table-cell">{formatDate(page.data.locale, new Date(item.updated_at))}</Table.Cell>
					</Table.Row>
				{/each}
			</Table.Body>
		</Table.Root>
	{/if}
</Card>

<Dialog.Root open={pendingDelete !== null} onOpenChange={(open) => { if (!open) pendingDelete = null; }}>
	<Dialog.Content closeLabel={t('files.cancel')}>
		<Dialog.Header>
			<Dialog.Title>{t('files.delete')}</Dialog.Title>
			<Dialog.Description>{t('files.deleteConfirm', { name: pendingDelete?.name ?? '' })}</Dialog.Description>
		</Dialog.Header>
		<Dialog.Footer>
			<Button type="button" variant="outline" onclick={() => pendingDelete = null}>{t('files.cancel')}</Button>
			<Button type="button" onclick={confirmRemove}>{t('files.delete')}</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
