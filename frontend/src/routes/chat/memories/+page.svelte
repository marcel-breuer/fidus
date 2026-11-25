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
	import { Alert, AlertDescription } from '#lib/components/ui/alert/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Card } from '#lib/components/ui/card/index.ts';
	import { Label } from '#lib/components/ui/label/index.ts';
	import { RadioGroup, RadioGroupItem } from '#lib/components/ui/radio-group/index.ts';
	import { Textarea } from '#lib/components/ui/textarea/index.ts';

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
<Card class="mx-auto grid w-full max-w-208 gap-4 p-[clamp(1rem,3vw,1.5rem)]">
	<a class="text-sm" href="/chat">{t('memory.back')}</a>
	<h1 class="m-0">{t('memory.title')}</h1>
	{#if error}<Alert variant="destructive"><AlertDescription class="text-foreground">{error}</AlertDescription></Alert>{/if}

	<div class="glass-inset grid gap-2 px-4 py-3.5">
		<p id="write-mode-label" class="m-0 font-semibold">{t('memory.writeModeTitle')}</p>
		<p class="m-0 text-sm text-muted-foreground">{t('memory.writeModeHelp')}</p>
		<RadioGroup value={writeMode} onValueChange={(mode) => changeMode(mode as WriteMode)} disabled={busy || loading} aria-labelledby="write-mode-label" class="gap-0">
			<Label for="write-mode-ask" class="min-h-11 font-normal"><RadioGroupItem id="write-mode-ask" value="ask" class="border-muted-foreground" />{t('memory.writeModeAsk')}</Label>
			<Label for="write-mode-allow" class="min-h-11 font-normal"><RadioGroupItem id="write-mode-allow" value="allow" class="border-muted-foreground" />{t('memory.writeModeAllow')}</Label>
		</RadioGroup>
	</div>

	<p class="m-0 text-sm text-muted-foreground">{t('memory.intro')}</p>
	<form class="grid justify-items-start gap-2.5" onsubmit={add}>
		<div class="grid w-full gap-1.5">
			<Label for="memory-new" class="font-semibold">{t('memory.new')}</Label>
			<Textarea id="memory-new" bind:value={draft} rows={2} maxlength={1000} class="field-sizing-fixed min-h-0 resize-y" />
		</div>
		<Button type="submit" disabled={busy || !draft.trim()}>{t('memory.add')}</Button>
	</form>

	{#if loading}
		<p class="m-0" role="status">{t('common.loading')}</p>
	{:else if items.length === 0}
		<p class="m-0 text-sm text-muted-foreground">{t('memory.empty')}</p>
	{:else}
		<ul class="m-0 grid list-none gap-3 p-0">
			{#each items as item (item.id)}
				<li class="glass-inset grid gap-2 p-4">
					{#if editingId === item.id}
						<div class="grid w-full gap-1.5">
							<Label for="memory-edit-{item.id}" class="font-semibold">{t('memory.editLabel')}</Label>
							<Textarea id="memory-edit-{item.id}" bind:value={editValue} rows={2} maxlength={1000} class="field-sizing-fixed min-h-0 resize-y" />
						</div>
						<div class="flex flex-wrap gap-2">
							<Button type="button" disabled={busy || !editValue.trim()} onclick={() => save(item)}>{t('memory.save')}</Button>
							<Button type="button" variant="outline" onclick={() => (editingId = null)}>{t('memory.cancel')}</Button>
						</div>
					{:else}
						<p class="m-0 whitespace-pre-wrap [overflow-wrap:anywhere]">{item.content}</p>
						<p class="m-0 text-sm text-muted-foreground">{item.source === 'agent' ? t('memory.sourceAgent') : t('memory.sourceUser')}</p>
						<div class="flex flex-wrap gap-2">
							<Button type="button" variant="outline" disabled={busy} onclick={() => { editingId = item.id; editValue = item.content; }}>{t('memory.edit')}</Button>
							<Button type="button" variant="outline" disabled={busy} onclick={() => remove(item)}>{t('memory.delete')}</Button>
						</div>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</Card>
