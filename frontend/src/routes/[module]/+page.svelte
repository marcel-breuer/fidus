<script lang="ts">
	import type { MessageKey } from '#lib/i18n/index.ts';
	import { getT } from '#lib/i18n/context.ts';

	let { data } = $props();
	const t = getT();
</script>

<svelte:head><title>{t(data.entry.name_key as MessageKey)} · {t('app.name')}</title></svelte:head>
<section class="glass-panel">
	<h1>{t(data.entry.name_key as MessageKey)}</h1>
	<p>{t('module.placeholder.body')}</p>
</section>

<style>
	section {
		padding: 1.5rem;
	}
	p {
		margin: 0;
		color: var(--muted);
	}
</style>
