<script lang="ts">
	import { onDestroy, onMount, tick, untrack } from 'svelte';
	import { goto, replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import {
		createConversation,
		deleteConversation,
		listConversations,
		listMessages,
		renameConversation,
		streamMessage,
		uploadAttachment,
		fetchMessageSpeech,
		transcribeDictation,
		continueAfterAction,
		type ChatMessage,
		type Conversation,
		type StreamEvent
	} from '#lib/api/chat.ts';
	import { pickRecorderFormat } from '#lib/api/audio.ts';
	import { actionSummary, decideAction, fileSourceHref, listActions, parseSources, safeHref, type AgentAction } from '#lib/api/agent.ts';
	import { renderMarkdown } from '#lib/markdown.ts';
	import { getT } from '#lib/i18n/context.ts';
	import { messages as catalogs, type MessageKey } from '#lib/i18n/index.ts';
	import { Alert, AlertDescription } from '#lib/components/ui/alert/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Card } from '#lib/components/ui/card/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { Label } from '#lib/components/ui/label/index.ts';
	import { Textarea } from '#lib/components/ui/textarea/index.ts';

	let { conversationId = null }: { conversationId?: string | null } = $props();
	const t = getT();
	const messagesCatalog = catalogs.en;
	type DisplayMessage = Pick<ChatMessage, 'id' | 'role' | 'content' | 'created_at' | 'citations' | 'attachments'>;
	let conversations = $state<Conversation[]>([]);
	let messages = $state<DisplayMessage[]>([]);
	let activeId = $state<string | null>(untrack(() => conversationId));
	let draft = $state('');
	let attachmentFiles = $state<File[]>([]);
	let uploadedAttachmentIds = $state<(string | null)[]>([]);
	let loading = $state(true);
	let streaming = $state(false);
	let failed = $state(false);
	let failedMessage = $state('');
	let renamingId = $state<string | null>(null);
	let renameValue = $state('');
	let busyId = $state('');
	let actions = $state<AgentAction[]>([]);
	let activeTool = $state('');
	let toolFailed = $state('');
	let actionFailed = $state(false);
	let streamSources: unknown[] = [];
	let controller: AbortController | null = null;
	let lastSubmitted = $state('');
	let shouldFollow = true;
	let messagesElement = $state<HTMLDivElement>();
	let composer = $state<HTMLTextAreaElement | null>(null);
	let recording = $state(false);
	let dictating = $state(false);
	let dictationError = $state(false);
	let speechLoadingId = $state('');
	let speechErrorId = $state('');
	let recorder: MediaRecorder | null = null;
	let recordingStream: MediaStream | null = null;
	let recordingChunks: Blob[] = [];
	let recordingTimer: ReturnType<typeof setTimeout> | null = null;
	let initialId = untrack(() => conversationId);

	onMount(() => { void load(); });
	onDestroy(() => {
		if (recordingTimer) clearTimeout(recordingTimer);
		if (recorder) {
			recorder.onstop = null;
			if (recorder.state === 'recording') recorder.stop();
		}
		releaseRecordingStream();
	});

	async function load() {
		loading = true;
		failed = false;
		try {
			conversations = await listConversations();
			if (activeId) {
				messages = await listMessages(activeId);
				actions = await listActions(activeId);
			}
		} catch {
			failed = true;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		if (conversationId !== initialId) {
			initialId = conversationId;
			activeId = conversationId;
			messages = [];
			actions = [];
			if (conversationId) void load();
		}
	});

	function relativeTime(value: string): string {
		const elapsed = Math.max(0, Date.now() - new Date(value).getTime());
		if (elapsed < 60_000) return t('chat.relativeNow');
		if (elapsed < 3_600_000) return t('chat.relativeMinutes', { count: Math.floor(elapsed / 60_000) });
		if (elapsed < 86_400_000) return t('chat.relativeHours', { count: Math.floor(elapsed / 3_600_000) });
		return t('chat.relativeDays', { count: Math.floor(elapsed / 86_400_000) });
	}

	async function openConversation(id: string) {
		if (streaming) return;
		await goto(`/chat/${id}`);
	}

	async function startNew() {
		if (streaming) return;
		activeId = null;
		messages = [];
		actions = [];
		failed = false;
		await goto('/chat');
		await tick();
		composer?.focus();
	}

	async function saveRename(item: Conversation) {
		const title = renameValue.trim();
		if (!title) return;
		busyId = item.id;
		try {
			const updated = await renameConversation(item.id, title);
			conversations = conversations.map((row) => row.id === item.id ? updated : row);
			renamingId = null;
		} catch { failed = true; }
		finally { busyId = ''; }
	}

	async function removeConversation(item: Conversation) {
		if (!window.confirm(t('chat.confirmDelete', { title: item.title }))) return;
		busyId = item.id;
		try {
			await deleteConversation(item.id);
			conversations = conversations.filter((row) => row.id !== item.id);
			if (activeId === item.id) await startNew();
		} catch { failed = true; }
		finally { busyId = ''; }
	}

	function onScroll() {
		if (!messagesElement) return;
		shouldFollow = messagesElement.scrollHeight - messagesElement.scrollTop - messagesElement.clientHeight < 72;
	}

	async function scrollToBottom() {
		await tick();
		if (shouldFollow && messagesElement) messagesElement.scrollTop = messagesElement.scrollHeight;
	}

	function handleEvent(event: StreamEvent) {
		if (event.event === 'message') {
			messages = [...messages, event.data];
		} else if (event.event === 'tool') {
			activeTool = event.data.status === 'running' ? event.data.name : '';
			toolFailed = event.data.status === 'error' ? event.data.name : toolFailed;
		} else if (event.event === 'citations') {
			streamSources = event.data.items;
		} else if (event.event === 'action') {
			actions = [...actions, {
				id: event.data.id,
				conversation_id: activeId ?? '',
				message_id: null,
				tool: event.data.tool,
				arguments: event.data.arguments,
				status: 'pending',
				created_at: new Date().toISOString(),
				decided_at: null
			}];
		} else if (event.event === 'delta') {
			activeTool = '';
			let assistant = messages.find((message) => message.id === 'streaming-assistant');
			if (!assistant) {
				assistant = { id: 'streaming-assistant', role: 'assistant', content: '', created_at: new Date().toISOString(), citations: null, attachments: [] };
				messages = [...messages, assistant];
			}
			messages = messages.map((message) => message.id === 'streaming-assistant'
				? { ...message, content: message.content + event.data.text } : message);
		} else if (event.event === 'done') {
			activeTool = '';
			const doneId = event.data.message_id;
			actions = actions.map((item) => item.message_id === null ? { ...item, message_id: doneId } : item);
			if (messages.some((message) => message.id === 'streaming-assistant')) {
				messages = messages.map((message) => message.id === 'streaming-assistant'
					? { ...message, id: event.data.message_id, citations: streamSources } : message);
			} else {
				messages = [...messages, {
					id: event.data.message_id,
					role: 'assistant',
					content: '',
					created_at: new Date().toISOString(),
					citations: streamSources,
					attachments: []
				}];
			}
			conversations = conversations.map((item) => item.id === activeId
				? { ...item, title: event.data.title, updated_at: new Date().toISOString() } : item);
		} else {
			failed = true;
		}
		void scrollToBottom();
	}

	async function send(content = draft) {
		const text = content.trim() || (attachmentFiles.length ? t('chat.attachmentPrompt') : '');
		if (!text || streaming) return;
		failed = false;
		failedMessage = '';
		toolFailed = '';
		actionFailed = false;
		streamSources = [];
		activeTool = '';
		lastSubmitted = text;
		draft = '';
		streaming = true;
		shouldFollow = true;
		try {
			let targetId = activeId;
			if (!targetId) {
				const created = await createConversation();
				targetId = created.id;
				activeId = targetId;
				conversations = [created, ...conversations];
				// Shallow routing: update the URL without remounting, so the running stream keeps its state.
				replaceState(`/chat/${targetId}`, {});
			}
			controller = new AbortController();
			const attachmentIds: string[] = [];
			for (let index = 0; index < attachmentFiles.length; index += 1) {
				let attachmentId = uploadedAttachmentIds[index];
				if (!attachmentId) {
					attachmentId = (await uploadAttachment(targetId, attachmentFiles[index])).id;
					uploadedAttachmentIds[index] = attachmentId;
				}
				attachmentIds.push(attachmentId);
			}
			await streamMessage(targetId, text, controller.signal, handleEvent, attachmentIds);
			attachmentFiles = [];
			uploadedAttachmentIds = [];
			conversations = await listConversations();
		} catch (error) {
			if (!(error instanceof DOMException && error.name === 'AbortError')) {
				failed = true;
				if (error instanceof Error && error.message.includes('429')) failedMessage = t('common.rateLimited');
			}
		} finally {
			streaming = false;
			controller = null;
			await tick();
			composer?.focus();
		}
	}

	function submit(event: SubmitEvent) {
		event.preventDefault();
		void send();
	}

	function composerKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
			event.preventDefault();
			void send();
		}
	}

	function stop() { controller?.abort(); }

	async function startDictation() {
		if (!navigator.mediaDevices?.getUserMedia || !('MediaRecorder' in window)) {
			dictationError = true;
			return;
		}
		const format = pickRecorderFormat((mime) => MediaRecorder.isTypeSupported(mime));
		if (!format) {
			dictationError = true;
			return;
		}
		dictationError = false;
		dictating = true;
		try {
			if (!activeId) {
				const created = await createConversation();
				activeId = created.id;
				conversations = [created, ...conversations];
				replaceState(`/chat/${created.id}`, {});
			}
			recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
			recordingChunks = [];
			recorder = new MediaRecorder(recordingStream, { mimeType: format.mime });
			recorder.ondataavailable = (event) => { if (event.data.size) recordingChunks.push(event.data); };
			recorder.onstop = () => { void finishDictation(format.extension); };
			recorder.start();
			recording = true;
			recordingTimer = setTimeout(stopDictation, 59_000);
		} catch {
			dictationError = true;
			dictating = false;
			releaseRecordingStream();
		}
	}

	function stopDictation() {
		if (recordingTimer) clearTimeout(recordingTimer);
		recordingTimer = null;
		if (recorder?.state === 'recording') recorder.stop();
		recording = false;
	}

	function releaseRecordingStream() {
		recordingStream?.getTracks().forEach((track) => track.stop());
		recordingStream = null;
	}

	async function finishDictation(extension: string) {
		const blob = new Blob(recordingChunks, { type: recorder?.mimeType || 'audio/webm' });
		releaseRecordingStream();
		recorder = null;
		if (!blob.size || !activeId) {
			dictationError = true;
			dictating = false;
			return;
		}
		try {
			const transcript = await transcribeDictation(activeId, new File([blob], `dictation${extension}`, { type: blob.type }));
			draft = `${draft.trimEnd()}${draft.trim() ? ' ' : ''}${transcript}`;
			await tick();
			composer?.focus();
		} catch {
			dictationError = true;
		} finally {
			dictating = false;
		}
	}

	async function readAloud(message: DisplayMessage) {
		if (!activeId || message.id === 'streaming-assistant') return;
		speechLoadingId = message.id;
		speechErrorId = '';
		try {
			const blob = await fetchMessageSpeech(activeId, message.id);
			const source = URL.createObjectURL(blob);
			const player = new Audio(source);
			player.onended = () => URL.revokeObjectURL(source);
			player.onerror = () => { URL.revokeObjectURL(source); speechErrorId = message.id; };
			await player.play();
		} catch {
			speechErrorId = message.id;
		} finally {
			speechLoadingId = '';
		}
	}

	async function decide(action: AgentAction, approve: boolean) {
		busyId = action.id;
		actionFailed = false;
		try {
			const updated = await decideAction(action.id, approve);
			actions = actions.map((item) => item.id === action.id ? updated : item);
			if (activeId) {
				streaming = true;
				streamSources = [];
				controller = new AbortController();
				await continueAfterAction(activeId, action.id, controller.signal, handleEvent);
				conversations = await listConversations();
			}
		} catch { actionFailed = true; }
		finally { busyId = ''; streaming = false; controller = null; }
	}

	function toolLabel(name: string): string {
		const key = `chat.tool.${name}`;
		return key in messagesCatalog ? t(key as MessageKey) : name;
	}

	function statusLabel(status: AgentAction['status']): string {
		return t(`chat.action${status[0].toUpperCase()}${status.slice(1)}` as MessageKey);
	}
