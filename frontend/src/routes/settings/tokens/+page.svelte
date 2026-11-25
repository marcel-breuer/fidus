<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import {
		createToken,
		DEFAULT_EXPIRY_DAYS,
		getOAuthGrants,
		getTokens,
		isExpired,
		MAX_EXPIRY_DAYS,
		mcpEndpoint,
		revokeToken,
		revokeOAuthGrant,
		TOKEN_SCOPES,
		TokenLimitError,
		type ApiToken,
		type CreatedToken,
		type OAuthGrant,
		type TokenScope
	} from '#lib/api/tokens.ts';
	import { formatDate } from '#lib/i18n/index.ts';
	import { getT } from '#lib/i18n/context.ts';
	import { Alert, AlertDescription } from '#lib/components/ui/alert/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Card, CardContent, CardHeader, CardTitle } from '#lib/components/ui/card/index.ts';
	import { Checkbox } from '#lib/components/ui/checkbox/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { Label } from '#lib/components/ui/label/index.ts';

	const t = getT();
	let tokens = $state<ApiToken[]>([]);
	let grants = $state<OAuthGrant[]>([]);
	let created = $state<CreatedToken | null>(null);
	let name = $state('');
	let expiresInDays = $state(String(DEFAULT_EXPIRY_DAYS));
	let selected = $state<TokenScope[]>([]);
	let loading = $state(true);
	let busyId = $state('');
	let errorKey = $state<'common.error' | 'tokens.limit' | 'tokens.scopeRequired' | null>(null);
	let copied = $state(false);
	function toggleScope(scope: TokenScope, checked: boolean) {
		selected = checked ? [...selected, scope] : selected.filter((item) => item !== scope);
	}
	const fmt = (value: string) => formatDate(page.data.locale, new Date(value));

	onMount(async () => {
		try {
			[tokens, grants] = await Promise.all([getTokens(), getOAuthGrants()]);
		} catch {
			errorKey = 'common.error';
		} finally {
			loading = false;
		}
	});

	async function addToken(event: SubmitEvent) {
		event.preventDefault();
		errorKey = null;
		if (selected.length === 0) {
			errorKey = 'tokens.scopeRequired';
			return;
		}
		busyId = 'create';
		created = null;
		copied = false;
		try {
			created = await createToken(name.trim(), selected, Number(expiresInDays));
			tokens = [created, ...tokens];
			name = '';
			selected = [];
			expiresInDays = String(DEFAULT_EXPIRY_DAYS);
		} catch (error) {
			errorKey = error instanceof TokenLimitError ? 'tokens.limit' : 'common.error';
		} finally {
			busyId = '';
		}
	}

	async function removeGrant(grant: OAuthGrant) {
		if (!confirm(t('oauth.grants.revokeConfirm', { name: grant.client_name }))) return;
		busyId = grant.id;
		errorKey = null;
		try {
			await revokeOAuthGrant(grant.id);
			grants = grants.filter((item) => item.id !== grant.id);
		} catch {
			errorKey = 'common.error';
		} finally {
			busyId = '';
		}
	}

	async function removeToken(token: ApiToken) {
		if (!confirm(t('tokens.revokeConfirm', { name: token.name }))) return;
		busyId = token.id;
		errorKey = null;
		try {
			await revokeToken(token.id);
			tokens = tokens.filter((item) => item.id !== token.id);
			if (created?.id === token.id) created = null;
		} catch {
			errorKey = 'common.error';
		} finally {
			busyId = '';
		}
	}

	async function copySecret() {
		if (!created) return;
		try {
			await navigator.clipboard.writeText(created.token);
			copied = true;
		} catch {
			errorKey = 'common.error';
		}
	}
</script>

