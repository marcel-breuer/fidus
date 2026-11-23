<script lang="ts">
	import type { MessageKey } from '$lib/i18n';
	import { getT } from '$lib/i18n/context';

	let { data } = $props();
	const t = getT();
</script>

<svelte:head><title>{t(data.entry.name_key as MessageKey)} · {t('app.name')}</title></svelte:head>
<h1>{t(data.entry.name_key as MessageKey)}</h1>
<p>{t('module.placeholder.body')}</p>
