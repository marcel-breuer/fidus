<script lang="ts">
	import type { ModuleEntry } from '$lib/api/types';
	import type { Locale } from '$lib/i18n';
	import { provideT } from '$lib/i18n/context';
	import Sidebar from './Sidebar.svelte';

	let { locale, modules, current }: { locale: Locale; modules: ModuleEntry[]; current: string } = $props();
	provideT(() => locale);
</script>

<Sidebar {modules} {current} />
