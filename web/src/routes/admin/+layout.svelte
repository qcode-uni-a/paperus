<script lang="ts">
	import { loadAdmin } from '#lib/admin/data.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import type { LayoutProps } from './$types';

	// The administration menu is part of the sidebar (#lib/Sidebar.svelte).
	let { children }: LayoutProps = $props();

	$effect(() => {
		if (!session.user?.is_admin) return;
		loadAdmin();
		const timer = setInterval(loadAdmin, 3000);
		return () => clearInterval(timer);
	});
</script>

{#if !session.checked}
	<p class="muted">Loading…</p>
{:else if !session.user?.is_admin}
	<p class="muted">Only administrators can see this page.</p>
{:else}
	<div class="content">{@render children()}</div>
{/if}

<style>
	.content :global(h1) {
		margin-top: 0;
	}
</style>
