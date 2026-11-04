<script lang="ts">
	import { resolve } from '$app/paths';
	import type { Item } from '#lib/api/client.ts';

	let { item }: { item: Item } = $props();

	const authors = $derived(
		item.authors.length > 3
			? `${item.authors.slice(0, 3).join('; ')} et al.`
			: item.authors.join('; ')
	);
</script>

<li>
	<a href={resolve('/items/[id]', { id: item.id })}>{item.title}</a>
	<div class="muted">
		{authors}{#if authors && (item.year || item.container_title)}
			·
		{/if}{item.year ?? ''}
		{#if item.container_title}<em>{item.container_title}</em>{/if}
		<span class="badge">{item.type}</span>
	</div>
</li>

<style>
	li {
		padding: 10px 0;
		border-bottom: 1px solid var(--border);
		list-style: none;
	}
	a {
		font-weight: 600;
		text-decoration: none;
	}
</style>
