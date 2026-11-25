<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { login, register, type AuthError } from '#lib/api/client.ts';
	import { getT } from '#lib/i18n/context.ts';
	import { Alert, AlertDescription } from '#lib/components/ui/alert/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Card, CardContent, CardHeader, CardTitle } from '#lib/components/ui/card/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { Label } from '#lib/components/ui/label/index.ts';

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
<main class="grid min-h-screen place-items-center p-4 [&_:is(h1,h2,h3,p,dl,ul)]:m-0">
	<Card class="w-[min(24rem,100%)]">
		<CardHeader>
			<CardTitle><h1 class="text-xl font-semibold">{t('auth.login.title')}</h1></CardTitle>
		</CardHeader>
		<CardContent>
			<form class="grid gap-4" onsubmit={submit}>
				{#if error}
					<Alert variant="destructive">
						<AlertDescription class="text-foreground">{t(errorKeys[error])}</AlertDescription>
					</Alert>
				{/if}
				<div class="grid gap-1.5">
					<Label for="email" class="font-semibold">{t('auth.email')}</Label>
					<Input id="email" type="email" autocomplete="email" required bind:value={email} />
				</div>
				<div class="grid gap-1.5">
					<Label for="password" class="font-semibold">{t('auth.password')}</Label>
					<Input id="password" type="password" autocomplete="current-password" required bind:value={password} />
				</div>
				<Button type="submit" disabled={busy}>{busy ? t('auth.login.submitting') : t('auth.login.submit')}</Button>
				<a href="/register">{t('auth.login.toRegister')}</a>
			</form>
		</CardContent>
	</Card>
</main>
