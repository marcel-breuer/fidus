<script lang="ts">
	import { onMount } from 'svelte';
	import { dismissReminder, getActiveReminders, mergeReminders, parseReminderPayload } from '$lib/api/reminders';
	import type { Reminder } from '$lib/api/tasks';
	import { getT } from '$lib/i18n/context';
	import { Button } from '$lib/ui';

	let { enabled }: { enabled: boolean } = $props();
	const t = getT();
	let active = $state<Reminder[]>([]);
	let error = $state(false);

	onMount(() => {
		if (!enabled) return;
		let source: EventSource | undefined;
		let retryTimer: ReturnType<typeof setTimeout> | undefined;
		let delay = 1000;
		let disposed = false;

		const connect = () => {
			if (disposed) return;
			source = new EventSource('/api/v1/reminders/stream');
			source.addEventListener('reminders', (event) => {
				active = mergeReminders(active, parseReminderPayload((event as MessageEvent<string>).data));
				error = false;
				delay = 1000;
			});
			source.onerror = () => {
				source?.close();
				if (!disposed && !retryTimer) {
					retryTimer = setTimeout(() => {
						retryTimer = undefined;
						delay = Math.min(delay * 2, 30000);
						connect();
					}, delay);
				}
			};
		};

		void getActiveReminders().then((items) => { active = items; }).catch(() => { error = true; });
		connect();
		return () => {
			disposed = true;
			source?.close();
			if (retryTimer) clearTimeout(retryTimer);
		};
	});

	async function dismiss(id: string) {
		try {
			await dismissReminder(id);
			active = active.filter((item) => item.id !== id);
		} catch { error = true; }
	}
</script>

{#if enabled && (active.length > 0 || error)}
	<section class="glass-panel banner" role="status" aria-live="polite" aria-label={t('reminders.title')}>
		{#if error}<p>{t('reminders.error')}</p>{/if}
		{#if active.length > 0}
			<h2>{t('reminders.title')}</h2>
			<ul>
				{#each active as reminder (reminder.id)}
					<li><span>{reminder.task_title}</span><Button variant="quiet" onclick={() => dismiss(reminder.id)}>{t('reminders.dismiss')}</Button></li>
				{/each}
			</ul>
		{/if}
	</section>
{/if}

<style>
	.banner { margin: 0 0 .75rem; padding: .8rem 1rem; }
	h2 { margin: 0 0 .5rem; font-size: 1rem; }
	ul { list-style: none; padding: 0; margin: 0; display: grid; gap: .5rem; }
	li { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: .5rem; }
	span { overflow-wrap: anywhere; }
	p { margin: 0 0 .5rem; }
</style>
