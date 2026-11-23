<script lang="ts">
	import type { HTMLInputAttributes } from 'svelte/elements';

	let {
		label,
		value = $bindable(''),
		...rest
	}: { label: string; value?: string } & HTMLInputAttributes = $props();
	const id = $props.id();
</script>

<div class="field">
	<label for={id}>{label}</label>
	<input class="glass-control" {id} bind:value {...rest} />
</div>

<style>
	.field {
		display: grid;
		gap: 0.35rem;
	}
	label {
		font-size: 0.875rem;
		font-weight: 600;
	}
	input {
		font: inherit;
		padding: 0.6rem 0.7rem;
	}
</style>
