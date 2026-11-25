<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Button as ShadButton, type ButtonProps } from '#lib/components/ui/button/index.ts';

	// Compatibility wrapper for routes that have not moved to the shadcn Button yet.
	// The native default (type="submit") is kept so existing forms still submit.
	let {
		variant = 'primary',
		type = 'submit',
		children,
		...rest
	}: { variant?: 'primary' | 'quiet'; children: Snippet } & Omit<ButtonProps, 'variant' | 'children'> = $props();
</script>

<ShadButton variant={variant === 'quiet' ? 'outline' : 'default'} {type} {...rest}>{@render children()}</ShadButton>
