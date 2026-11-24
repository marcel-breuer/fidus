<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import {
		buildInviteLink,
		createInvitation,
		getAdminAudit,
		getAdminModules,
		getAdminUsers,
		getInvitations,
		getRegistration,
		REGISTRATION_MODES,
		revokeInvitation,
		setModuleEnabled,
		setRegistrationMode,
		updateAdminUser,
		userChangeErrorKey,
		type AdminInvitation,
		type AdminModule,
		type AdminUser,
		type CreatedInvitation,
		type RegistrationMode,
		type RegistrationSetting
	} from '#lib/api/admin.ts';
	import { formatDate } from '#lib/i18n/index.ts';
	import type { MessageKey } from '#lib/i18n/index.ts';
	import { getT } from '#lib/i18n/context.ts';
	import { Alert, Button, TextField } from '#lib/ui/index.ts';

	const t = getT();
	let modules = $state<AdminModule[]>([]);
	let invitations = $state<AdminInvitation[]>([]);
	let created = $state<CreatedInvitation | null>(null);
	let expiresInDays = $state('7');
	let users = $state<AdminUser[]>([]);
	let userQuery = $state('');
	let userCursor = $state<string | null>(null);
	let auditEntries = $state<import('#lib/api/admin.ts').AdminAuditPage['items']>([]);
	let auditCursor = $state<string | null>(null);
	let registration = $state<RegistrationSetting | null>(null);
	let registrationSaved = $state(false);
	let userError = $state<MessageKey | ''>('');
	let loading = $state(true);
	let busyKey = $state('');
	let errorMessage = $state(false);
	let copied = $state(false);
	const inviteLink = $derived(
		created ? buildInviteLink(page.url.origin, created.token) : ''
	);

	async function load() {
		loading = true;
		errorMessage = false;
		try {
			const [loadedModules, loadedInvitations, loadedUsers, loadedRegistration, loadedAudit] = await Promise.all([
				getAdminModules(),
				getInvitations(),
				getAdminUsers(userQuery),
				getRegistration(),
				getAdminAudit()
			]);
			modules = loadedModules;
			invitations = loadedInvitations;
			users = loadedUsers.items;
			userCursor = loadedUsers.next_cursor;
			registration = loadedRegistration;
			auditEntries = loadedAudit.items;
			auditCursor = loadedAudit.next_cursor;
		} catch {
			errorMessage = true;
		} finally {
			loading = false;
		}
	}

	async function searchUsers(event?: SubmitEvent) {
		event?.preventDefault();
		busyKey = 'users';
		userError = '';
		try {
			const result = await getAdminUsers(userQuery.trim());
			users = result.items;
			userCursor = result.next_cursor;
		} catch {
			userError = 'common.error';
		} finally {
			busyKey = '';
		}
	}

	async function nextUsers() {
		if (!userCursor) return;
		busyKey = 'users';
		try {
			const result = await getAdminUsers(userQuery.trim(), userCursor);
			users = result.items;
			userCursor = result.next_cursor;
		} catch {
			userError = 'common.error';
		} finally {
			busyKey = '';
		}
	}

	async function nextAudit() {
		if (!auditCursor) return;
		busyKey = 'audit';
		errorMessage = false;
		try {
			const result = await getAdminAudit(auditCursor);
			auditEntries = result.items;
			auditCursor = result.next_cursor;
		} catch {
			errorMessage = true;
		} finally {
			busyKey = '';
		}
	}

	onMount(load);

	async function changeUser(
		user: AdminUser,
		change: { is_active?: boolean; role?: AdminUser['role'] }
	): Promise<boolean> {
		busyKey = user.id;
		userError = '';
		try {
			const updated = await updateAdminUser(user.id, change);
			users = users.map((item) => (item.id === updated.id ? updated : item));
			return true;
		} catch (error) {
			userError = userChangeErrorKey(error);
			return false;
		} finally {
			busyKey = '';
		}
	}

	function toggleActive(user: AdminUser) {
		if (user.is_active && !confirm(t('admin.users.confirmDeactivate', { email: user.email }))) return;
		void changeUser(user, { is_active: !user.is_active });
	}

	async function chooseMode(mode: RegistrationMode) {
		busyKey = 'registration';
		errorMessage = false;
		registrationSaved = false;
		try {
			registration = await setRegistrationMode(mode);
			registrationSaved = true;
		} catch {
			errorMessage = true;
		} finally {
			busyKey = '';
		}
	}

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
		<div><Button variant="quiet" onclick={load}>{t('common.retry')}</Button></div>
	{/if}
	<section class="glass-panel section" aria-labelledby="registration-title">
		<h2 id="registration-title">{t('admin.registration.title')}</h2>
		<p class="hint">{t('admin.registration.description')}</p>
		{#if loading}
			<p>{t('common.loading')}</p>
		{:else if registration}
			<div class="mode-group" role="radiogroup" aria-labelledby="registration-title">
				{#each REGISTRATION_MODES as mode (mode)}
					<label class="mode glass-control" class:selected={registration.mode === mode}>
						<input
							type="radio"
							name="registration-mode"
							value={mode}
							checked={registration.mode === mode}
							disabled={busyKey === 'registration'}
							onchange={() => chooseMode(mode)}
						/>
						<span class="mode-name">{t(`admin.registration.mode.${mode}`)}</span>
						<span class="hint">{t(`admin.registration.mode.${mode}.hint`)}</span>
					</label>
				{/each}
			</div>
			<p class="hint">{t('admin.registration.default', { mode: t(`admin.registration.mode.${registration.default}`) })}</p>
			<p class="hint" role="status">{registrationSaved ? t('admin.registration.saved') : ''}</p>
		{/if}
	</section>

	<section class="glass-panel section" aria-labelledby="users-title">
		<h2 id="users-title">{t('admin.users.title')}</h2>
		<form class="user-search" onsubmit={searchUsers}>
			<TextField label={t('admin.users.search')} type="search" bind:value={userQuery} />
			<Button type="submit" disabled={busyKey === 'users'}>{t('admin.users.searchSubmit')}</Button>
		</form>
		{#if userError}
			<Alert>{t(userError)}</Alert>
		{/if}
		{#if loading}
			<p>{t('common.loading')}</p>
		{:else if users.length === 0}
			<p>{t('admin.users.empty')}</p>
		{:else}
			<ul class="user-list">
				{#each users as user (user.id)}
					{@const isSelf = user.id === page.data.user?.id}
					<li class="user glass-inset" class:inactive={!user.is_active}>
						<div class="identity">
							<span class="email">{user.email}</span>
							<span class="badges">
								{#if isSelf}<span class="badge">{t('admin.users.you')}</span>{/if}
								<span class="badge" class:off={!user.is_active}>
									{user.is_active ? t('admin.users.status.active') : t('admin.users.status.inactive')}
								</span>
							</span>
						</div>
						<div class="actions">
							<select
								class="glass-control"
								aria-label={t('admin.users.role', { email: user.email })}
								value={user.role}
								disabled={busyKey === user.id || isSelf}
								onchange={async (event) => {
									const select = event.currentTarget;
									// A refused change must show the stored role again.
									if (!(await changeUser(user, { role: select.value as AdminUser['role'] }))) select.value = user.role;
								}}
							>
								<option value="admin">{t('admin.users.role.admin')}</option>
								<option value="member">{t('admin.users.role.member')}</option>
							</select>
							<Button
								variant="quiet"
								disabled={busyKey === user.id || (isSelf && user.is_active)}
								aria-label={t(user.is_active ? 'admin.users.deactivateLabel' : 'admin.users.reactivateLabel', { email: user.email })}
								onclick={() => toggleActive(user)}
							>
								{user.is_active ? t('admin.users.deactivate') : t('admin.users.reactivate')}
							</Button>
						</div>
					</li>
				{/each}
			</ul>
		{/if}
		{#if !loading && userCursor}
			<Button variant="quiet" disabled={busyKey === 'users'} onclick={nextUsers}>{t('admin.users.next')}</Button>
		{/if}
	</section>

	<section class="glass-panel section" aria-labelledby="audit-title">
		<h2 id="audit-title">{t('admin.audit.title')}</h2>
		{#if loading}
			<p>{t('common.loading')}</p>
		{:else if auditEntries.length === 0}
			<p>{t('admin.audit.empty')}</p>
		{:else}
			<ul class="audit-list">
				{#each auditEntries as entry (entry.id)}
					<li class="glass-inset">
						<div><strong>{entry.action}</strong><span>{t('admin.audit.actor', { actor: entry.actor, user: entry.user_id })}</span></div>
						<div><span>{t('admin.audit.target', { type: entry.target_type, id: entry.target_id ?? t('admin.audit.noTarget') })}</span><time datetime={entry.created_at}>{formatDate(page.data.locale, new Date(entry.created_at))}</time></div>
					</li>
				{/each}
			</ul>
		{/if}
		{#if !loading && auditCursor}
			<Button variant="quiet" disabled={busyKey === 'audit'} onclick={nextAudit}>{t('admin.audit.next')}</Button>
		{/if}
	</section>

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
	.module-list li { min-height: 44px; }
	.module-list li label { display: flex; align-items: center; flex: 1; min-height: 44px; }
	.module-list input { width: 1.2rem; height: 1.2rem; accent-color: var(--accent-text); }
	.create-form { display: grid; grid-template-columns: minmax(8rem, 12rem) auto; align-items: end; justify-content: start; gap: 0.75rem; }
	.user-search { display: flex; align-items: end; flex-wrap: wrap; gap: 0.75rem; }
	.user-search :global(.field) { flex: 1 1 14rem; }
	.audit-list { display: grid; gap: 0.5rem; list-style: none; padding: 0; margin: 0; }
	.audit-list li { display: grid; gap: 0.35rem; padding: 0.75rem; border-radius: 1rem; min-width: 0; }
	.audit-list li > div { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 0.5rem 1rem; }
	.audit-list span, .audit-list time { color: var(--muted); overflow-wrap: anywhere; }
	.invite-result { display: grid; gap: 0.5rem; }
	.invite-result p { margin: 0; }
	.link-row { display: flex; align-items: center; flex-wrap: wrap; gap: 0.75rem; min-width: 0; }
	.link-row a { overflow-wrap: anywhere; }
	.hint { margin: 0; color: var(--muted); font-size: 0.875rem; }
	.mode-group { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: 0.75rem; }
	.mode { display: grid; grid-template-columns: auto 1fr; gap: 0.15rem 0.6rem; align-items: center; padding: 0.75rem; cursor: pointer; }
	.mode.selected { border-color: var(--accent-text); }
	.mode input { grid-row: span 2; accent-color: var(--accent-text); }
	.mode-name { font-weight: 600; }
	.mode .hint { grid-column: 2; }
	.user-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.5rem; }
	.user { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.75rem; padding: 0.75rem; border-radius: 1rem; }
	.user.inactive .email { color: var(--muted); }
	.identity { display: grid; gap: 0.25rem; min-width: 0; }
	.email { overflow-wrap: anywhere; font-weight: 600; }
	.badges { display: flex; gap: 0.4rem; }
	.badge { font-size: 0.75rem; padding: 0.1rem 0.5rem; border-radius: 999px; border: 1px solid var(--glass-border); color: var(--accent-text); }
	.badge.off { color: var(--muted); }
	.actions { display: flex; align-items: center; gap: 0.5rem; }
	.actions select { font: inherit; padding: 0.5rem 0.6rem; }
	@media (max-width: 520px) {
		.user { flex-direction: column; align-items: stretch; }
		.create-form { grid-template-columns: 1fr; }
		.invitation-list li { align-items: flex-start; }
	}
</style>
