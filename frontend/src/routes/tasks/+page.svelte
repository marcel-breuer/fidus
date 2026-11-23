<script lang="ts">
	import { page } from '$app/state';
	import { createTask, completeTask, deleteTask, formatTaskDate, getTasks, serializeDateTime, updateTask, type Task, type TaskStatus } from '$lib/api/tasks';
	import { getT } from '$lib/i18n/context';
	import { Alert, Button, TextField } from '$lib/ui';

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
<section class="glass-panel tasks">
	<h1>{t('tasks.title')}</h1>
	<form class="create" onsubmit={addTask}>
		<TextField label={t('tasks.taskTitle')} bind:value={title} maxlength={500} required />
		<TextField label={t('tasks.dueAt')} type="datetime-local" bind:value={dueAt} />
		<TextField label={t('tasks.remindAt')} type="datetime-local" bind:value={remindAt} />
		<label class="field"><span>{t('tasks.notes')}</span><textarea class="glass-control" bind:value={notes} rows="3"></textarea></label>
		<Button disabled={saving || !title.trim()}>{saving ? t('common.loading') : t('tasks.add')}</Button>
	</form>
	<div class="filters" role="group" aria-label={t('tasks.filter')}>
		<Button variant={filter === 'open' ? 'primary' : 'quiet'} onclick={() => filter = 'open'}>{t('tasks.open')}</Button>
		<Button variant={filter === 'done' ? 'primary' : 'quiet'} onclick={() => filter = 'done'}>{t('tasks.done')}</Button>
		<Button variant={filter === 'all' ? 'primary' : 'quiet'} onclick={() => filter = 'all'}>{t('tasks.all')}</Button>
	</div>
	{#if error}<Alert>{error}</Alert>{/if}
	{#if loading}<p role="status">{t('common.loading')}</p>
	{:else if items.length === 0}<p class="empty">{t('tasks.empty')}</p>
	{:else}
		<ul>
			{#each items as task (task.id)}
				<li>
					<label class="complete"><input type="checkbox" checked={Boolean(task.done_at)} onchange={() => toggleTask(task)} /><span class:finished={Boolean(task.done_at)}>{task.title}</span></label>
					{#if editing === task.id}
						<TextField label={t('tasks.taskTitle')} bind:value={editTitle} />
						<label class="field"><span>{t('tasks.notes')}</span><textarea class="glass-control" bind:value={editNotes} rows="2"></textarea></label>
						<div class="actions"><Button onclick={() => saveEdit(task)}>{t('tasks.save')}</Button><Button variant="quiet" onclick={() => editing = null}>{t('tasks.cancel')}</Button></div>
					{:else}
						{#if task.notes}<p>{task.notes}</p>{/if}
						{#if task.due_at}<p class="date">{t('tasks.dueLabel', { date: formatTaskDate(task.due_at, page.data.locale) })}</p>{/if}
						<div class="actions"><Button variant="quiet" onclick={() => beginEdit(task)}>{t('tasks.edit')}</Button><Button variant="quiet" onclick={() => remove(task)}>{t('tasks.delete')}</Button></div>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	.tasks { padding: clamp(1rem, 3vw, 1.5rem); display: grid; gap: 1rem; }
	h1 { margin: 0; }
	.create { display: grid; gap: .8rem; grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr)); }
	.field { display: grid; gap: .35rem; font-weight: 600; }
	textarea { font: inherit; color: var(--ink); padding: .6rem .7rem; resize: vertical; }
	.filters, .actions { display: flex; flex-wrap: wrap; gap: .5rem; }
	ul { list-style: none; padding: 0; margin: 0; display: grid; gap: .75rem; }
	li { padding: 1rem; border: 1px solid var(--glass-rim); border-radius: .8rem; display: grid; gap: .65rem; }
	.complete { display: flex; gap: .65rem; align-items: center; font-weight: 650; }
	.complete input { width: 1.1rem; height: 1.1rem; accent-color: var(--accent); }
	.finished, .date, .empty { color: var(--muted); }
	.finished { text-decoration: line-through; }
	li p { margin: 0; overflow-wrap: anywhere; }
</style>
