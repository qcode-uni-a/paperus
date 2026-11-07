<script lang="ts">
	import { listItems, unarchiveItem, type Item } from '#lib/api/client.ts';
	import ItemRow from '#lib/ItemRow.svelte';
	import { libraryById } from '#lib/organize.svelte.ts';
	import { keepPlace } from '#lib/keepPlace.svelte.ts';

	const PAGE = 100;
	let items = $state<Item[] | null>(null);
	let total = $state(0);

	async function load(before?: string) {
		const { data, response } = await listItems({
			query: { archived: true, limit: PAGE, before }
		});
		total = Number(response?.headers.get('X-Total-Count') ?? 0);
		items = before ? [...(items ?? []), ...(data ?? [])] : (data ?? []);
	}

	$effect(() => {
		load();
	});

	keepPlace(
		'archive',
		() => items?.length ?? 0,
		async (count) => {
			await load();
			let shown = 0;
			while (items && items.length > shown && items.length < Math.min(count, total)) {
				shown = items.length;
				await load(items.at(-1)?.id);
			}
		}
	);

	async function takeOut(id: string) {
		await unarchiveItem({ path: { item_id: id } });
		items = items?.filter((item) => item.id !== id) ?? null;
		total -= 1;
	}
</script>

<svelte:head><title>Archive · paperus</title></svelte:head>

<h1>Archive</h1>
{#if items?.length === 0}
	<p class="muted">
		The archive is empty. Papers you archive (in a paper's menu) are kept here, left out of the
		library, search and Manage; search can include them again.
	</p>
{:else if items}
	<p class="muted">
		{total}
		{total === 1 ? 'paper' : 'papers'}, kept but left out of the library and search.
	</p>
{/if}
<ul>
	{#each items ?? [] as item (item.id)}
		<ItemRow {item}>
			{#snippet actions()}
				{#if libraryById(item.library_id)?.writable}
					<button onclick={() => takeOut(item.id)}>Take out</button>
				{/if}
			{/snippet}
		</ItemRow>
	{/each}
</ul>
{#if items && items.length < total}
	<button class="more" onclick={() => load(items?.at(-1)?.id)}>Show more</button>
{/if}

<style>
	h1 {
		margin: 0 0 8px;
	}
	ul {
		margin: 0;
		padding: 0;
	}
	.more {
		margin-top: 12px;
	}
</style>
