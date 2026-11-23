<script lang="ts">
	import type { Snippet } from 'svelte';
	let { children }: { children: Snippet } = $props();
</script>

<p class="alert" role="alert">{@render children()}</p>

<style>
	.alert {
		margin: 0;
		padding: 0.6rem 0.8rem;
		border: 1px solid var(--danger);
		border-radius: 0.625rem;
		background: var(--danger-bg);
		color: var(--ink);
		font-size: 0.9rem;
	}
</style>
