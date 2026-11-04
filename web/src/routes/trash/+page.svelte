<script lang="ts">
	import { listItems, restoreItem, type Item } from '#lib/api/client.ts';
	import ItemRow from '#lib/ItemRow.svelte';

	let items = $state<Item[] | null>(null);

	async function load() {
		const { data } = await listItems({ query: { trashed: true, limit: 200 } });
		items = data ?? [];
	}

	$effect(() => {
		load();
	});

	async function restore(id: string) {
		await restoreItem({ path: { item_id: id } });
		await load();
	}
</script>

<h1>Trash</h1>
{#if items?.length === 0}
	<p class="muted">The trash is empty.</p>
{/if}
<ul>
	{#each items ?? [] as item (item.id)}
		<div class="row">
			<div class="grow"><ItemRow {item} /></div>
			<button onclick={() => restore(item.id)}>Restore</button>
		</div>
	{/each}
</ul>

<style>
	ul {
		padding: 0;
	}
	.grow {
		flex: 1;
		min-width: 0;
	}
</style>
