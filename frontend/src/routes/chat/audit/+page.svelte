<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { listAgentAudit, type AgentAuditEntry } from '#lib/api/agent.ts';
	import { formatDate } from '#lib/i18n/index.ts';
	import { getT } from '#lib/i18n/context.ts';
	import { Alert, AlertDescription } from '#lib/components/ui/alert/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Card } from '#lib/components/ui/card/index.ts';

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
<div class="mx-auto grid w-[min(56rem,100%)] gap-4">
	<h1 class="m-0 text-[1.4rem] font-bold">{t('chat.audit.title')}</h1>
	<p class="m-0 text-muted-foreground">{t('chat.audit.intro')}</p>
	{#if failed}
		<Alert variant="destructive"><AlertDescription class="text-foreground">{t('chat.audit.error')}</AlertDescription></Alert>
		<Button variant="outline" onclick={load}>{t('common.retry')}</Button>
	{:else if loading}
		<p class="m-0" aria-live="polite">{t('common.loading')}</p>
	{:else if entries.length === 0}
		<Card class="p-4"><p class="m-0">{t('chat.audit.empty')}</p></Card>
	{:else}
		<ul class="m-0 grid list-none gap-2.5 p-0">
			{#each entries as entry (entry.id)}
				<li>
					<Card class="flex-row flex-wrap items-center justify-between gap-3 px-4 py-3.5">
						<div>
							<strong>{entry.action}</strong>
							<p class="mx-0 mt-1 mb-0 text-muted-foreground [overflow-wrap:anywhere]">{t('chat.audit.target', { type: entry.target_type, id: entry.target_id ?? t('chat.audit.noTarget') })}</p>
						</div>
						<time class="text-sm text-muted-foreground" datetime={entry.created_at}>{formatDate(locale, new Date(entry.created_at))}</time>
					</Card>
				</li>
			{/each}
		</ul>
	{/if}
</div>
