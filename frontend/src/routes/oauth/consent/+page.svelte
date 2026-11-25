<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { csrfHeaders } from '#lib/api/csrf.ts';
	import { getT } from '#lib/i18n/context.ts';
	import { Alert, AlertDescription } from '#lib/components/ui/alert/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Card, CardContent, CardHeader, CardTitle } from '#lib/components/ui/card/index.ts';

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
<main class="grid min-h-screen place-items-center p-4 [&_:is(h1,h2,h3,p,dl,ul)]:m-0">
	<Card class="w-[min(34rem,100%)]" role="region" aria-labelledby="consent-title">
		<CardHeader>
			<CardTitle><h1 id="consent-title" class="text-xl font-semibold">{t('oauth.consent.title')}</h1></CardTitle>
		</CardHeader>
		<CardContent class="grid gap-4">
			{#if loading}
				<p>{t('common.loading')}</p>
			{:else if signedOut}
				<p>{t('oauth.consent.loginRequired')}</p>
				<div><Button onclick={signIn}>{t('oauth.consent.signIn')}</Button></div>
			{:else if failed || !info}
				<Alert variant="destructive">
					<AlertDescription class="text-foreground">{t('common.error')}</AlertDescription>
				</Alert>
			{:else}
				<p>{t('oauth.consent.explanation', { client: info.client_name })}</p>
				<h2 class="text-base font-semibold">{t('oauth.consent.scopes')}</h2>
				<p class="break-words [overflow-wrap:anywhere]">{t('oauth.consent.redirect', { uri: info.redirect_uri })}</p>
				<ul class="grid list-disc gap-1.5 pl-5">
					{#each info.scopes as scope (scope)}
						<li><code>{scope}</code></li>
					{/each}
				</ul>
				<p class="text-muted-foreground">{t('oauth.consent.privateData')}</p>
				<div class="flex flex-wrap justify-end gap-2.5">
					<Button variant="outline" disabled={busy} onclick={() => decide(false)}>{t('oauth.consent.deny')}</Button>
					<Button disabled={busy} onclick={() => decide(true)}>{t('oauth.consent.approve')}</Button>
				</div>
			{/if}
		</CardContent>
	</Card>
</main>
