<script lang="ts">
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { listItems, type Item } from '#lib/api/client.ts';
	import ItemRow from '#lib/ItemRow.svelte';
	import { uploads } from '#lib/uploads.svelte.ts';
	import { keepPlace } from '#lib/keepPlace.svelte.ts';
	import BulkBar from '#lib/BulkBar.svelte';
	import SelectAllBox from '#lib/SelectAllBox.svelte';
	import { NearEnd } from '#lib/nearEnd.ts';
	import { organize } from '#lib/organize.svelte.ts';
	import { Selection } from '#lib/selection.svelte.ts';
	import { isDefault, sortFromAddress, sortQuery } from '#lib/librarySort.ts';
	import SortControl from '#lib/SortControl.svelte';

	/** Items of a collection, loading more while scrolling. */
	let { collection, nested = false }: { collection: string; nested?: boolean } = $props();

	const PAGE = 50;
	// The most the server lists at once.
	const MOST = 200;
	let items = $state<Item[]>([]);
	const sort = $derived(sortFromAddress(page.url.searchParams));
	const sortKey = $derived(JSON.stringify(sortQuery(sort)));
	const selection = new Selection(() => items.map((item) => item.id));
	let total = $state<number | null>(null);
	let more = $state(false);
	let loading = false;
	let latest = 0;

	async function load(before?: string, limit = PAGE) {
		if (before && loading) return;
		const request = ++latest;
		loading = true;
		const { data, response } = await listItems({
			query: {
				limit,
				// Newest added first: after the last item; any other order: by place.
				...(isDefault(sort) ? { before } : { offset: before ? items.length : 0 }),
				collection,
				nested,
				...sortQuery(sort)
			}
		});
		if (request !== latest) return;
		loading = false;
		if (!data) return;
		items = before ? [...items, ...data] : data;
		total = Number(response?.headers.get('X-Total-Count') ?? items.length);
		more = data.length > 0 && items.length < total;
		if (before) nearEnd.again();
	}

	/** While the first rows load again: no pages added in between. */
	let refilling = false;

	/** The first ``count`` rows again (at least a page), e.g. after Back. */
	async function loadUpTo(count: number) {
		refilling = true;
		try {
			await load(undefined, Math.min(Math.max(count, PAGE), MOST));
			while (more && items.length < count) {
				await load(items.at(-1)?.id, Math.min(count - items.length, MOST));
			}
		} finally {
			refilling = false;
		}
		nearEnd.again();
	}

	keepPlace('collection', () => items.length, loadUpTo);

	$effect(() => {
		void collection;
		void nested;
		void sortKey;
		untrack(() => load());
	});

	$effect(() => {
		if (!items.some((item) => item.processing)) return;
		const timer = setInterval(() => !refilling && loadUpTo(items.length), 2000);
		return () => clearInterval(timer);
	});

	// Reload when uploads (dropped here, or added with +) finish.
	$effect(() => {
		if (uploads.finished) untrack(() => loadUpTo(items.length));
	});

	const nearEnd = new NearEnd(() => {
		if (more && !loading && !refilling) load(items.at(-1)?.id);
	});

	/** Reload, e.g. after items were added elsewhere. */
	export function refresh() {
		load();
	}
</script>

{#if total !== null}
	<div class="head">
		<div class="counted">
			<SelectAllBox {selection} {total} />
			<h2 class="count">{total.toLocaleString()} {total === 1 ? 'item' : 'items'}</h2>
		</div>
		<div class="tools">
			{#if total > 1}<SortControl />{/if}
			{#if total > 0 && !selection.active}<button
					class="select"
					onclick={() => (selection.active = true)}>Select</button
				>{/if}
		</div>
	</div>
{/if}
{#if total === 0}
	<p class="muted">No items here yet. Add them with + above, or drop files here.</p>
{/if}
<ul>
	{#each items as item (item.id)}<ItemRow {item} {selection} />{/each}
</ul>
<BulkBar
	{selection}
	{items}
	total={total ?? items.length}
	matching={{ collection, nested }}
	collection={organize.collections.find((c) => c.id === collection)}
	onchange={() => loadUpTo(items.length)}
/>
{#if more}
	<div {@attach nearEnd.attach} class="more">
		<button onclick={() => load(items.at(-1)?.id)}>Show more</button>
	</div>
{/if}

<style>
	.head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 10px 12px;
	}
	.tools {
		display: flex;
		gap: 8px;
		margin-left: auto;
	}
	.select {
		padding: 3px 12px;
	}
	/* With a mouse the rows' boxes and the list's are there; Select is for
	   phones and tablets. */
	@media (min-width: 761px) and (pointer: fine) {
		.select {
			display: none;
		}
	}
	.counted {
		position: relative;
	}
	.count {
		font-family: var(--sans);
		font-size: var(--step-0);
		font-weight: 600;
		color: var(--muted);
		margin: 0;
		letter-spacing: 0;
		white-space: nowrap;
	}
	ul {
		margin: 0;
		padding: 0;
	}
	.more {
		display: flex;
		justify-content: center;
		padding: 8px 0 24px;
	}
</style>
