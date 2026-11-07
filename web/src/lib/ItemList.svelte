<script lang="ts">
	import { untrack } from 'svelte';
	import { listItems, type Item } from '#lib/api/client.ts';
	import ItemRow from '#lib/ItemRow.svelte';
	import { uploads } from '#lib/uploads.svelte.ts';
	import { keepPlace } from '#lib/keepPlace.svelte.ts';

	/** Items of a collection, loading more while scrolling. */
	let { collection, nested = false }: { collection: string; nested?: boolean } = $props();

	const PAGE = 50;
	// The most the server lists at once.
	const MOST = 200;
	let items = $state<Item[]>([]);
	let total = $state<number | null>(null);
	let more = $state(false);
	let loading = false;
	let latest = 0;

	async function load(before?: string, limit = PAGE) {
		if (before && loading) return;
		const request = ++latest;
		loading = true;
		const { data, response } = await listItems({
			query: { limit, before, collection, nested }
		});
		if (request !== latest) return;
		loading = false;
		if (!data) return;
		items = before ? [...items, ...data] : data;
		total = Number(response?.headers.get('X-Total-Count') ?? items.length);
		more = data.length > 0 && items.length < total;
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
	}

	keepPlace('collection', () => items.length, loadUpTo);

	$effect(() => {
		void collection;
		void nested;
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

	function loadMoreNearby(node: HTMLElement) {
		const observer = new IntersectionObserver(
			([entry]) => {
				if (entry.isIntersecting && more && !refilling) load(items.at(-1)?.id);
			},
			{ rootMargin: '800px 0px' }
		);
		observer.observe(node);
		return () => observer.disconnect();
	}

	/** Reload, e.g. after items were added elsewhere. */
	export function refresh() {
		load();
	}
</script>

{#if total !== null}
	<h2 class="count">{total.toLocaleString()} {total === 1 ? 'item' : 'items'}</h2>
{/if}
{#if total === 0}
	<p class="muted">No items here yet. Add them with + above, or drop files here.</p>
{/if}
<ul>
	{#each items as item (item.id)}<ItemRow {item} />{/each}
</ul>
{#if more}
	<div {@attach loadMoreNearby} class="more">
		<button onclick={() => load(items.at(-1)?.id)}>Show more</button>
	</div>
{/if}

<style>
	.count {
		font-family: var(--sans);
		font-size: var(--step-0);
		font-weight: 600;
		color: var(--muted);
		margin: 0;
		letter-spacing: 0;
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
