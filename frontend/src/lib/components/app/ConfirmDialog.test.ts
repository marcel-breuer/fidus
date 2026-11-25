import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import { LOCALES, messages, type MessageKey } from '#lib/i18n/index.ts';
import ConfirmDialog from './ConfirmDialog.svelte';

const confirmKeys: MessageKey[] = [
	'common.cancel',
	'chat.delete',
	'chat.confirmDelete',
	'audio.delete',
	'audio.deleteConfirm',
	'memory.delete',
	'memory.confirmDelete',
	'tokens.revoke',
	'tokens.revokeConfirm',
	'oauth.grants.revokeConfirm',
	'admin.users.deactivate',
	'admin.users.confirmDeactivate',
	'files.delete',
	'files.deleteConfirm'
];

const sources = import.meta.glob<string>(['/src/**/*.svelte', '/src/**/*.ts', '!/src/**/*.test.ts'], {
	query: '?raw',
	import: 'default',
	eager: true
});

describe('ConfirmDialog', () => {
	it('renders nothing while closed', () => {
		const body = render(ConfirmDialog, {
			props: { open: false, title: 'T', description: 'D', confirmLabel: 'Yes', cancelLabel: 'No', onconfirm: () => {}, oncancel: () => {} }
		}).body;
		expect(body).not.toContain('role="dialog"');
		expect(body).not.toContain('>D<');
	});

	it('has German and English copy for every confirmation', () => {
		for (const locale of LOCALES) {
			for (const key of confirmKeys) expect(messages[locale][key], `${locale} ${key}`).toBeTruthy();
		}
	});

	it('leaves no native confirm() prompt in the app', () => {
		const offenders = Object.entries(sources).filter(([, code]) => /(?<![\w.])(window\.)?confirm\(/.test(code)).map(([file]) => file);
		expect(Object.keys(sources).length).toBeGreaterThan(20);
		expect(offenders).toEqual([]);
	});
});
