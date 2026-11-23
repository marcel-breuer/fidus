<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import {
		createToken,
		DEFAULT_EXPIRY_DAYS,
		getTokens,
		isExpired,
		MAX_EXPIRY_DAYS,
		mcpEndpoint,
		revokeToken,
		TOKEN_SCOPES,
		TokenLimitError,
		type ApiToken,
		type CreatedToken,
		type TokenScope
	} from '$lib/api/tokens';
	import { formatDate } from '$lib/i18n';
	import { getT } from '$lib/i18n/context';
	import { Alert, Button, TextField } from '$lib/ui';

	const t = getT();
	let tokens = $state<ApiToken[]>([]);
	let created = $state<CreatedToken | null>(null);
	let name = $state('');
	let expiresInDays = $state(String(DEFAULT_EXPIRY_DAYS));
	let selected = $state<TokenScope[]>([]);
	let loading = $state(true);
	let busyId = $state('');
	let errorKey = $state<'common.error' | 'tokens.limit' | 'tokens.scopeRequired' | null>(null);
	let copied = $state(false);
	const fmt = (value: string) => formatDate(page.data.locale, new Date(value));

	onMount(async () => {
		try {
			tokens = await getTokens();
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
<div class="tokens-page">
	<h1>{t('tokens.title')}</h1>
	<p class="intro">{t('tokens.intro')}</p>
	{#if errorKey}
		<Alert>{t(errorKey)}</Alert>
	{/if}

	<section class="glass-panel section" aria-labelledby="create-title">
		<h2 id="create-title">{t('tokens.create.title')}</h2>
		<form class="create-form" onsubmit={addToken}>
			<TextField label={t('tokens.name')} required maxlength={100} bind:value={name} />
			<TextField
				label={t('tokens.expiry')}
				type="number"
				min="1"
				max={String(MAX_EXPIRY_DAYS)}
				required
				bind:value={expiresInDays}
			/>
			<fieldset>
				<legend>{t('tokens.scopes')}</legend>
				{#each TOKEN_SCOPES as scope (scope)}
					<label class="scope">
						<input type="checkbox" value={scope} bind:group={selected} />
						<span>{t(`tokens.scope.${scope}`)}</span>
					</label>
				{/each}
			</fieldset>
			<div class="submit">
				<Button type="submit" disabled={busyId === 'create'}>{t('tokens.create')}</Button>
			</div>
		</form>
		{#if created}
			<div class="secret" role="status">
				<p>{t('tokens.created')}</p>
				<div class="secret-row">
					<code>{created.token}</code>
					<Button variant="quiet" onclick={copySecret}>{copied ? t('tokens.copied') : t('tokens.copy')}</Button>
					<Button variant="quiet" onclick={() => (created = null)}>{t('tokens.done')}</Button>
				</div>
				<p class="endpoint">{t('tokens.endpoint')}: <code>{mcpEndpoint(page.url.origin)}</code></p>
			</div>
		{/if}
	</section>

	<section class="glass-panel section" aria-labelledby="active-title">
		<h2 id="active-title">{t('tokens.active')}</h2>
		{#if loading}
			<p>{t('common.loading')}</p>
		{:else if tokens.length === 0}
			<p>{t('tokens.empty')}</p>
		{:else}
			<ul class="token-list">
				{#each tokens as token (token.id)}
					<li>
						<div class="meta">
							<strong>{token.name}</strong>
							<span class="prefix">{token.token_prefix}…</span>
							<span class="scopes">{token.scopes.map((scope) => t(`tokens.scope.${scope}`)).join(', ')}</span>
							<span class="dates">
								{isExpired(token)
									? t('tokens.expired', { date: fmt(token.expires_at) })
									: t('tokens.expires', { date: fmt(token.expires_at) })}
								·
								{token.last_used_at ? t('tokens.lastUsed', { date: fmt(token.last_used_at) }) : t('tokens.neverUsed')}
							</span>
						</div>
						<Button variant="quiet" disabled={busyId === token.id} onclick={() => removeToken(token)}>{t('tokens.revoke')}</Button>
					</li>
				{/each}
			</ul>
		{/if}
	</section>
</div>

<style>
	.tokens-page { display: grid; gap: 1rem; width: min(56rem, 100%); margin: 0 auto; }
	.tokens-page h1, h2 { margin: 0; }
	h2 { font-size: 1.1rem; }
	.intro { margin: 0; color: var(--muted); }
	.section { display: grid; gap: 1rem; padding: 1.25rem; min-width: 0; }
	.create-form { display: grid; grid-template-columns: minmax(0, 1fr) minmax(8rem, 12rem); gap: 0.75rem; align-items: end; }
	fieldset { grid-column: 1 / -1; display: grid; gap: 0.4rem; margin: 0; padding: 0; border: 0; }
	legend { font-size: 0.875rem; font-weight: 600; padding: 0; margin-bottom: 0.35rem; }
	.scope { display: flex; align-items: center; gap: 0.55rem; }
	.scope input { width: 1.1rem; height: 1.1rem; accent-color: var(--accent-text); }
	.submit { grid-column: 1 / -1; }
	.secret { display: grid; gap: 0.6rem; padding: 0.9rem; border: 1px solid var(--line); border-radius: 0.625rem; background: var(--glass-inset-fill); }
	.secret p { margin: 0; }
	.secret-row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem; min-width: 0; }
	code { overflow-wrap: anywhere; font-size: 0.85rem; }
	.token-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.75rem; }
	.token-list li { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
	.meta { display: grid; gap: 0.15rem; min-width: 0; }
	.prefix, .scopes, .dates { font-size: 0.85rem; color: var(--muted); overflow-wrap: anywhere; }
	@media (max-width: 520px) {
		.create-form { grid-template-columns: 1fr; }
		.token-list li { flex-direction: column; }
	}
</style>
