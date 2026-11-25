<script lang="ts">
	import type { ModuleEntry } from '#lib/api/types.ts';
	import type { MessageKey } from '#lib/i18n/index.ts';
	import { getT } from '#lib/i18n/context.ts';
	import * as Sidebar from '#lib/components/ui/sidebar/index.ts';
	import Icon from './Icon.svelte';

	let { modules, current = '', admin = false }: { modules: ModuleEntry[]; current?: string; admin?: boolean } = $props();
	const t = getT();
	const extra = $derived([
		{ href: '/settings/tokens', label: t('nav.tokens') },
		{ href: '/settings/usage', label: t('nav.usage') },
		...(admin ? [{ href: '/admin', label: t('nav.admin') }] : [])
	]);
</script>

<nav aria-label={t('nav.primary')}>
	{#if modules.length === 0}
		<p class="px-3 text-sm text-muted-foreground">{t('nav.empty')}</p>
	{:else}
		<Sidebar.Menu>
			{#each modules as module (module.key)}
				<Sidebar.MenuItem>
					<Sidebar.MenuButton isActive={current === module.route}>
						{#snippet child({ props })}
							<a
								{...props}
								href={module.route}
								aria-current={current === module.route ? 'page' : undefined}
								data-module={module.key}
							>
								<Icon name={module.icon} />
								<span>{t(module.name_key as MessageKey)}</span>
							</a>
						{/snippet}
					</Sidebar.MenuButton>
				</Sidebar.MenuItem>
			{/each}
		</Sidebar.Menu>
	{/if}
	<Sidebar.Menu class="mt-1">
		{#each extra as link (link.href)}
			<Sidebar.MenuItem>
				<Sidebar.MenuButton isActive={current === link.href}>
					{#snippet child({ props })}
						<a {...props} href={link.href} aria-current={current === link.href ? 'page' : undefined}>
							<span>{link.label}</span>
						</a>
					{/snippet}
				</Sidebar.MenuButton>
			</Sidebar.MenuItem>
		{/each}
	</Sidebar.Menu>
</nav>
