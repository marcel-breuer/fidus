<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import {
		DEFAULT_USAGE_PERIOD,
		formatAmount,
		formatDay,
		getUsage,
		isEmptyUsage,
		USAGE_METRICS,
		USAGE_PERIODS,
		type Usage,
		type UsagePeriod
	} from '#lib/api/usage.ts';
	import { getT } from '#lib/i18n/context.ts';
	import { Alert, Button } from '#lib/ui/index.ts';

	const t = getT();
	let usage = $state<Usage | null>(null);
	let period = $state<UsagePeriod>(DEFAULT_USAGE_PERIOD);
	let loading = $state(true);
	let failed = $state(false);
	const locale = $derived(page.data.locale as string);

	async function load(days: UsagePeriod) {
		period = days;
		loading = true;
		failed = false;
		try {
			usage = await getUsage(days);
		} catch {
			failed = true;
		} finally {
			loading = false;
		}
	}

	onMount(() => load(DEFAULT_USAGE_PERIOD));
</script>

<svelte:head><title>{t('usage.title')} · {t('app.name')}</title></svelte:head>
<div class="usage-page">
	<h1>{t('usage.title')}</h1>
	<p class="intro">{t('usage.intro')}</p>

	<div class="periods" role="group" aria-label={t('usage.period')}>
		{#each USAGE_PERIODS as days (days)}
			<Button variant={period === days ? 'primary' : 'quiet'} aria-pressed={period === days} disabled={loading} onclick={() => load(days)}>
				{t(`usage.period.${days}`)}
			</Button>
		{/each}
	</div>

	{#if failed}
		<Alert>{t('common.error')}</Alert>
	{/if}

	<section class="glass-panel section" aria-labelledby="totals-title" aria-busy={loading}>
		<h2 id="totals-title">{t('usage.totals')}</h2>
		{#if loading && !usage}
			<p>{t('common.loading')}</p>
		{:else if usage}
			<dl class="totals">
				{#each USAGE_METRICS as metric (metric)}
					<div class="total">
						<dt>{t(`usage.metric.${metric}`)}</dt>
						<dd>{formatAmount(locale, metric, usage.totals[metric])}</dd>
					</div>
				{/each}
			</dl>
		{/if}
	</section>

	{#if usage}
		<section class="glass-panel section" aria-labelledby="daily-title">
			<h2 id="daily-title">{t('usage.daily')}</h2>
			{#if isEmptyUsage(usage)}
				<p>{t('usage.empty')}</p>
			{:else}
				<div class="table-wrap">
					<table>
						<thead>
							<tr>
								<th scope="col">{t('usage.day')}</th>
								{#each USAGE_METRICS as metric (metric)}
									<th scope="col" class="num">{t(`usage.metric.${metric}`)}</th>
								{/each}
							</tr>
						</thead>
						<tbody>
							{#each usage.daily as day (day.day)}
								<tr>
									<th scope="row">{formatDay(locale, day.day)}</th>
									{#each USAGE_METRICS as metric (metric)}
										<td class="num">{formatAmount(locale, metric, day[metric])}</td>
									{/each}
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
			<p class="note">{t('usage.note')}</p>
		</section>
	{/if}
</div>

<style>
	.usage-page { display: grid; gap: 1rem; width: min(56rem, 100%); margin: 0 auto; }
	h1, h2 { margin: 0; }
	h2 { font-size: 1.1rem; }
	.intro, .note { margin: 0; color: var(--muted); }
	.note { font-size: 0.85rem; }
	.periods { display: flex; flex-wrap: wrap; gap: 0.5rem; }
	.section { display: grid; gap: 1rem; padding: 1.25rem; min-width: 0; }
	.totals { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: 0.75rem; margin: 0; }
	.total { display: grid; gap: 0.2rem; padding: 0.8rem 0.9rem; border: 1px solid var(--line); border-radius: 0.625rem; background: var(--glass-inset-fill); }
	dt { font-size: 0.85rem; color: var(--muted); }
	dd { margin: 0; font-size: 1.5rem; font-weight: 600; font-variant-numeric: tabular-nums; }
	.table-wrap { overflow-x: auto; }
	table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
	th, td { padding: 0.5rem 0.65rem; text-align: left; border-bottom: 1px solid var(--line); white-space: nowrap; }
	thead th { font-weight: 600; color: var(--muted); }
	tbody th { font-weight: 500; }
	.num { text-align: right; font-variant-numeric: tabular-nums; }
</style>
