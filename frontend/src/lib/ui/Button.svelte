<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLButtonAttributes } from 'svelte/elements';

	let {
		variant = 'primary',
		children,
		...rest
	}: { variant?: 'primary' | 'quiet'; children: Snippet } & HTMLButtonAttributes = $props();
</script>

<button class="btn {variant}{variant === 'quiet' ? ' glass-control' : ''}" {...rest}>{@render children()}</button>

<style>
	.btn {
		font: inherit;
		font-weight: 600;
		border-radius: 0.625rem;
		padding: 0.6rem 1rem;
		border: 1px solid var(--glass-rim);
		cursor: pointer;
		transition:
			filter 180ms ease-out,
			opacity 180ms ease-out,
			transform 180ms ease-out;
	}
	.primary {
		background: var(--accent);
		color: var(--accent-ink);
		box-shadow: inset 0 1px 0 var(--glass-edge);
	}
	.primary:hover:not(:disabled) {
		filter: brightness(1.04);
		transform: translateY(-1px);
	}
	.btn:disabled {
		opacity: 0.6;
		cursor: progress;
	}
</style>
