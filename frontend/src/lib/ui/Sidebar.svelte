<script lang="ts">
	import type { ModuleEntry } from '$lib/api/types';
	import type { MessageKey } from '$lib/i18n';
	import { getT } from '$lib/i18n/context';
	import Icon from './Icon.svelte';

	let { modules, current = '', admin = false }: { modules: ModuleEntry[]; current?: string; admin?: boolean } = $props();
	const t = getT();
</script>

<nav aria-label={t('nav.primary')}>
	{#if modules.length === 0}
		<p class="empty">{t('nav.empty')}</p>
	{:else}
		<ul>
			{#each modules as module (module.key)}
				<li>
					<a
						href={module.route}
						aria-current={current === module.route ? 'page' : undefined}
						data-module={module.key}
					>
						<Icon name={module.icon} />
						<span>{t(module.name_key as MessageKey)}</span>
					</a>
				</li>
			{/each}
		</ul>
	{/if}
	{#if admin}
		<a class="admin-link" href="/admin" aria-current={current === '/admin' ? 'page' : undefined}>
			<span>{t('nav.admin')}</span>
		</a>
	{/if}
</nav>

<style>
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 2px;
	}
	a {
		display: flex;
		align-items: center;
		gap: 0.65rem;
		padding: 0.55rem 0.7rem;
		border-radius: 0.625rem;
		color: inherit;
		text-decoration: none;
		transition:
			color 180ms ease-out,
			background-color 180ms ease-out;
	}
	a:hover {
		background: var(--hover);
	}
	a[aria-current='page'] {
		background: var(--accent);
		color: var(--accent-ink);
	}
	.empty {
		color: var(--muted);
		font-size: 0.9rem;
		padding: 0 0.7rem;
	}
	.admin-link {
		display: flex;
		align-items: center;
		gap: 0.65rem;
		padding: 0.55rem 0.7rem;
		border-radius: 0.625rem;
		color: inherit;
		text-decoration: none;
	}
	.admin-link:hover { background: var(--hover); }
	.admin-link[aria-current='page'] { background: var(--accent); color: var(--accent-ink); }
</style>
