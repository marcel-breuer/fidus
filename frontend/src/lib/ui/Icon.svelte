<script lang="ts">
	import type { Component } from 'svelte';
	import FolderIcon from '@lucide/svelte/icons/folder';
	import ListChecksIcon from '@lucide/svelte/icons/list-checks';
	import MessageSquareIcon from '@lucide/svelte/icons/message-square';
	import MicIcon from '@lucide/svelte/icons/mic';
	import MinusIcon from '@lucide/svelte/icons/minus';

	// Module icon names come from the API; unknown names fall back to a neutral mark.
	const icons: Record<string, Component> = {
		chat: MessageSquareIcon,
		files: FolderIcon,
		tasks: ListChecksIcon,
		audio: MicIcon
	};
	let { name }: { name: string } = $props();
	const Glyph = $derived(icons[name] ?? MinusIcon);
</script>

<Glyph aria-hidden="true" />
