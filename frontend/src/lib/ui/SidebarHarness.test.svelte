<script lang="ts">
	import type { ModuleEntry } from '#lib/api/types.ts';
	import type { Locale } from '#lib/i18n/index.ts';
	import { provideT } from '#lib/i18n/context.ts';
	import * as SidebarUi from '#lib/components/ui/sidebar/index.ts';
	import Sidebar from './Sidebar.svelte';

	let { locale, modules, current, admin = false }: { locale: Locale; modules: ModuleEntry[]; current: string; admin?: boolean } = $props();
	provideT(() => locale);
</script>

<SidebarUi.Provider>
	<Sidebar {modules} {current} {admin} />
</SidebarUi.Provider>
