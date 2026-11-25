<script lang="ts">
	import { page } from '$app/state';
	import { createTask, completeTask, deleteTask, formatTaskDate, getTasks, serializeDateTime, updateTask, type Task, type TaskStatus } from '#lib/api/tasks.ts';
	import { getT } from '#lib/i18n/context.ts';
	import { Alert, AlertDescription } from '#lib/components/ui/alert/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Card } from '#lib/components/ui/card/index.ts';
	import { Checkbox } from '#lib/components/ui/checkbox/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { Label } from '#lib/components/ui/label/index.ts';
	import { Tabs, TabsList, TabsTrigger } from '#lib/components/ui/tabs/index.ts';
	import { Textarea } from '#lib/components/ui/textarea/index.ts';

	const t = getT();
	let items = $state<Task[]>([]);
	let filter = $state<TaskStatus>('open');
	let title = $state('');
	let notes = $state('');
	let dueAt = $state('');
	let remindAt = $state('');
	let editing = $state<string | null>(null);
	let editTitle = $state('');
	let editNotes = $state('');
	let loading = $state(true);
	let saving = $state(false);
	let error = $state('');

	async function refresh() {
		loading = true;
		error = '';
		try {
			items = (await getTasks(filter)).items;
		} catch {
			error = t('tasks.error');
		} finally {
			loading = false;
		}
	}

	$effect(() => { filter; void refresh(); });

	async function addTask(event: SubmitEvent) {
		event.preventDefault();
		saving = true;
		error = '';
		try {
			await createTask({
				title: title.trim(),
				notes: notes.trim() || null,
				due_at: serializeDateTime(dueAt),
				remind_at: serializeDateTime(remindAt)
			});
			title = '';
			notes = '';
			dueAt = '';
			remindAt = '';
			await refresh();
		} catch {
			error = t('tasks.error');
		} finally {
			saving = false;
		}
	}

	async function toggleTask(task: Task) {
		try {
			await completeTask(task.id, !task.done_at);
			await refresh();
		} catch { error = t('tasks.error'); }
	}

	function beginEdit(task: Task) {
		editing = task.id;
		editTitle = task.title;
		editNotes = task.notes ?? '';
	}

	async function saveEdit(task: Task) {
		try {
			await updateTask(task.id, { title: editTitle.trim(), notes: editNotes.trim() || null });
			editing = null;
			await refresh();
		} catch { error = t('tasks.error'); }
	}

	async function remove(task: Task) {
		try { await deleteTask(task.id); await refresh(); }
		catch { error = t('tasks.error'); }
	}
</script>

<svelte:head><title>{t('tasks.title')} · {t('app.name')}</title></svelte:head>
<Card class="gap-4 p-[clamp(1rem,3vw,1.5rem)]">
	<h1 class="m-0">{t('tasks.title')}</h1>
	<form class="grid grid-cols-[repeat(auto-fit,minmax(min(100%,14rem),1fr))] gap-3" onsubmit={addTask}>
		<div class="grid gap-1.5"><Label for="task-title" class="font-semibold">{t('tasks.taskTitle')}</Label><Input id="task-title" bind:value={title} maxlength={500} required /></div>
		<div class="grid gap-1.5"><Label for="task-due" class="font-semibold">{t('tasks.dueAt')}</Label><Input id="task-due" type="datetime-local" bind:value={dueAt} /></div>
		<div class="grid gap-1.5"><Label for="task-remind" class="font-semibold">{t('tasks.remindAt')}</Label><Input id="task-remind" type="datetime-local" bind:value={remindAt} /></div>
		<div class="grid gap-1.5"><Label for="task-notes" class="font-semibold">{t('tasks.notes')}</Label><Textarea id="task-notes" bind:value={notes} rows={3} class="resize-y" /></div>
		<Button type="submit" class="self-start" disabled={saving || !title.trim()}>{saving ? t('common.loading') : t('tasks.add')}</Button>
	</form>
	<Tabs bind:value={filter}>
		<TabsList class="group-data-horizontal/tabs:h-11 max-w-full" aria-label={t('tasks.filter')}>
			<TabsTrigger value="open">{t('tasks.open')}</TabsTrigger>
			<TabsTrigger value="done">{t('tasks.done')}</TabsTrigger>
			<TabsTrigger value="all">{t('tasks.all')}</TabsTrigger>
		</TabsList>
	</Tabs>
	{#if error}<Alert variant="destructive"><AlertDescription class="text-foreground">{error}</AlertDescription></Alert>{/if}
	{#if loading}<p role="status" class="m-0">{t('common.loading')}</p>
	{:else if items.length === 0}<p class="m-0 text-muted-foreground">{t('tasks.empty')}</p>
	{:else}
		<ul class="m-0 grid list-none gap-3 p-0">
			{#each items as task (task.id)}
				<li class="glass-inset grid gap-2.5 rounded-xl p-4">
					<div class="flex min-h-11 items-center gap-2.5 font-semibold">
						<Checkbox id={`task-${task.id}`} checked={Boolean(task.done_at)} onCheckedChange={() => toggleTask(task)} />
						<Label for={`task-${task.id}`} class={`font-semibold [overflow-wrap:anywhere] ${task.done_at ? 'text-muted-foreground line-through' : ''}`}>{task.title}</Label>
					</div>
					{#if editing === task.id}
						<div class="grid gap-1.5"><Label for={`edit-title-${task.id}`} class="font-semibold">{t('tasks.taskTitle')}</Label><Input id={`edit-title-${task.id}`} bind:value={editTitle} /></div>
						<div class="grid gap-1.5"><Label for={`edit-notes-${task.id}`} class="font-semibold">{t('tasks.notes')}</Label><Textarea id={`edit-notes-${task.id}`} bind:value={editNotes} rows={2} class="resize-y" /></div>
						<div class="flex flex-wrap gap-2"><Button type="button" onclick={() => saveEdit(task)}>{t('tasks.save')}</Button><Button type="button" variant="outline" onclick={() => editing = null}>{t('tasks.cancel')}</Button></div>
					{:else}
						{#if task.notes}<p class="m-0 [overflow-wrap:anywhere]">{task.notes}</p>{/if}
						{#if task.due_at}<p class="m-0 text-muted-foreground [overflow-wrap:anywhere]">{t('tasks.dueLabel', { date: formatTaskDate(task.due_at, page.data.locale) })}</p>{/if}
						<div class="flex flex-wrap gap-2"><Button type="button" variant="outline" onclick={() => beginEdit(task)}>{t('tasks.edit')}</Button><Button type="button" variant="outline" onclick={() => remove(task)}>{t('tasks.delete')}</Button></div>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</Card>