<svelte:head><title>{t('tokens.title')} · {t('app.name')}</title></svelte:head>
<div class="mx-auto grid w-[min(56rem,100%)] gap-4 [&_:is(h1,h2,h3,p,dl,ul)]:m-0">
	<h1 class="text-2xl font-semibold">{t('tokens.title')}</h1>
	<p class="text-muted-foreground">{t('tokens.intro')}</p>
	{#if errorKey}
		<Alert variant="destructive">
			<AlertDescription class="text-foreground">{t(errorKey)}</AlertDescription>
		</Alert>
	{/if}

	<Card class="min-w-0" role="region" aria-labelledby="create-title">
		<CardHeader>
			<CardTitle><h2 id="create-title" class="text-lg font-semibold">{t('tokens.create.title')}</h2></CardTitle>
		</CardHeader>
		<CardContent class="gap-4">
			<form class="grid grid-cols-1 items-end gap-3 min-[521px]:grid-cols-[minmax(0,1fr)_minmax(8rem,12rem)]" onsubmit={addToken}>
				<div class="grid gap-1.5">
					<Label for="token-name" class="font-semibold">{t('tokens.name')}</Label>
					<Input id="token-name" required maxlength={100} bind:value={name} />
				</div>
				<div class="grid gap-1.5">
					<Label for="token-expiry" class="font-semibold">{t('tokens.expiry')}</Label>
					<Input id="token-expiry" type="number" min="1" max={String(MAX_EXPIRY_DAYS)} required bind:value={expiresInDays} />
				</div>
				<fieldset class="col-span-full m-0 grid gap-1 border-0 p-0">
					<legend class="mb-1.5 p-0 text-sm font-semibold">{t('tokens.scopes')}</legend>
					{#each TOKEN_SCOPES as scope (scope)}
						<div class="flex min-h-11 items-center gap-2.5">
							<Checkbox id="token-scope-{scope}" checked={selected.includes(scope)} onCheckedChange={(checked) => toggleScope(scope, checked)} />
							<Label for="token-scope-{scope}" class="min-h-11 flex-1 font-normal">{t(`tokens.scope.${scope}`)}</Label>
						</div>
					{/each}
				</fieldset>
				<div class="col-span-full">
					<Button type="submit" disabled={busyId === 'create'}>{t('tokens.create')}</Button>
				</div>
			</form>
			{#if created}
				<div class="glass-inset grid gap-2.5 rounded-lg p-3.5" role="status">
					<p>{t('tokens.created')}</p>
					<div class="flex min-w-0 flex-wrap items-center gap-2.5">
						<code class="text-sm [overflow-wrap:anywhere]">{created.token}</code>
						<Button type="button" variant="outline" onclick={copySecret}>{copied ? t('tokens.copied') : t('tokens.copy')}</Button>
						<Button type="button" variant="outline" onclick={() => (created = null)}>{t('tokens.done')}</Button>
					</div>
					<p>{t('tokens.endpoint')}: <code class="text-sm [overflow-wrap:anywhere]">{mcpEndpoint(page.url.origin)}</code></p>
				</div>
			{/if}
		</CardContent>
	</Card>

	<Card class="min-w-0" role="region" aria-labelledby="active-title">
		<CardHeader>
			<CardTitle><h2 id="active-title" class="text-lg font-semibold">{t('tokens.active')}</h2></CardTitle>
		</CardHeader>
		<CardContent class="gap-4">
			{#if loading}
				<p>{t('common.loading')}</p>
			{:else if tokens.length === 0}
				<p>{t('tokens.empty')}</p>
			{:else}
				<ul class="m-0 grid list-none gap-3 p-0">
					{#each tokens as token (token.id)}
						<li class="flex flex-col items-start justify-between gap-4 min-[521px]:flex-row">
							<div class="grid min-w-0 gap-0.5">
								<strong>{token.name}</strong>
								<span class="text-sm text-muted-foreground [overflow-wrap:anywhere]">{token.token_prefix}…</span>
								<span class="text-sm text-muted-foreground [overflow-wrap:anywhere]">{token.scopes.map((scope) => t(`tokens.scope.${scope}`)).join(', ')}</span>
								<span class="text-sm text-muted-foreground [overflow-wrap:anywhere]">{isExpired(token)
									? t('tokens.expired', { date: fmt(token.expires_at) })
									: t('tokens.expires', { date: fmt(token.expires_at) })}
								·
								{token.last_used_at ? t('tokens.lastUsed', { date: fmt(token.last_used_at) }) : t('tokens.neverUsed')}</span>
							</div>
							<Button type="button" variant="outline" disabled={busyId === token.id} onclick={() => removeToken(token)}>{t('tokens.revoke')}</Button>
						</li>
					{/each}
				</ul>
			{/if}
		</CardContent>
	</Card>

	<Card class="min-w-0" role="region" aria-labelledby="oauth-grants-title">
		<CardHeader>
			<CardTitle><h2 id="oauth-grants-title" class="text-lg font-semibold">{t('oauth.grants.title')}</h2></CardTitle>
		</CardHeader>
		<CardContent class="gap-4">
			{#if loading}
				<p>{t('common.loading')}</p>
			{:else if grants.length === 0}
				<p>{t('oauth.grants.empty')}</p>
			{:else}
				<ul class="m-0 grid list-none gap-3 p-0">
					{#each grants as grant (grant.id)}
						<li class="flex flex-col items-start justify-between gap-4 min-[521px]:flex-row">
							<div class="grid min-w-0 gap-0.5">
								<strong>{grant.client_name}</strong>
								<span class="text-sm text-muted-foreground [overflow-wrap:anywhere]">{grant.resource}</span>
								<span class="text-sm text-muted-foreground [overflow-wrap:anywhere]">{grant.scopes.map((scope) => t(`tokens.scope.${scope}`)).join(', ')}</span>
								<span class="text-sm text-muted-foreground [overflow-wrap:anywhere]">{t('oauth.grants.expires', { date: fmt(grant.expires_at) })}</span>
							</div>
							<Button type="button" variant="outline" disabled={busyId === grant.id} onclick={() => removeGrant(grant)}>{t('tokens.revoke')}</Button>
						</li>
					{/each}
				</ul>
			{/if}
		</CardContent>
	</Card>
</div>
