<script lang="ts">
	import { goto } from '$app/navigation';
	import { login, register, type AuthError } from '$lib/api/client';
	import { getT } from '$lib/i18n/context';
	import { Alert, Button, TextField } from '$lib/ui';

	const t = getT();
	const errorKeys = {
		exists: 'auth.register.error.exists',
		closed: 'auth.register.error.closed',
		invalid: 'auth.register.error.invalid',
		rateLimited: 'auth.register.error.rateLimited',
		credentials: 'common.error',
		unknown: 'common.error'
	} as const;
	let email = $state('');
	let password = $state('');
	let error = $state<AuthError | null>(null);
	let busy = $state(false);

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		busy = true;
		error = (await register(email, password)) ?? (await login(email, password));
		busy = false;
		if (!error) await goto('/', { invalidateAll: true });
	}
</script>

<svelte:head><title>{t('auth.register.title')} · {t('app.name')}</title></svelte:head>
<main class="auth">
	<form onsubmit={submit}>
		<h1>{t('auth.register.title')}</h1>
		{#if error}
			<Alert>{t(errorKeys[error])}</Alert>
		{/if}
		<TextField label={t('auth.email')} type="email" autocomplete="email" required bind:value={email} />
		<TextField label={t('auth.password')} type="password" autocomplete="new-password" required bind:value={password} />
		<Button type="submit" disabled={busy}>{busy ? t('auth.register.submitting') : t('auth.register.submit')}</Button>
		<a href="/login">{t('auth.register.toLogin')}</a>
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
	}
	a {
		color: var(--accent);
	}
</style>
