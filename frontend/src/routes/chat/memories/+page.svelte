<script lang="ts">
	import { onMount } from 'svelte';
	import {
		createMemory,
		deleteMemory,
		getWriteMode,
		listMemories,
		setWriteMode,
		updateMemory,
		type Memory,
		type WriteMode
	} from '#lib/api/agent.ts';
	import { getT } from '#lib/i18n/context.ts';
	import { Alert, Button } from '#lib/ui/index.ts';

	const t = getT();
	let items = $state<Memory[]>([]);
	let writeMode = $state<WriteMode>('ask');
	let draft = $state('');
	let editingId = $state<string | null>(null);
	let editValue = $state('');
	let loading = $state(true);
	let busy = $state(false);
	let error = $state('');

	onMount(async () => {
		try {
			[items, writeMode] = await Promise.all([listMemories(), getWriteMode()]);
		} catch {
			error = t('memory.error');
		} finally {
			loading = false;
		}
	});

	async function run(action: () => Promise<void>) {
		busy = true;
		error = '';
		try {
			await action();
		} catch (failure) {
			error = failure instanceof Error && failure.message.endsWith('409') ? t('memory.limit') : t('memory.error');
		} finally {
			busy = false;
		}
	}

	const add = (event: SubmitEvent) => {
		event.preventDefault();
		const content = draft.trim();
		if (!content) return;
		void run(async () => {
			items = [await createMemory(content), ...items];
			draft = '';
		});
	};

	const save = (item: Memory) => {
		const content = editValue.trim();
		if (!content) return;
		void run(async () => {
			const updated = await updateMemory(item.id, content);
			items = items.map((row) => (row.id === item.id ? updated : row));
			editingId = null;
		});
	};

	const remove = (item: Memory) => {
		if (!window.confirm(t('memory.confirmDelete'))) return;
		void run(async () => {
			await deleteMemory(item.id);
			items = items.filter((row) => row.id !== item.id);
		});
	};

	const changeMode = (mode: WriteMode) => {
		void run(async () => {
			writeMode = await setWriteMode(mode);
		});
	};
</script>

<svelte:head><title>{t('memory.title')} · {t('app.name')}</title></svelte:head>
<section class="glass-panel memory">
	<a class="back" href="/chat">{t('memory.back')}</a>
	<h1>{t('memory.title')}</h1>
	{#if error}<Alert>{error}</Alert>{/if}

	<fieldset class="mode">
		<legend>{t('memory.writeModeTitle')}</legend>
		<p class="muted">{t('memory.writeModeHelp')}</p>
		<label><input type="radio" name="write-mode" value="ask" checked={writeMode === 'ask'} disabled={busy || loading} onchange={() => changeMode('ask')} /> {t('memory.writeModeAsk')}</label>
		<label><input type="radio" name="write-mode" value="allow" checked={writeMode === 'allow'} disabled={busy || loading} onchange={() => changeMode('allow')} /> {t('memory.writeModeAllow')}</label>
	</fieldset>

	<p class="muted">{t('memory.intro')}</p>
	<form class="create" onsubmit={add}>
		<label class="field">
			<span>{t('memory.new')}</span>
			<textarea class="glass-control" bind:value={draft} rows="2" maxlength="1000"></textarea>
		</label>
		<Button type="submit" disabled={busy || !draft.trim()}>{t('memory.add')}</Button>
	</form>

	{#if loading}
		<p role="status">{t('common.loading')}</p>
	{:else if items.length === 0}
		<p class="muted">{t('memory.empty')}</p>
	{:else}
		<ul>
			{#each items as item (item.id)}
				<li>
					{#if editingId === item.id}
						<label class="field">
							<span>{t('memory.editLabel')}</span>
							<textarea class="glass-control" bind:value={editValue} rows="2" maxlength="1000"></textarea>
						</label>
						<div class="actions">
							<Button type="button" disabled={busy || !editValue.trim()} onclick={() => save(item)}>{t('memory.save')}</Button>
							<Button type="button" variant="quiet" onclick={() => (editingId = null)}>{t('memory.cancel')}</Button>
						</div>
					{:else}
						<p class="content">{item.content}</p>
						<p class="muted">{item.source === 'agent' ? t('memory.sourceAgent') : t('memory.sourceUser')}</p>
						<div class="actions">
							<Button type="button" variant="quiet" disabled={busy} onclick={() => { editingId = item.id; editValue = item.content; }}>{t('memory.edit')}</Button>
							<Button type="button" variant="quiet" disabled={busy} onclick={() => remove(item)}>{t('memory.delete')}</Button>
						</div>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	.memory { max-width: 52rem; margin: 0 auto; padding: clamp(1rem, 3vw, 1.5rem); display: grid; gap: 1rem; }
	h1 { margin: 0; }
	.back { color: var(--accent-text); font-size: 0.9rem; }
	.muted { color: var(--muted); margin: 0; font-size: 0.9rem; }
	.mode { display: grid; gap: 0.5rem; border: 1px solid var(--glass-rim); border-radius: 0.8rem; padding: 0.9rem 1rem; }
	.mode legend { font-weight: 650; padding: 0 0.3rem; }
	.mode label { display: flex; gap: 0.5rem; align-items: center; min-height: 44px; }
	.mode input { accent-color: var(--accent); }
	.create { display: grid; gap: 0.6rem; justify-items: start; }
	.field { display: grid; gap: 0.35rem; font-weight: 600; width: 100%; }
	textarea { font: inherit; color: var(--ink); padding: 0.6rem 0.7rem; resize: vertical; width: 100%; box-sizing: border-box; }
	ul { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.75rem; }
	li { padding: 1rem; border: 1px solid var(--glass-rim); border-radius: 0.8rem; display: grid; gap: 0.5rem; }
	.content { margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
	.actions { display: flex; flex-wrap: wrap; gap: 0.5rem; }
</style>
