<script lang="ts">
	import type { HTMLInputAttributes, HTMLInputTypeAttribute } from 'svelte/elements';
	import { Input } from '#lib/components/ui/input/index.ts';
	import { Label } from '#lib/components/ui/label/index.ts';

	let {
		label,
		value = $bindable(''),
		...rest
	}: { label: string; value?: string; type?: Exclude<HTMLInputTypeAttribute, 'file'> } & Omit<HTMLInputAttributes, 'type' | 'value' | 'files'> = $props();
	const id = $props.id();
</script>

<div class="grid gap-1.5">
	<Label for={id} class="font-semibold">{label}</Label>
	<Input {id} bind:value {...rest} />
</div>
