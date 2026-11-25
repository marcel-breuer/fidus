<script lang="ts">
	import type { MessageKey } from '#lib/i18n/index.ts';
	import { getT } from '#lib/i18n/context.ts';
	import { Card } from '#lib/components/ui/card/index.ts';

	let { data } = $props();
	const t = getT();
</script>

<svelte:head><title>{t(data.entry.name_key as MessageKey)} · {t('app.name')}</title></svelte:head>
<Card class="p-6">
	<h1 class="m-0">{t(data.entry.name_key as MessageKey)}</h1>
	<p class="m-0 text-muted-foreground">{t('module.placeholder.body')}</p>
</Card>
