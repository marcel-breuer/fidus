<script lang="ts">
	import type { Locale } from '#lib/i18n/index.ts';
	import { provideT } from '#lib/i18n/context.ts';
	import Page from './+page.svelte';

	let { locale }: { locale: Locale } = $props();
	provideT(() => locale);
</script>

<Page />
