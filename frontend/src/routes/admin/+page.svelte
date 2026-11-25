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
	import { Alert, AlertDescription } from '#lib/components/ui/alert/index.ts';
	import { Badge } from '#lib/components/ui/badge/index.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Card, CardContent, CardHeader, CardTitle } from '#lib/components/ui/card/index.ts';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { Label } from '#lib/components/ui/label/index.ts';
	import * as Select from '#lib/components/ui/select/index.ts';
	import { Switch } from '#lib/components/ui/switch/index.ts';

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
<div class="mx-auto grid w-[min(56rem,100%)] gap-4 [&_:is(h1,h2,h3,p,dl,ul)]:m-0">
	<h1 class="text-2xl font-semibold">{t('admin.title')}</h1>
	{#if errorMessage}
		<Alert variant="destructive">
			<AlertDescription class="text-foreground">{t('common.error')}</AlertDescription>
		</Alert>
		<div><Button type="button" variant="outline" onclick={load}>{t('common.retry')}</Button></div>
	{/if}

	<Card class="min-w-0" role="region" aria-labelledby="registration-title">
		<CardHeader>
			<CardTitle><h2 id="registration-title" class="text-lg font-semibold">{t('admin.registration.title')}</h2></CardTitle>
		</CardHeader>
		<CardContent class="gap-4">
			<p class="text-sm text-muted-foreground">{t('admin.registration.description')}</p>
			{#if loading}
				<p>{t('common.loading')}</p>
			{:else if registration}
				<div class="grid grid-cols-[repeat(auto-fit,minmax(11rem,1fr))] gap-3" role="radiogroup" aria-labelledby="registration-title">
					{#each REGISTRATION_MODES as mode (mode)}
						<label class="glass-control grid cursor-pointer grid-cols-[auto_1fr] items-center gap-x-2.5 gap-y-0.5 p-3 {registration.mode === mode ? 'border-primary' : ''}">
							<input
								class="row-span-2 accent-primary"
								type="radio"
								name="registration-mode"
								value={mode}
								checked={registration.mode === mode}
								disabled={busyKey === 'registration'}
								onchange={() => chooseMode(mode)}
							/>
							<span class="font-semibold">{t(`admin.registration.mode.${mode}`)}</span>
							<span class="col-start-2 text-sm text-muted-foreground">{t(`admin.registration.mode.${mode}.hint`)}</span>
						</label>
					{/each}
				</div>
				<p class="text-sm text-muted-foreground">{t('admin.registration.default', { mode: t(`admin.registration.mode.${registration.default}`) })}</p>
				<p class="text-sm text-muted-foreground" role="status">{registrationSaved ? t('admin.registration.saved') : ''}</p>
			{/if}
		</CardContent>
	</Card>

	<Card class="min-w-0" role="region" aria-labelledby="users-title">
		<CardHeader>
			<CardTitle><h2 id="users-title" class="text-lg font-semibold">{t('admin.users.title')}</h2></CardTitle>
		</CardHeader>
		<CardContent class="gap-4">
			<form class="flex flex-wrap items-end gap-3" onsubmit={searchUsers}>
				<div class="grid flex-[1_1_14rem] gap-1.5">
					<Label for="user-search" class="font-semibold">{t('admin.users.search')}</Label>
					<Input id="user-search" type="search" bind:value={userQuery} />
				</div>
				<Button type="submit" disabled={busyKey === 'users'}>{t('admin.users.searchSubmit')}</Button>
			</form>
			{#if userError}
				<Alert variant="destructive">
					<AlertDescription class="text-foreground">{t(userError)}</AlertDescription>
				</Alert>
			{/if}
			{#if loading}
				<p>{t('common.loading')}</p>
			{:else if users.length === 0}
				<p>{t('admin.users.empty')}</p>
			{:else}
				<ul class="m-0 grid list-none gap-2 p-0">
					{#each users as user (user.id)}
						{@const isSelf = user.id === page.data.user?.id}
						<li class="glass-inset flex flex-col items-stretch justify-between gap-3 rounded-2xl p-3 min-[521px]:flex-row min-[521px]:flex-wrap min-[521px]:items-center">
							<div class="grid min-w-0 gap-1">
								<span class="font-semibold [overflow-wrap:anywhere] {user.is_active ? '' : 'text-muted-foreground'}">{user.email}</span>
								<span class="flex gap-1.5">
									{#if isSelf}<Badge variant="outline">{t('admin.users.you')}</Badge>{/if}
									<Badge variant="outline" class={user.is_active ? '' : 'text-muted-foreground'}>
										{user.is_active ? t('admin.users.status.active') : t('admin.users.status.inactive')}
									</Badge>
								</span>
							</div>
							<div class="flex items-center gap-2">
								<!-- A refused change keeps the stored role: the getter always reads it back. -->
								<Select.Root
									type="single"
									bind:value={() => user.role, (role) => void changeUser(user, { role: role as AdminUser['role'] })}
									disabled={busyKey === user.id || isSelf}
								>
									<Select.Trigger aria-label={t('admin.users.role', { email: user.email })}>
										{t(`admin.users.role.${user.role}`)}
									</Select.Trigger>
									<Select.Content>
										<Select.Item value="admin" label={t('admin.users.role.admin')} />
										<Select.Item value="member" label={t('admin.users.role.member')} />
									</Select.Content>
								</Select.Root>
								<Button
									type="button"
									variant="outline"
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
				<div><Button type="button" variant="outline" disabled={busyKey === 'users'} onclick={nextUsers}>{t('admin.users.next')}</Button></div>
			{/if}
		</CardContent>
	</Card>

	<Card class="min-w-0" role="region" aria-labelledby="audit-title">
		<CardHeader>
			<CardTitle><h2 id="audit-title" class="text-lg font-semibold">{t('admin.audit.title')}</h2></CardTitle>
		</CardHeader>
		<CardContent class="gap-4">
			{#if loading}
				<p>{t('common.loading')}</p>
			{:else if auditEntries.length === 0}
				<p>{t('admin.audit.empty')}</p>
			{:else}
				<ul class="m-0 grid list-none gap-2 p-0">
					{#each auditEntries as entry (entry.id)}
						<li class="glass-inset grid min-w-0 gap-1.5 rounded-2xl p-3 [&>div]:flex [&>div]:flex-wrap [&>div]:items-baseline [&>div]:justify-between [&>div]:gap-x-4 [&>div]:gap-y-2 [&_span]:text-muted-foreground [&_span]:[overflow-wrap:anywhere] [&_time]:text-muted-foreground [&_time]:[overflow-wrap:anywhere]">
							<div><strong>{entry.action}</strong><span>{t('admin.audit.actor', { actor: entry.actor, user: entry.user_id })}</span></div>
							<div><span>{t('admin.audit.target', { type: entry.target_type, id: entry.target_id ?? t('admin.audit.noTarget') })}</span><time datetime={entry.created_at}>{formatDate(page.data.locale, new Date(entry.created_at))}</time></div>
						</li>
					{/each}
				</ul>
			{/if}
			{#if !loading && auditCursor}
				<div><Button type="button" variant="outline" disabled={busyKey === 'audit'} onclick={nextAudit}>{t('admin.audit.next')}</Button></div>
			{/if}
		</CardContent>
	</Card>

	<Card class="min-w-0" role="region" aria-labelledby="modules-title">
		<CardHeader>
			<CardTitle><h2 id="modules-title" class="text-lg font-semibold">{t('admin.modules.title')}</h2></CardTitle>
		</CardHeader>
		<CardContent class="gap-4">
			{#if loading}
				<p>{t('common.loading')}</p>
			{:else if modules.length === 0}
				<p>{t('admin.modules.empty')}</p>
			{:else}
				<ul class="m-0 grid list-none gap-2 p-0">
					{#each modules as module (module.key)}
						<li class="flex min-h-11 items-center justify-between gap-4">
							<Label for="module-{module.key}" class="min-h-11 flex-1 text-sm font-normal">{t(module.name_key as MessageKey)}</Label>
							<Switch
								id="module-{module.key}"
								checked={module.enabled}
								disabled={busyKey === module.key}
								aria-label={t('admin.modules.toggle', { module: t(module.name_key as MessageKey) })}
								onCheckedChange={(checked) => toggleModule(module, checked)}
							/>
						</li>
					{/each}
				</ul>
			{/if}
		</CardContent>
	</Card>

	<Card class="min-w-0" role="region" aria-labelledby="invitations-title">
		<CardHeader>
			<CardTitle><h2 id="invitations-title" class="text-lg font-semibold">{t('admin.invitations.title')}</h2></CardTitle>
		</CardHeader>
		<CardContent class="gap-4">
			<form class="grid grid-cols-1 items-end justify-start gap-3 min-[521px]:grid-cols-[minmax(8rem,12rem)_auto]" onsubmit={addInvitation}>
				<div class="grid gap-1.5">
					<Label for="invite-expiry" class="font-semibold">{t('admin.invitations.expiry')}</Label>
					<Input id="invite-expiry" type="number" min="1" max="30" required bind:value={expiresInDays} />
				</div>
				<Button type="submit" disabled={busyKey === 'create'}>{t('admin.invitations.create')}</Button>
			</form>
			{#if created}
				<div class="grid gap-2" aria-live="polite">
					<p>{t('admin.invitations.created')}</p>
					<div class="flex min-w-0 flex-wrap items-center gap-3">
						<a class="[overflow-wrap:anywhere]" href={inviteLink}>{inviteLink}</a>
						<Button type="button" variant="outline" onclick={copyInviteLink}>{copied ? t('admin.invitations.copied') : t('admin.invitations.copy')}</Button>
					</div>
				</div>
			{/if}
			<h3 class="mt-4 text-[0.95rem] font-semibold">{t('admin.invitations.active')}</h3>
			{#if loading}
				<p>{t('common.loading')}</p>
			{:else if invitations.length === 0}
				<p>{t('admin.invitations.empty')}</p>
			{:else}
				<ul class="m-0 grid list-none gap-2 p-0">
					{#each invitations as invitation (invitation.id)}
						<li class="flex items-start justify-between gap-4 min-[521px]:items-center">
							<span>{t('admin.invitations.expires', { date: formatDate(page.data.locale, new Date(invitation.expires_at)) })}</span>
							<Button type="button" variant="outline" disabled={busyKey === invitation.id} onclick={() => removeInvitation(invitation)}>{t('admin.invitations.revoke')}</Button>
						</li>
					{/each}
				</ul>
			{/if}
		</CardContent>
	</Card>
</div>
