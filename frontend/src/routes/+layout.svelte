<script lang="ts">
	import '../app.css';
	import { goto, invalidateAll } from '$app/navigation';
	import { page } from '$app/state';
	import { logout, logoutAll } from '#lib/api/client.ts';
	import { LOCALES, LOCALE_COOKIE, type Locale } from '#lib/i18n/index.ts';
	import { getT, provideT } from '#lib/i18n/context.ts';
	import { Button } from '#lib/components/ui/button/index.ts';
	import { Label } from '#lib/components/ui/label/index.ts';
	import * as Select from '#lib/components/ui/select/index.ts';
	import * as SidebarUi from '#lib/components/ui/sidebar/index.ts';
	import { ReminderBanner, Sidebar } from '#lib/ui/index.ts';

	let { data, children } = $props();
	provideT(() => data.locale);
	const t = getT();
	const languageId = 'language-select';

	async function signOut() {
		await logout();
		await goto('/login', { invalidateAll: true });
	}

	async function signOutEverywhere() {
		await logoutAll();
		await goto('/login', { invalidateAll: true });
	}

	async function setLocale(locale: Locale) {
		document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=31536000; samesite=lax`;
		await invalidateAll();
	}
</script>

{#if data.user}
	<SidebarUi.Provider>
		<SidebarUi.Root variant="floating" title={t('app.name')} description={t('nav.primary')} closeLabel={t('nav.open')}>
			<SidebarUi.Header class="p-5 pb-0">
				<p class="mx-3 my-0 text-[1.1rem] font-bold">{t('app.name')}</p>
			</SidebarUi.Header>
			<SidebarUi.Content class="px-3.5 py-5">
				<Sidebar modules={data.modules} current={page.url.pathname} admin={data.user.role === 'admin'} />
			</SidebarUi.Content>
			<SidebarUi.Footer class="gap-2.5 p-3.5">
				<p class="m-0 text-[0.8rem] text-muted-foreground [overflow-wrap:anywhere]">{t('nav.signedInAs', { email: data.user.email })}</p>
				<div class="grid gap-1">
					<Label for={languageId} class="text-[0.8rem] font-normal">{t('nav.language')}</Label>
					<Select.Root type="single" value={data.locale} onValueChange={(value) => setLocale(value as Locale)}>
						<Select.Trigger id={languageId} class="w-full">{t(`language.${data.locale}`)}</Select.Trigger>
						<Select.Content>
							{#each LOCALES as locale}
								<Select.Item value={locale} label={t(`language.${locale}`)} />
							{/each}
						</Select.Content>
					</Select.Root>
				</div>
				<div class="grid grid-cols-2 gap-2">
					<Button variant="outline" class="h-auto whitespace-normal py-2" onclick={signOut}>{t('nav.logout')}</Button>
					<Button variant="outline" class="h-auto whitespace-normal py-2" onclick={signOutEverywhere}>{t('nav.logoutAll')}</Button>
				</div>
			</SidebarUi.Footer>
		</SidebarUi.Root>
		<div class="flex min-w-0 flex-1 flex-col">
			<header class="flex items-center gap-2 px-3 pt-3 md:hidden">
				<SidebarUi.Trigger class="size-11" aria-label={t('nav.open')} />
				<p class="m-0 font-bold">{t('app.name')}</p>
			</header>
			<main class="min-w-0 p-6 md:py-9 md:pr-9 md:pl-6">
				{#if data.modules.some((module) => module.key === 'tasks')}
					<ReminderBanner enabled={true} />
				{/if}
				{@render children()}
			</main>
		</div>
	</SidebarUi.Provider>
{:else}
	{@render children()}
{/if}
