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
	import { Alert, AlertDescription } from '#lib/components/ui/alert/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Card, CardContent, CardHeader, CardTitle } from '#lib/components/ui/card/index.ts';
	import * as Table from '#lib/components/ui/table/index.ts';

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
<div class="mx-auto grid w-[min(56rem,100%)] gap-4 [&_:is(h1,h2,h3,p,dl,ul)]:m-0">
	<h1 class="text-2xl font-semibold">{t('usage.title')}</h1>
	<p class="text-muted-foreground">{t('usage.intro')}</p>

	<div class="flex flex-wrap gap-2" role="group" aria-label={t('usage.period')}>
		{#each USAGE_PERIODS as days (days)}
			<Button type="button" variant={period === days ? 'default' : 'outline'} aria-pressed={period === days} disabled={loading} onclick={() => load(days)}>
				{t(`usage.period.${days}`)}
			</Button>
		{/each}
	</div>

	{#if failed}
		<Alert variant="destructive">
			<AlertDescription class="text-foreground">{t('common.error')}</AlertDescription>
		</Alert>
	{/if}

	<Card class="min-w-0" role="region" aria-labelledby="totals-title" aria-busy={loading}>
		<CardHeader>
			<CardTitle><h2 id="totals-title" class="text-lg font-semibold">{t('usage.totals')}</h2></CardTitle>
		</CardHeader>
		<CardContent>
			{#if loading && !usage}
				<p>{t('common.loading')}</p>
			{:else if usage}
				<dl class="m-0 grid grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-3">
					{#each USAGE_METRICS as metric (metric)}
						<div class="glass-inset grid gap-1 rounded-lg p-3.5">
							<dt class="text-sm text-muted-foreground">{t(`usage.metric.${metric}`)}</dt>
							<dd class="m-0 text-2xl font-semibold tabular-nums">{formatAmount(locale, metric, usage.totals[metric])}</dd>
						</div>
					{/each}
				</dl>
			{/if}
		</CardContent>
	</Card>

	{#if usage}
		<Card class="min-w-0" role="region" aria-labelledby="daily-title">
			<CardHeader>
				<CardTitle><h2 id="daily-title" class="text-lg font-semibold">{t('usage.daily')}</h2></CardTitle>
			</CardHeader>
			<CardContent class="gap-4">
				{#if isEmptyUsage(usage)}
					<p>{t('usage.empty')}</p>
				{:else}
					<Table.Root>
						<Table.Header>
							<Table.Row>
								<Table.Head scope="col" class="text-muted-foreground">{t('usage.day')}</Table.Head>
								{#each USAGE_METRICS as metric (metric)}
									<Table.Head scope="col" class="text-right text-muted-foreground tabular-nums">{t(`usage.metric.${metric}`)}</Table.Head>
								{/each}
							</Table.Row>
						</Table.Header>
						<Table.Body>
							{#each usage.daily as day (day.day)}
								<Table.Row>
									<Table.Head scope="row" class="font-normal">{formatDay(locale, day.day)}</Table.Head>
									{#each USAGE_METRICS as metric (metric)}
										<Table.Cell class="text-right tabular-nums">{formatAmount(locale, metric, day[metric])}</Table.Cell>
									{/each}
								</Table.Row>
							{/each}
						</Table.Body>
					</Table.Root>
				{/if}
				<p class="text-sm text-muted-foreground">{t('usage.note')}</p>
			</CardContent>
		</Card>
	{/if}
</div>
