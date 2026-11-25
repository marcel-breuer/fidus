<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.ts';
	import * as Dialog from '#lib/components/ui/dialog/index.ts';

	/** Confirmation step for destructive actions; every string comes from the i18n layer. */
	let {
		open,
		title,
		description,
		confirmLabel,
		cancelLabel,
		onconfirm,
		oncancel
	}: {
		open: boolean;
		title: string;
		description: string;
		confirmLabel: string;
		cancelLabel: string;
		onconfirm: () => void;
		oncancel: () => void;
	} = $props();
</script>

<Dialog.Root {open} onOpenChange={(next) => { if (!next) oncancel(); }}>
	<Dialog.Content closeLabel={cancelLabel}>
		<Dialog.Header>
			<Dialog.Title>{title}</Dialog.Title>
			<Dialog.Description>{description}</Dialog.Description>
		</Dialog.Header>
		<Dialog.Footer>
			<Button type="button" variant="outline" onclick={oncancel}>{cancelLabel}</Button>
			<Button type="button" variant="destructive" onclick={onconfirm}>{confirmLabel}</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
