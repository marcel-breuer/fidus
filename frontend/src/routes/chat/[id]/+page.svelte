<script lang="ts">
	import ChatShell from '../ChatShell.svelte';
	import { page } from '$app/state';
</script>

<ChatShell conversationId={page.params.id} />
