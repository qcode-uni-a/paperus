<script lang="ts">
	import { listItems, type Item } from '#lib/api/client.ts';
	import ItemRow from '#lib/ItemRow.svelte';

	let items = $state<Item[] | null>(null);

	$effect(() => {
		listItems({ query: { favourite: true, limit: 200 } }).then(({ data }) => {
			items = data ?? [];
		});
	});
</script>

<svelte:head><title>Favourites · paperus</title></svelte:head>

<h1>Favourites</h1>
{#if items?.length === 0}
	<p class="muted">
		No favourites yet. Star a paper (☆ next to its title) to find it here quickly; only you see your
		stars.
	</p>
{/if}
<ul>
	{#each items ?? [] as item (item.id)}<ItemRow {item} />{/each}
</ul>

<style>
	h1 {
		margin: 0 0 8px;
	}
	ul {
		margin: 0;
		padding: 0;
	}
</style>
