<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { login, register, type AuthError } from '$lib/api/client';
	import { getT } from '$lib/i18n/context';
	import { Alert, Button, TextField } from '$lib/ui';

	const t = getT();
	const errorKeys = {
		credentials: 'auth.login.error.credentials',
		rateLimited: 'auth.login.error.rateLimited',
		unknown: 'common.error',
		exists: 'common.error',
		closed: 'common.error',
		invalid: 'common.error'
	} as const;
	let email = $state('');
	let password = $state('');
	let error = $state<AuthError | null>(null);
	let busy = $state(false);

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		busy = true;
		error = await login(email, password);
		busy = false;
		if (!error) {
			const returnTo = new URL(page.url.searchParams.get('returnTo') ?? '/', page.url.origin);
			await goto(
				returnTo.origin === page.url.origin
					? `${returnTo.pathname}${returnTo.search}${returnTo.hash}`
					: '/',
				{ invalidateAll: true }
			);
		}
	}
</script>

<svelte:head><title>{t('auth.login.title')} · {t('app.name')}</title></svelte:head>
<main class="auth">
	<form class="glass-panel" onsubmit={submit}>
		<h1>{t('auth.login.title')}</h1>
		{#if error}
			<Alert>{t(errorKeys[error])}</Alert>
		{/if}
		<TextField label={t('auth.email')} type="email" autocomplete="email" required bind:value={email} />
		<TextField label={t('auth.password')} type="password" autocomplete="current-password" required bind:value={password} />
		<Button type="submit" disabled={busy}>{busy ? t('auth.login.submitting') : t('auth.login.submit')}</Button>
		<a href="/register">{t('auth.login.toRegister')}</a>
	</form>
</main>

<style>
	.auth {
		min-height: 100vh;
		display: grid;
		place-items: center;
		padding: 1rem;
	}
	form {
		width: min(24rem, 100%);
		display: grid;
		gap: 1rem;
		padding: 1.75rem;
	}
</style>
