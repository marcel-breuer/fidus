<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLButtonAttributes } from 'svelte/elements';

	let {
		variant = 'primary',
		children,
		...rest
	}: { variant?: 'primary' | 'quiet'; children: Snippet } & HTMLButtonAttributes = $props();
</script>

<button class="btn {variant}" {...rest}>{@render children()}</button>

<style>
	.btn {
		font: inherit;
		font-weight: 600;
		border-radius: 6px;
		padding: 0.6rem 1rem;
		border: 1px solid transparent;
		cursor: pointer;
	}
	.primary {
		background: var(--accent);
		color: var(--accent-ink);
	}
	.quiet {
		background: transparent;
		color: var(--ink);
		border-color: var(--line);
	}
	.btn:disabled {
		opacity: 0.6;
		cursor: progress;
	}
</style>
