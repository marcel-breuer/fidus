<script lang="ts">
	import '../app.css';
	import { goto, invalidateAll } from '$app/navigation';
	import { page } from '$app/state';
	import { logout } from '$lib/api/client';
	import { LOCALES, LOCALE_COOKIE, type Locale } from '$lib/i18n';
	import { getT, provideT } from '$lib/i18n/context';
	import { Button, Sidebar } from '$lib/ui';

	let { data, children } = $props();
	provideT(() => data.locale);
	const t = getT();

	async function signOut() {
		await logout();
		await goto('/login', { invalidateAll: true });
	}

	async function setLocale(locale: Locale) {
		document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=31536000; samesite=lax`;
		await invalidateAll();
	}
</script>

{#if data.user}
	<div class="shell">
		<aside>
			<p class="brand">{t('app.name')}</p>
			<Sidebar modules={data.modules} current={page.url.pathname} />
			<div class="foot">
				<p class="who">{t('nav.signedInAs', { email: data.user.email })}</p>
				<label class="lang">
					<span>{t('nav.language')}</span>
					<select value={data.locale} onchange={(e) => setLocale(e.currentTarget.value as Locale)}>
						{#each LOCALES as locale}
							<option value={locale}>{t(`language.${locale}`)}</option>
						{/each}
					</select>
				</label>
				<Button variant="quiet" onclick={signOut}>{t('nav.logout')}</Button>
			</div>
		</aside>
		<main>{@render children()}</main>
	</div>
{:else}
	{@render children()}
{/if}

<style>
	.shell {
		display: grid;
		grid-template-columns: 15rem 1fr;
		min-height: 100vh;
	}
	aside {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
		padding: 1.25rem 0.9rem;
		border-right: 1px solid var(--line);
		background: var(--surface);
	}
	.brand {
		margin: 0 0.7rem;
		font-weight: 700;
		font-size: 1.1rem;
	}
	.foot {
		margin-top: auto;
		display: grid;
		gap: 0.6rem;
	}
	.who {
		margin: 0;
		font-size: 0.8rem;
		color: var(--muted);
		overflow-wrap: anywhere;
	}
	.lang {
		display: grid;
		gap: 0.25rem;
		font-size: 0.8rem;
	}
	select {
		font: inherit;
		padding: 0.35rem;
		background: var(--bg);
		color: var(--ink);
		border: 1px solid var(--line);
		border-radius: 6px;
	}
	main {
		padding: 1.5rem;
	}
	@media (max-width: 720px) {
		.shell {
			grid-template-columns: 1fr;
		}
		aside {
			border-right: 0;
			border-bottom: 1px solid var(--line);
		}
		.foot {
			margin-top: 0;
		}
	}
</style>
