<script lang="ts">
	import { onMount } from 'svelte';
	import { dismissReminder, getActiveReminders, mergeReminders, parseReminderPayload } from '#lib/api/reminders.ts';
	import type { Reminder } from '#lib/api/tasks.ts';
	import { getT } from '#lib/i18n/context.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Card } from '#lib/components/ui/card/index.ts';

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
	<Card class="mb-3 gap-2 px-4 py-3" role="status" aria-live="polite" aria-label={t('reminders.title')}>
		{#if error}<p>{t('reminders.error')}</p>{/if}
		{#if active.length > 0}
			<h2 class="m-0 text-base font-bold">{t('reminders.title')}</h2>
			<ul class="m-0 grid list-none gap-2 p-0">
				{#each active as reminder (reminder.id)}
					<li class="flex flex-wrap items-center justify-between gap-2"><span class="[overflow-wrap:anywhere]">{reminder.task_title}</span><Button variant="outline" onclick={() => dismiss(reminder.id)}>{t('reminders.dismiss')}</Button></li>
				{/each}
			</ul>
		{/if}
	</Card>
{/if}
