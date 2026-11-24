<script lang="ts">
	import type { ModuleEntry } from '#lib/api/types.ts';
	import type { MessageKey } from '#lib/i18n/index.ts';
	import { getT } from '#lib/i18n/context.ts';
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
	<a class="extra-link" href="/settings/tokens" aria-current={current === '/settings/tokens' ? 'page' : undefined}>
		<span>{t('nav.tokens')}</span>
	</a>
	<a class="extra-link" href="/settings/usage" aria-current={current === '/settings/usage' ? 'page' : undefined}>
		<span>{t('nav.usage')}</span>
	</a>
	{#if admin}
		<a class="extra-link" href="/admin" aria-current={current === '/admin' ? 'page' : undefined}>
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
		min-height: 44px;
		padding: 0.55rem 0.7rem;
		border-radius: 0.625rem;
		color: var(--ink);
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
	.extra-link {
		display: flex;
		align-items: center;
		gap: 0.65rem;
		min-height: 44px;
		padding: 0.55rem 0.7rem;
		border-radius: 0.625rem;
		color: var(--ink);
		text-decoration: none;
	}
	.extra-link:hover { background: var(--hover); }
	.extra-link[aria-current='page'] { background: var(--accent); color: var(--accent-ink); }
	@media (max-width: 720px) {
		nav { display: flex; flex-wrap: wrap; gap: 0.25rem; }
		ul { display: grid; flex: 1 1 100%; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.25rem; }
		li { min-width: 0; }
		a { white-space: nowrap; }
		.extra-link { display: inline-flex; flex: 0 0 auto; }
	}
</style>
