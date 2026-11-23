<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import {
		buildInviteLink,
		createInvitation,
		getAdminModules,
		getInvitations,
		revokeInvitation,
		setModuleEnabled,
		type AdminInvitation,
		type AdminModule,
		type CreatedInvitation
	} from '$lib/api/admin';
	import { formatDate } from '$lib/i18n';
	import type { MessageKey } from '$lib/i18n';
	import { getT } from '$lib/i18n/context';
	import { Alert, Button, TextField } from '$lib/ui';

	const t = getT();
	let modules = $state<AdminModule[]>([]);
	let invitations = $state<AdminInvitation[]>([]);
	let created = $state<CreatedInvitation | null>(null);
	let expiresInDays = $state('7');
	let loading = $state(true);
	let busyKey = $state('');
	let errorMessage = $state(false);
	let copied = $state(false);
	const inviteLink = $derived(
		created ? buildInviteLink(page.url.origin, created.token) : ''
	);

	onMount(async () => {
		try {
			[modules, invitations] = await Promise.all([getAdminModules(), getInvitations()]);
		} catch {
			errorMessage = true;
		} finally {
			loading = false;
		}
	});

	async function toggleModule(module: AdminModule, enabled: boolean) {
		busyKey = module.key;
		errorMessage = false;
		try {
			const updated = await setModuleEnabled(module.key, enabled);
			modules = modules.map((item) => (item.key === updated.key ? updated : item));
		} catch {
			errorMessage = true;
		} finally {
			busyKey = '';
		}
	}

	async function addInvitation(event: SubmitEvent) {
		event.preventDefault();
		busyKey = 'create';
		errorMessage = false;
		created = null;
		try {
			created = await createInvitation(Number(expiresInDays));
			invitations = [created, ...invitations];
		} catch {
			errorMessage = true;
		} finally {
			busyKey = '';
		}
	}

	async function removeInvitation(invitation: AdminInvitation) {
		busyKey = invitation.id;
		errorMessage = false;
		try {
			await revokeInvitation(invitation.id);
			invitations = invitations.filter((item) => item.id !== invitation.id);
		} catch {
			errorMessage = true;
		} finally {
			busyKey = '';
		}
	}

	async function copyInviteLink() {
		try {
			await navigator.clipboard.writeText(inviteLink);
			copied = true;
		} catch {
			errorMessage = true;
		}
	}
</script>

<svelte:head><title>{t('admin.title')} · {t('app.name')}</title></svelte:head>
<div class="admin-page">
	<h1>{t('admin.title')}</h1>
	{#if errorMessage}
		<Alert>{t('common.error')}</Alert>
	{/if}
	<section class="glass-panel section" aria-labelledby="modules-title">
		<h2 id="modules-title">{t('admin.modules.title')}</h2>
		{#if loading}
			<p>{t('common.loading')}</p>
		{:else if modules.length === 0}
			<p>{t('admin.modules.empty')}</p>
		{:else}
			<ul class="module-list">
				{#each modules as module (module.key)}
					<li>
						<label for="module-{module.key}">{t(module.name_key as MessageKey)}</label>
						<input
							id="module-{module.key}"
							type="checkbox"
							checked={module.enabled}
							disabled={busyKey === module.key}
							aria-label={t('admin.modules.toggle', { module: t(module.name_key as MessageKey) })}
							onchange={(event) => toggleModule(module, event.currentTarget.checked)}
						/>
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<section class="glass-panel section" aria-labelledby="invitations-title">
		<h2 id="invitations-title">{t('admin.invitations.title')}</h2>
		<form class="create-form" onsubmit={addInvitation}>
			<TextField label={t('admin.invitations.expiry')} type="number" min="1" max="30" required bind:value={expiresInDays} />
			<Button type="submit" disabled={busyKey === 'create'}>{t('admin.invitations.create')}</Button>
		</form>
		{#if created}
			<div class="invite-result" aria-live="polite">
				<p>{t('admin.invitations.created')}</p>
				<div class="link-row">
					<a href={inviteLink}>{inviteLink}</a>
					<Button variant="quiet" onclick={copyInviteLink}>{copied ? t('admin.invitations.copied') : t('admin.invitations.copy')}</Button>
				</div>
			</div>
		{/if}
		<h3>{t('admin.invitations.active')}</h3>
		{#if loading}
			<p>{t('common.loading')}</p>
		{:else if invitations.length === 0}
			<p>{t('admin.invitations.empty')}</p>
		{:else}
			<ul class="invitation-list">
				{#each invitations as invitation (invitation.id)}
					<li>
						<span>{t('admin.invitations.expires', { date: formatDate(page.data.locale, new Date(invitation.expires_at)) })}</span>
						<Button variant="quiet" disabled={busyKey === invitation.id} onclick={() => removeInvitation(invitation)}>{t('admin.invitations.revoke')}</Button>
					</li>
				{/each}
			</ul>
		{/if}
	</section>
</div>

<style>
	.admin-page { display: grid; gap: 1rem; width: min(56rem, 100%); margin: 0 auto; }
	.admin-page h1, h2, h3 { margin: 0; }
	h2 { font-size: 1.1rem; }
	h3 { font-size: 0.95rem; margin-top: 1rem; }
	.section { display: grid; gap: 1rem; padding: 1.25rem; min-width: 0; }
	.module-list, .invitation-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.5rem; }
	.module-list li, .invitation-list li { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
	.module-list input { width: 1.2rem; height: 1.2rem; accent-color: var(--accent-text); }
	.create-form { display: grid; grid-template-columns: minmax(8rem, 12rem) auto; align-items: end; justify-content: start; gap: 0.75rem; }
	.invite-result { display: grid; gap: 0.5rem; }
	.invite-result p { margin: 0; }
	.link-row { display: flex; align-items: center; flex-wrap: wrap; gap: 0.75rem; min-width: 0; }
	.link-row a { overflow-wrap: anywhere; }
	@media (max-width: 520px) {
		.create-form { grid-template-columns: 1fr; }
		.invitation-list li { align-items: flex-start; }
	}
</style>
