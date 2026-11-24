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
	} from '$lib/api/chat';
	import { pickRecorderFormat } from '$lib/api/audio';
	import { actionSummary, decideAction, fileSourceHref, listActions, parseSources, safeHref, type AgentAction } from '$lib/api/agent';
	import { renderMarkdown } from '$lib/markdown';
	import { getT } from '$lib/i18n/context';
	import { messages as catalogs, type MessageKey } from '$lib/i18n';
	import { Alert, Button } from '$lib/ui';

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
	let composer = $state<HTMLTextAreaElement>();
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
<div class="chat-layout">
	<aside class="conversation-panel glass-chrome" aria-label={t('chat.conversations')}>
		<div class="list-heading">
			<h1>{t('chat.conversations')}</h1>
			<Button variant="quiet" onclick={startNew} disabled={streaming}>{t('chat.new')}</Button>
			<a class="memory-link" href="/chat/memories">{t('chat.memoryLink')}</a>
			<a class="memory-link" href="/chat/audit">{t('chat.audit.link')}</a>
		</div>
		{#if loading}
			<p class="muted">{t('common.loading')}</p>
		{:else if conversations.length === 0}
			<p class="muted">{t('chat.emptyList')}</p>
		{:else}
			<ul>
				{#each conversations as item (item.id)}
					<li class:active={item.id === activeId}>
						{#if renamingId === item.id}
							<form class="rename" onsubmit={(event) => { event.preventDefault(); void saveRename(item); }}>
								<label class="visually-hidden" for="rename-{item.id}">{t('chat.rename')}</label>
								<input id="rename-{item.id}" class="glass-control" bind:value={renameValue} maxlength="200" />
								<Button type="submit" variant="quiet" disabled={busyId === item.id}>{t('chat.saveRename')}</Button>
								<Button type="button" variant="quiet" onclick={() => renamingId = null}>{t('chat.cancelRename')}</Button>
							</form>
						{:else}
							<button class="conversation-link" aria-current={item.id === activeId ? 'page' : undefined} onclick={() => openConversation(item.id)}>
								<span class="conversation-title">{item.title}</span>
								<time datetime={item.updated_at}>{relativeTime(item.updated_at)}</time>
							</button>
							<div class="row-actions">
								<Button variant="quiet" disabled={streaming || busyId === item.id} aria-label={t('chat.rename')} onclick={() => { renamingId = item.id; renameValue = item.title; }}>{t('chat.rename')}</Button>
								<Button variant="quiet" disabled={streaming || busyId === item.id} aria-label={t('chat.delete')} onclick={() => void removeConversation(item)}>{t('chat.delete')}</Button>
							</div>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</aside>

	<section class="chat-main glass-panel" aria-label={t('chat.title')}>
		{#if loading && activeId}
			<p class="empty-state">{t('chat.loading')}</p>
		{:else}
			<div class="messages" bind:this={messagesElement} onscroll={onScroll}>
				{#if messages.length === 0 && !streaming}
					<p class="empty-state">{t('chat.emptyMessages')}</p>
				{/if}
				{#each messages as message (message.id)}
					<article class="message" class:user-message={message.role === 'user'}>
						<p class="speaker">{message.role === 'user' ? t('chat.user') : t('chat.assistant')}</p>
						{#if message.content || message.role === 'user'}
							<div class="bubble glass-inset" aria-live={message.id === 'streaming-assistant' ? 'polite' : undefined}>
								{@html renderMarkdown(message.content)}
							</div>
						{/if}
						{#if message.attachments?.length}
							<ul class="message-attachments" aria-label={t('chat.attachments')}>
								{#each message.attachments ?? [] as attachment (attachment.id)}<li>{attachment.filename}</li>{/each}
							</ul>
						{/if}
						{#if message.role === 'assistant'}
							{#if message.id !== 'streaming-assistant' && message.content}
								<div class="message-actions">
									<Button type="button" variant="quiet" disabled={speechLoadingId === message.id} onclick={() => void readAloud(message)}>{speechLoadingId === message.id ? t('chat.speechLoading') : t('chat.readAloud')}</Button>
									{#if speechErrorId === message.id}<span class="speaker" role="status">{t('chat.speechError')}</span>{/if}
								</div>
							{/if}
							{@const sources = parseSources(message.citations)}
							{#if sources.length}
								<div class="sources">
									<p class="speaker">{t('chat.sources')}</p>
									<ol>
										{#each sources as source (source.ref)}
											<li value={source.ref}>
												{#if source.type === 'web'}
													{@const href = safeHref(source.url)}
													<span class="kind">{t('chat.sourceWeb')}</span>
													{#if href}<a {href} target="_blank" rel="noopener noreferrer">{source.title}</a>{:else}{source.title}{/if}
												{:else if source.type === 'file'}
													<span class="kind">{t('chat.sourceFile')}</span>
													<a href={fileSourceHref(source)}>{t('chat.sourceFilePassage', { name: source.file_name, position: source.position + 1, version: source.version })}</a>
													<span class="snippet">{source.snippet}</span>
								{:else if source.type === 'attachment'}
									<span class="kind">{t('chat.sourceAttachment')}</span>
									<span>{source.filename}</span>
												{:else}
													<span class="kind">{t('chat.sourceConversation')}</span>
													<a href="/chat/{source.conversation_id}">{source.snippet}</a>
												{/if}
											</li>
										{/each}
									</ol>
								</div>
							{/if}
							{#each actions.filter((item) => item.message_id === message.id) as action (action.id)}
								<div class="action glass-inset" role="group" aria-label={t('chat.actionTitle')}>
									<p class="speaker">{t('chat.actionTitle')}</p>
									<p><strong>{toolLabel(action.tool)}</strong>: {actionSummary(action)}</p>
									{#if action.status === 'pending'}
										<div class="composer-actions">
											<Button type="button" disabled={busyId === action.id} onclick={() => void decide(action, true)}>{t('chat.actionApprove')}</Button>
											<Button type="button" variant="quiet" disabled={busyId === action.id} onclick={() => void decide(action, false)}>{t('chat.actionReject')}</Button>
										</div>
									{:else}
										<p class="speaker" role="status">{statusLabel(action.status)}</p>
									{/if}
								</div>
							{/each}
						{/if}
					</article>
				{/each}
			</div>
		{/if}
		<form class="composer" onsubmit={submit}>
			{#if failed}<Alert>{failedMessage || t('chat.error')}</Alert>{/if}
			{#if actionFailed}<Alert>{t('chat.actionError')}</Alert>{/if}
			{#if toolFailed && !streaming}<p class="speaker" role="status">{t('chat.toolError', { tool: toolLabel(toolFailed) })}</p>{/if}
			{#if activeTool}<p class="speaker" role="status">{t('chat.toolRunning', { tool: toolLabel(activeTool) })}</p>{/if}
			<label class="visually-hidden" for="chat-composer">{t('chat.composer')}</label>
			<textarea id="chat-composer" bind:this={composer} bind:value={draft} class="glass-control" rows="3" maxlength="20000" placeholder={t('chat.placeholder')} disabled={streaming} onkeydown={composerKeydown}></textarea>
			{#if dictationError}<Alert>{t('chat.dictationError')}</Alert>{/if}
			<label for="chat-attachments">{t('chat.attachments')}</label>
			<input id="chat-attachments" type="file" accept=".pdf,.txt,.md,.markdown,.png,.jpg,.jpeg,.webp" multiple disabled={streaming} onchange={(event) => {
				const selected = Array.from(event.currentTarget.files ?? []);
				if (attachmentFiles.length + selected.length <= 5) {
					attachmentFiles = [...attachmentFiles, ...selected];
					uploadedAttachmentIds = [...uploadedAttachmentIds, ...selected.map(() => null)];
				}
				event.currentTarget.value = '';
			}} />
			{#if attachmentFiles.length}
				<ul class="attachment-list" aria-label={t('chat.attachments')}>
					{#each attachmentFiles as file, index (`${file.name}-${index}`)}
						<li><span>{file.name}</span><Button type="button" variant="quiet" disabled={streaming} aria-label={t('chat.removeAttachment', { name: file.name })} onclick={() => {
							attachmentFiles = attachmentFiles.filter((_, itemIndex) => itemIndex !== index);
							uploadedAttachmentIds = uploadedAttachmentIds.filter((_, itemIndex) => itemIndex !== index);
						}}>{t('chat.removeAttachmentButton')}</Button></li>
					{/each}
				</ul>
			{/if}
			<div class="composer-actions">
				{#if recording}
					<Button type="button" variant="quiet" onclick={stopDictation}>{t('chat.stopRecording')}</Button>
				{:else}
					<Button type="button" variant="quiet" disabled={streaming || dictating} onclick={() => void startDictation()}>{dictating ? t('chat.transcribing') : t('chat.dictate')}</Button>
				{/if}
				{#if failed && lastSubmitted}<Button type="button" variant="quiet" disabled={streaming} onclick={() => void send(lastSubmitted)}>{t('chat.retry')}</Button>{/if}
				{#if streaming}
					<Button type="button" variant="quiet" onclick={stop}>{t('chat.stop')}</Button>
				{:else}
				<Button type="submit" disabled={!draft.trim() && attachmentFiles.length === 0}>{t('chat.send')}</Button>
				{/if}
			</div>
		</form>
	</section>
</div>

<style>
	.chat-layout { display: grid; grid-template-columns: minmax(15rem, 18rem) minmax(0, 1fr); gap: 0.75rem; height: calc(100vh - 3rem); min-height: 34rem; max-width: 90rem; margin: 0 auto; }
	.conversation-panel, .chat-main { min-width: 0; min-height: 0; padding: 1rem; }
	.conversation-panel { overflow: auto; }
	.list-heading { display: grid; gap: 0.75rem; margin-bottom: 0.75rem; }
	.list-heading h1 { margin: 0; font-size: 1.05rem; }
	ul { display: grid; gap: 0.45rem; list-style: none; padding: 0; margin: 0; }
	li { min-width: 0; padding: 0.4rem; border-radius: 0.85rem; }
	li.active { background: var(--glass-inset-fill); }
	.conversation-link { width: 100%; display: grid; gap: 0.15rem; border: 0; background: none; color: inherit; text-align: left; font: inherit; padding: 0.35rem; cursor: pointer; }
	.conversation-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	time, .muted, .speaker { color: var(--muted); font-size: 0.78rem; }
	.row-actions { display: flex; gap: 0.3rem; }
	.row-actions :global(button) { font-size: 0.72rem; padding: 0.25rem 0.4rem; }
	.rename { display: grid; gap: 0.4rem; }
	.rename input { min-width: 0; padding: 0.4rem; font: inherit; }
	.chat-main { display: grid; grid-template-rows: minmax(0, 1fr) auto; gap: 0.75rem; overflow: hidden; }
	.messages { min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: 1rem; padding: 0.5rem; scroll-behavior: smooth; }
	.message { width: min(88%, 52rem); align-self: flex-start; }
	.user-message { align-self: flex-end; }
	.speaker { margin: 0 0 0.25rem 0.25rem; }
	.user-message .speaker { text-align: right; margin-right: 0.25rem; }
	.bubble { padding: 0.8rem 1rem; overflow-wrap: anywhere; }
	.bubble :global(p:first-child) { margin-top: 0; }
	.bubble :global(p:last-child) { margin-bottom: 0; }
	.bubble :global(pre) { overflow: auto; padding: 0.75rem; border-radius: 0.5rem; background: rgb(0 0 0 / 0.08); }
	.bubble :global(code) { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
	.memory-link { font-size: 0.85rem; color: var(--accent-text); }
	.sources, .action { margin-top: 0.5rem; }
	.message-actions { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.35rem; }
	.sources ol { margin: 0; padding-left: 1.4rem; display: grid; gap: 0.3rem; font-size: 0.85rem; overflow-wrap: anywhere; }
	.sources .kind { color: var(--muted); margin-right: 0.35rem; }
	.sources .snippet { display: block; color: var(--muted); }
	.action { padding: 0.7rem 1rem; display: grid; gap: 0.4rem; }
	.action p { margin: 0; }
	.empty-state { color: var(--muted); margin: auto; text-align: center; }
	.composer { display: grid; gap: 0.5rem; }
	textarea { width: 100%; resize: vertical; padding: 0.7rem; font: inherit; }
	.composer-actions { display: flex; justify-content: flex-end; gap: 0.5rem; }
	.attachment-list { display: grid; gap: 0.25rem; margin: 0; padding: 0; list-style: none; }
	.message-attachments { display: flex; flex-wrap: wrap; gap: 0.3rem; margin: 0.4rem 0 0; padding: 0; list-style: none; font-size: 0.8rem; }
	.message-attachments li { background: var(--glass-inset-fill); border-radius: 0.5rem; padding: 0.3rem 0.55rem; overflow-wrap: anywhere; }
	.attachment-list li { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; min-width: 0; overflow-wrap: anywhere; background: var(--glass-inset-fill); border-radius: 0.5rem; }
	.visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
	@media (max-width: 720px) {
		.chat-layout { height: auto; min-height: calc(100vh - 3rem); grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(26rem, 1fr); }
		.conversation-panel { max-height: 14rem; }
		.chat-main { min-height: 30rem; }
		.message { width: min(96%, 52rem); }
	}
</style>
