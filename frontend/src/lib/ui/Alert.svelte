<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Alert, AlertDescription } from '#lib/components/ui/alert/index.ts';

	let { children }: { children: Snippet } = $props();
</script>

<Alert variant="destructive">
	<AlertDescription class="text-foreground">{@render children()}</AlertDescription>
</Alert>
