<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { listAgentAudit, type AgentAuditEntry } from '#lib/api/agent.ts';
	import { formatDate } from '#lib/i18n/index.ts';
	import { getT } from '#lib/i18n/context.ts';
	import { Alert, Button } from '#lib/ui/index.ts';

	const t = getT();
	let entries = $state<AgentAuditEntry[]>([]);
	let loading = $state(true);
	let failed = $state(false);
	const locale = $derived(page.data.locale as 'en' | 'de');

	async function load() {
		loading = true;
		failed = false;
		try {
			entries = await listAgentAudit();
		} catch {
			failed = true;
		} finally {
			loading = false;
		}
	}

	onMount(load);
</script>

<svelte:head><title>{t('chat.audit.title')} · {t('app.name')}</title></svelte:head>
<div class="audit-page">
	<h1>{t('chat.audit.title')}</h1>
	<p class="hint">{t('chat.audit.intro')}</p>
	{#if failed}
		<Alert>{t('chat.audit.error')}</Alert>
		<Button variant="quiet" onclick={load}>{t('common.retry')}</Button>
	{:else if loading}
		<p aria-live="polite">{t('common.loading')}</p>
	{:else if entries.length === 0}
		<p class="glass-panel empty">{t('chat.audit.empty')}</p>
	{:else}
		<ul class="entries">
			{#each entries as entry (entry.id)}
				<li class="glass-panel entry">
					<div>
						<strong>{entry.action}</strong>
						<p>{t('chat.audit.target', { type: entry.target_type, id: entry.target_id ?? t('chat.audit.noTarget') })}</p>
					</div>
					<time datetime={entry.created_at}>{formatDate(locale, new Date(entry.created_at))}</time>
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.audit-page { display: grid; gap: 1rem; width: min(56rem, 100%); margin: 0 auto; }
	.audit-page h1, .audit-page p { margin: 0; }
	.hint { color: var(--muted); }
	.empty { padding: 1rem; }
	.entries { display: grid; gap: 0.65rem; list-style: none; margin: 0; padding: 0; }
	.entry { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.75rem; padding: 0.9rem 1rem; }
	.entry p { color: var(--muted); margin-top: 0.25rem; overflow-wrap: anywhere; }
	.entry time { color: var(--muted); font-size: 0.875rem; }
</style>
