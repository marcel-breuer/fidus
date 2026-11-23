<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import { goto, replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import {
		createConversation,
		deleteConversation,
		listConversations,
		listMessages,
		renameConversation,
		streamMessage,
		type ChatMessage,
		type Conversation,
		type StreamEvent
	} from '$lib/api/chat';
	import { renderMarkdown } from '$lib/markdown';
	import { getT } from '$lib/i18n/context';
	import { Alert, Button } from '$lib/ui';

	let { conversationId = null }: { conversationId?: string | null } = $props();
	const t = getT();
	type DisplayMessage = Pick<ChatMessage, 'id' | 'role' | 'content' | 'created_at'>;
	let conversations = $state<Conversation[]>([]);
	let messages = $state<DisplayMessage[]>([]);
	let activeId = $state<string | null>(conversationId);
	let draft = $state('');
	let loading = $state(true);
	let streaming = $state(false);
	let failed = $state(false);
	let renamingId = $state<string | null>(null);
	let renameValue = $state('');
	let busyId = $state('');
	let controller: AbortController | null = null;
	let lastSubmitted = $state('');
	let shouldFollow = true;
	let messagesElement = $state<HTMLDivElement>();
	let composer = $state<HTMLTextAreaElement>();
	let initialId = untrack(() => conversationId);

	onMount(() => { void load(); });

	async function load() {
		loading = true;
		failed = false;
		try {
			conversations = await listConversations();
			if (activeId) messages = await listMessages(activeId);
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
		} else if (event.event === 'delta') {
			let assistant = messages.find((message) => message.id === 'streaming-assistant');
			if (!assistant) {
				assistant = { id: 'streaming-assistant', role: 'assistant', content: '', created_at: new Date().toISOString() };
				messages = [...messages, assistant];
			}
			messages = messages.map((message) => message.id === 'streaming-assistant'
				? { ...message, content: message.content + event.data.text } : message);
		} else if (event.event === 'done') {
			if (messages.some((message) => message.id === 'streaming-assistant')) {
				messages = messages.map((message) => message.id === 'streaming-assistant'
					? { ...message, id: event.data.message_id } : message);
			} else {
				messages = [...messages, {
					id: event.data.message_id,
					role: 'assistant',
					content: '',
					created_at: new Date().toISOString()
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
		const text = content.trim();
		if (!text || streaming) return;
		failed = false;
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
			await streamMessage(targetId, text, controller.signal, handleEvent);
			conversations = await listConversations();
		} catch (error) {
			if (!(error instanceof DOMException && error.name === 'AbortError')) failed = true;
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
</script>

<svelte:head><title>{t('chat.title')} · {t('app.name')}</title></svelte:head>
<div class="chat-layout">
	<aside class="conversation-panel glass-chrome" aria-label={t('chat.conversations')}>
		<div class="list-heading">
			<h1>{t('chat.conversations')}</h1>
			<Button variant="quiet" onclick={startNew} disabled={streaming}>{t('chat.new')}</Button>
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
						<div class="bubble glass-inset" aria-live={message.id === 'streaming-assistant' ? 'polite' : undefined}>
							{@html renderMarkdown(message.content)}
						</div>
					</article>
				{/each}
			</div>
		{/if}
		<form class="composer" onsubmit={submit}>
			{#if failed}<Alert>{t('chat.error')}</Alert>{/if}
			<label class="visually-hidden" for="chat-composer">{t('chat.composer')}</label>
			<textarea id="chat-composer" bind:this={composer} bind:value={draft} class="glass-control" rows="3" maxlength="20000" placeholder={t('chat.placeholder')} disabled={streaming} onkeydown={composerKeydown}></textarea>
			<div class="composer-actions">
				{#if failed && lastSubmitted}<Button type="button" variant="quiet" disabled={streaming} onclick={() => void send(lastSubmitted)}>{t('chat.retry')}</Button>{/if}
				{#if streaming}
					<Button type="button" variant="quiet" onclick={stop}>{t('chat.stop')}</Button>
				{:else}
					<Button type="submit" disabled={!draft.trim()}>{t('chat.send')}</Button>
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
	.empty-state { color: var(--muted); margin: auto; text-align: center; }
	.composer { display: grid; gap: 0.5rem; }
	textarea { width: 100%; resize: vertical; padding: 0.7rem; font: inherit; }
	.composer-actions { display: flex; justify-content: flex-end; gap: 0.5rem; }
	.visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
	@media (max-width: 720px) {
		.chat-layout { height: auto; min-height: calc(100vh - 3rem); grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(26rem, 1fr); }
		.conversation-panel { max-height: 14rem; }
		.chat-main { min-height: 30rem; }
		.message { width: min(96%, 52rem); }
	}
</style>
