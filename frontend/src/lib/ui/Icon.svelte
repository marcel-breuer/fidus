<script lang="ts">
	const paths: Record<string, string> = {
		chat: 'M4 5h16v11H9l-5 4z',
		files: 'M4 6a1 1 0 0 1 1-1h5l2 2h7a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z',
		tasks: 'M5 12l4 4 10-10',
		audio: 'M12 4a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V7a3 3 0 0 0-3-3zM6 11a6 6 0 0 0 12 0M12 17v3'
	};
	let { name }: { name: string } = $props();
</script>

<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
	<path d={paths[name] ?? 'M5 12h14'} />
</svg>