</script>

<svelte:head><title>{t('chat.title')} · {t('app.name')}</title></svelte:head>
{#snippet failure(message: string)}
	<Alert variant="destructive"><AlertDescription class="text-foreground">{message}</AlertDescription></Alert>
{/snippet}
<div class="mx-auto grid h-[calc(100vh-3rem)] min-h-136 max-w-360 grid-cols-[minmax(15rem,18rem)_minmax(0,1fr)] gap-3 max-[720px]:h-auto max-[720px]:min-h-[calc(100vh-3rem)] max-[720px]:grid-cols-[minmax(0,1fr)] max-[720px]:grid-rows-[auto_minmax(26rem,1fr)]">
	<aside class="glass-chrome min-h-0 min-w-0 overflow-auto p-4 max-[720px]:max-h-56" aria-label={t('chat.conversations')}>
		<div class="mb-3 grid gap-3">
			<h1 class="m-0 text-[1.05rem]">{t('chat.conversations')}</h1>
			<Button variant="outline" onclick={startNew} disabled={streaming}>{t('chat.new')}</Button>
			<a class="text-[0.85rem]" href="/chat/memories">{t('chat.memoryLink')}</a>
			<a class="text-[0.85rem]" href="/chat/audit">{t('chat.audit.link')}</a>
		</div>
		{#if loading}
			<p class="m-0 text-[0.78rem] text-muted-foreground">{t('common.loading')}</p>
		{:else if conversations.length === 0}
			<p class="m-0 text-[0.78rem] text-muted-foreground">{t('chat.emptyList')}</p>
		{:else}
			<ul class="m-0 grid list-none gap-2 p-0">
				{#each conversations as item (item.id)}
					<li class="min-w-0 rounded-xl p-1.5 {item.id === activeId ? 'bg-(--glass-inset-fill)' : ''}">
						{#if renamingId === item.id}
							<form class="grid gap-1.5" onsubmit={(event) => { event.preventDefault(); void saveRename(item); }}>
								<Label class="sr-only" for="rename-{item.id}">{t('chat.rename')}</Label>
								<Input id="rename-{item.id}" bind:value={renameValue} maxlength={200} />
								<Button type="submit" variant="outline" disabled={busyId === item.id}>{t('chat.saveRename')}</Button>
								<Button type="button" variant="outline" onclick={() => renamingId = null}>{t('chat.cancelRename')}</Button>
							</form>
						{:else}
							<Button variant="ghost" class="h-auto min-h-11 w-full min-w-0 justify-start rounded-md p-1.5 text-left font-normal whitespace-normal" aria-current={item.id === activeId ? 'page' : undefined} onclick={() => openConversation(item.id)}>
								<span class="grid min-w-0 gap-0.5">
									<span class="truncate">{item.title}</span>
									<time class="text-[0.78rem] text-muted-foreground" datetime={item.updated_at}>{relativeTime(item.updated_at)}</time>
								</span>
							</Button>
							<div class="flex gap-1.5">
								<Button variant="outline" class="px-2 text-xs" disabled={streaming || busyId === item.id} aria-label={t('chat.rename')} onclick={() => { renamingId = item.id; renameValue = item.title; }}>{t('chat.rename')}</Button>
								<Button variant="outline" class="px-2 text-xs" disabled={streaming || busyId === item.id} aria-label={t('chat.delete')} onclick={() => void removeConversation(item)}>{t('chat.delete')}</Button>
							</div>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</aside>

	<Card role="region" class="grid min-h-0 min-w-0 grid-rows-[minmax(0,1fr)_auto] gap-3 p-4 max-[720px]:min-h-120" aria-label={t('chat.title')}>
		{#if loading && activeId}
			<p class="m-auto text-center text-muted-foreground">{t('chat.loading')}</p>
		{:else}
			<div class="flex min-h-0 flex-col gap-4 overflow-auto scroll-smooth p-2" bind:this={messagesElement} onscroll={onScroll}>
				{#if messages.length === 0 && !streaming}
					<p class="m-auto text-center text-muted-foreground">{t('chat.emptyMessages')}</p>
				{/if}
				{#each messages as message (message.id)}
					<article class="w-[min(88%,52rem)] max-[720px]:w-[min(96%,52rem)] {message.role === 'user' ? 'self-end' : 'self-start'}">
						<p class="mx-1 mt-0 mb-1 text-[0.78rem] text-muted-foreground {message.role === 'user' ? 'text-right' : ''}">{message.role === 'user' ? t('chat.user') : t('chat.assistant')}</p>
						{#if message.content || message.role === 'user'}
							<div class="glass-inset px-4 py-3 [overflow-wrap:anywhere] [&_code]:font-mono [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_pre]:overflow-auto [&_pre]:rounded-md [&_pre]:bg-black/8 [&_pre]:p-3" aria-live={message.id === 'streaming-assistant' ? 'polite' : undefined}>
								{@html renderMarkdown(message.content)}
							</div>
						{/if}
						{#if message.attachments?.length}
							<ul class="mx-0 mt-1.5 mb-0 flex list-none flex-wrap gap-1.5 p-0 text-[0.8rem]" aria-label={t('chat.attachments')}>
								{#each message.attachments ?? [] as attachment (attachment.id)}<li class="rounded-md bg-(--glass-inset-fill) px-2 py-1 [overflow-wrap:anywhere]">{attachment.filename}</li>{/each}
							</ul>
						{/if}
						{#if message.role === 'assistant'}
							{#if message.id !== 'streaming-assistant' && message.content}
								<div class="mt-1.5 flex items-center gap-2">
									<Button type="button" variant="outline" disabled={speechLoadingId === message.id} onclick={() => void readAloud(message)}>{speechLoadingId === message.id ? t('chat.speechLoading') : t('chat.readAloud')}</Button>
									{#if speechErrorId === message.id}<span class="mx-1 mt-0 mb-1 text-[0.78rem] text-muted-foreground" role="status">{t('chat.speechError')}</span>{/if}
								</div>
							{/if}
							{@const sources = parseSources(message.citations)}
							{#if sources.length}
								<div class="mt-2">
									<p class="mx-1 mt-0 mb-1 text-[0.78rem] text-muted-foreground">{t('chat.sources')}</p>
									<ol class="m-0 grid gap-1.5 pl-[1.4rem] text-[0.85rem] [overflow-wrap:anywhere]">
										{#each sources as source (source.ref)}
											<li value={source.ref}>
												{#if source.type === 'web'}
													{@const href = safeHref(source.url)}
													<span class="mr-1.5 text-muted-foreground">{t('chat.sourceWeb')}</span>
													{#if href}<a {href} target="_blank" rel="noopener noreferrer">{source.title}</a>{:else}{source.title}{/if}
												{:else if source.type === 'file'}
													<span class="mr-1.5 text-muted-foreground">{t('chat.sourceFile')}</span>
													<a href={fileSourceHref(source)}>{t('chat.sourceFilePassage', { name: source.file_name, position: source.position + 1, version: source.version })}</a>
													<span class="block text-muted-foreground">{source.snippet}</span>
												{:else if source.type === 'attachment'}
													<span class="mr-1.5 text-muted-foreground">{t('chat.sourceAttachment')}</span>
													<span>{source.filename}</span>
												{:else}
													<span class="mr-1.5 text-muted-foreground">{t('chat.sourceConversation')}</span>
													<a href="/chat/{source.conversation_id}">{source.snippet}</a>
												{/if}
											</li>
										{/each}
									</ol>
								</div>
							{/if}
							{#each actions.filter((item) => item.message_id === message.id) as action (action.id)}
								<div class="glass-inset mt-2 grid gap-1.5 px-4 py-3 [&_p]:m-0" role="group" aria-label={t('chat.actionTitle')}>
									<p class="mx-1 mt-0 mb-1 text-[0.78rem] text-muted-foreground">{t('chat.actionTitle')}</p>
									<p><strong>{toolLabel(action.tool)}</strong>: {actionSummary(action)}</p>
									{#if action.status === 'pending'}
										<div class="flex justify-end gap-2">
											<Button type="button" disabled={busyId === action.id} onclick={() => void decide(action, true)}>{t('chat.actionApprove')}</Button>
											<Button type="button" variant="outline" disabled={busyId === action.id} onclick={() => void decide(action, false)}>{t('chat.actionReject')}</Button>
										</div>
									{:else}
										<p class="mx-1 mt-0 mb-1 text-[0.78rem] text-muted-foreground" role="status">{statusLabel(action.status)}</p>
									{/if}
								</div>
							{/each}
						{/if}
					</article>
				{/each}
			</div>
		{/if}
		<form class="grid gap-2" onsubmit={submit}>
			{#if failed}{@render failure(failedMessage || t('chat.error'))}{/if}
			{#if actionFailed}{@render failure(t('chat.actionError'))}{/if}
			{#if toolFailed && !streaming}<p class="mx-1 mt-0 mb-1 text-[0.78rem] text-muted-foreground" role="status">{t('chat.toolError', { tool: toolLabel(toolFailed) })}</p>{/if}
			{#if activeTool}<p class="mx-1 mt-0 mb-1 text-[0.78rem] text-muted-foreground" role="status">{t('chat.toolRunning', { tool: toolLabel(activeTool) })}</p>{/if}
			<Label class="sr-only" for="chat-composer">{t('chat.composer')}</Label>
			<Textarea id="chat-composer" bind:ref={composer} bind:value={draft} class="field-sizing-fixed min-h-0 resize-y" rows={3} maxlength={20000} placeholder={t('chat.placeholder')} disabled={streaming} onkeydown={composerKeydown} />
			{#if dictationError}{@render failure(t('chat.dictationError'))}{/if}
			<Label for="chat-attachments">{t('chat.attachments')}</Label>
			<Input id="chat-attachments" type="file" accept=".pdf,.txt,.md,.markdown,.png,.jpg,.jpeg,.webp" multiple disabled={streaming} onchange={(event) => {
				const selected = Array.from(event.currentTarget.files ?? []);
				if (attachmentFiles.length + selected.length <= 5) {
					attachmentFiles = [...attachmentFiles, ...selected];
					uploadedAttachmentIds = [...uploadedAttachmentIds, ...selected.map(() => null)];
				}
				event.currentTarget.value = '';
			}} />
			{#if attachmentFiles.length}
				<ul class="m-0 grid list-none gap-1 p-0" aria-label={t('chat.attachments')}>
					{#each attachmentFiles as file, index (`${file.name}-${index}`)}
						<li class="flex min-w-0 items-center justify-between gap-2 rounded-md bg-(--glass-inset-fill) [overflow-wrap:anywhere]"><span>{file.name}</span><Button type="button" variant="outline" disabled={streaming} aria-label={t('chat.removeAttachment', { name: file.name })} onclick={() => {
							attachmentFiles = attachmentFiles.filter((_, itemIndex) => itemIndex !== index);
							uploadedAttachmentIds = uploadedAttachmentIds.filter((_, itemIndex) => itemIndex !== index);
						}}>{t('chat.removeAttachmentButton')}</Button></li>
					{/each}
				</ul>
			{/if}
			<div class="flex justify-end gap-2">
				{#if recording}
					<Button type="button" variant="outline" onclick={stopDictation}>{t('chat.stopRecording')}</Button>
				{:else}
					<Button type="button" variant="outline" disabled={streaming || dictating} onclick={() => void startDictation()}>{dictating ? t('chat.transcribing') : t('chat.dictate')}</Button>
				{/if}
				{#if failed && lastSubmitted}<Button type="button" variant="outline" disabled={streaming} onclick={() => void send(lastSubmitted)}>{t('chat.retry')}</Button>{/if}
				{#if streaming}
					<Button type="button" variant="outline" onclick={stop}>{t('chat.stop')}</Button>
				{:else}
					<Button type="submit" disabled={!draft.trim() && attachmentFiles.length === 0}>{t('chat.send')}</Button>
				{/if}
			</div>
		</form>
	</Card>
</div>
