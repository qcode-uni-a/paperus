<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import { listItems, type Item } from '#lib/api/client.ts';
	import { ago } from '#lib/format.ts';
	import ItemRow from '#lib/ItemRow.svelte';
	import { keepPlace } from '#lib/keepPlace.svelte.ts';
	import { NearEnd } from '#lib/nearEnd.ts';

	const PAGE = 50;
	// All activity (changes by anyone, and what one opened), or only opened.
	const onlyOpened = $derived(page.url.searchParams.get('show') === 'opened');

	let items = $state<Item[]>([]);
	let total = $state<number | null>(null);
	let more = $state(false);
	let loading = false;
	let latest = 0;

	async function load(offset = 0, limit = PAGE) {
		if (offset && loading) return;
		const request = ++latest;
		loading = true;
		const { data, response } = await listItems({
			query: { sort: onlyOpened ? 'opened' : 'recent', limit, offset }
		});
		if (request !== latest) return;
		loading = false;
		if (!data) return;
		items = offset ? [...items, ...data] : data;
		total = Number(response?.headers.get('X-Total-Count') ?? items.length);
		more = data.length === limit && items.length < total;
		if (offset) nearEnd.again();
	}

	/** While the first rows load again: no pages added in between. */
	let refilling = false;

	keepPlace(
		'recent',
		() => items.length,
		async (count) => {
			refilling = true;
			try {
				await load(0, Math.min(Math.max(count, PAGE), 200));
				while (more && items.length < count) {
					await load(items.length, Math.min(count - items.length, 200));
				}
			} finally {
				refilling = false;
			}
			nearEnd.again();
		}
	);

	$effect(() => {
		void onlyOpened;
		untrack(() => load());
	});

	const nearEnd = new NearEnd(() => {
		if (more && !loading && !refilling) load(items.length);
	});

	/** Why the item is here: opened by the reader, added, or changed. */
	function note(item: Item): string {
		const opened = item.viewed_at ? new Date(item.viewed_at).getTime() : 0;
		const changed = new Date(item.changed_at).getTime();
		if (opened >= changed) return `You opened it ${ago(item.viewed_at ?? item.changed_at)}`;
		const added = Math.abs(changed - new Date(item.created_at).getTime()) < 60_000;
		return `${added ? 'Added' : 'Changed'} ${ago(item.changed_at)}`;
	}

	function show(opened: boolean) {
		goto(opened ? `${resolve('/recent')}?show=opened` : resolve('/recent'), {
			replace: true,
			reset: false
		});
	}
</script>

<svelte:head><title>Recent · paperus</title></svelte:head>

<header class="head">
	<h1>Recent</h1>
	<div class="switch" role="group" aria-label="Show">
		<button aria-pressed={!onlyOpened} onclick={() => show(false)}>All activity</button>
		<button aria-pressed={onlyOpened} onclick={() => show(true)}>Opened by me</button>
	</div>
</header>

{#if total === 0}
	<p class="muted">
		{onlyOpened ? 'You have not opened any paper yet.' : 'Nothing has happened here yet.'}
	</p>
{/if}
<ul class="items">
	{#each items as item (item.id)}<ItemRow {item} note={note(item)} />{/each}
</ul>
{#if more}
	<div {@attach nearEnd.attach} class="more">
		<button onclick={() => load(items.length)}>Show more</button>
	</div>
{/if}

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 12px;
		margin-bottom: 8px;
	}
	h1 {
		margin: 0;
	}
	.switch {
		display: inline-flex;
		padding: 3px;
		border-radius: 999px;
		background: var(--rail);
	}
	.switch button {
		padding: 5px 14px;
		border: none;
		border-radius: 999px;
		background: none;
		color: var(--muted);
		font-size: var(--step--1);
		font-weight: 600;
	}
	.switch button[aria-pressed='true'] {
		background: var(--surface);
		color: var(--ink);
		box-shadow: 0 1px 2px rgb(27 36 64 / 0.12);
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
