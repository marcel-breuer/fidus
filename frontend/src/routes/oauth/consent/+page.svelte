<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { csrfHeaders } from '$lib/api/csrf';
	import { getT } from '$lib/i18n/context';
	import { Alert, Button } from '$lib/ui';

	const t = getT();
	type ConsentInfo = { client_name: string; redirect_uri: string; scopes: string[] };
	let info = $state<ConsentInfo | null>(null);
	let loading = $state(true);
	let busy = $state(false);
	let signedOut = $state(false);
	let failed = $state(false);
	const params = $derived(page.url.searchParams);
	const values = () => new URLSearchParams({
		client_id: params.get('client_id') ?? '',
		redirect_uri: params.get('redirect_uri') ?? '',
		resource: params.get('resource') ?? '',
		scope: params.get('scope') ?? '',
		state: params.get('state') ?? '',
		code_challenge: params.get('code_challenge') ?? '',
		code_challenge_method: params.get('code_challenge_method') ?? ''
	});

	onMount(async () => {
		try {
			const response = await fetch(`/oauth/consent/details?${values()}`);
			if (response.status === 401) signedOut = true;
			else if (!response.ok) failed = true;
			else info = (await response.json()) as ConsentInfo;
		} catch {
			failed = true;
		} finally {
			loading = false;
		}
	});

	async function decide(approved: boolean) {
		busy = true;
		failed = false;
		try {
			const response = await fetch('/oauth/consent', {
				method: 'POST',
				headers: { 'content-type': 'application/json', ...csrfHeaders() },
				body: JSON.stringify({
					...Object.fromEntries(values()),
					approved
				})
			});
			if (!response.ok) throw new Error('consent failed');
			const location = response.headers.get('location');
			if (!location) throw new Error('missing redirect');
			window.location.assign(location);
		} catch {
			failed = true;
		} finally {
			busy = false;
		}
	}

	function signIn() {
		const returnTo = `${page.url.pathname}${page.url.search}`;
		goto(`/login?returnTo=${encodeURIComponent(returnTo)}`);
	}
</script>

<svelte:head><title>{t('oauth.consent.title')} · {t('app.name')}</title></svelte:head>
<main class="consent">
	<section class="glass-panel panel" aria-labelledby="consent-title">
		<h1 id="consent-title">{t('oauth.consent.title')}</h1>
		{#if loading}
			<p>{t('common.loading')}</p>
		{:else if signedOut}
			<p>{t('oauth.consent.loginRequired')}</p>
			<Button onclick={signIn}>{t('oauth.consent.signIn')}</Button>
		{:else if failed || !info}
			<Alert>{t('common.error')}</Alert>
		{:else}
			<p>{t('oauth.consent.explanation', { client: info.client_name })}</p>
			<h2>{t('oauth.consent.scopes')}</h2>
			<p class="redirect">{t('oauth.consent.redirect', { uri: info.redirect_uri })}</p>
			<ul>
				{#each info.scopes as scope (scope)}
					<li><code>{scope}</code></li>
				{/each}
			</ul>
			<p class="privacy">{t('oauth.consent.privateData')}</p>
			<div class="actions">
				<Button disabled={busy} onclick={() => decide(false)} variant="quiet">{t('oauth.consent.deny')}</Button>
				<Button disabled={busy} onclick={() => decide(true)}>{t('oauth.consent.approve')}</Button>
			</div>
		{/if}
	</section>
</main>

<style>
	.consent { min-height: 100vh; display: grid; place-items: center; padding: 1rem; }
	.panel { width: min(34rem, 100%); display: grid; gap: 1rem; padding: 1.5rem; }
	h1, h2, p { margin: 0; }
	h2 { font-size: 1rem; }
	ul { display: grid; gap: 0.4rem; margin: 0; padding-left: 1.25rem; }
	.privacy { color: var(--muted); }
	.redirect { overflow-wrap: anywhere; }
	.actions { display: flex; justify-content: end; gap: 0.6rem; flex-wrap: wrap; }
</style>
