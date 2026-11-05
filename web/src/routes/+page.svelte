<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import { listItems, search, type Item, type Passage } from '#lib/api/client.ts';
	import AddItem from '#lib/AddItem.svelte';
	import ItemRow from '#lib/ItemRow.svelte';
	import { uploads } from '#lib/uploads.svelte.ts';

	const PAGE = 50;

	let items = $state<Item[]>([]);
	let more = $state(false);
	// The search lives in the address (?q=…), so Back and links keep it.
	const searched = $derived(page.url.searchParams.get('q')?.trim() ?? '');
	let query = $state(page.url.searchParams.get('q') ?? '');
	let passages = $state<Passage[] | null>(null);

	/** Passages grouped by item, items in the order of their best passage. */
	const groups = $derived.by(() => {
		const byItem = new Map<string, { id: string; title: string; passages: Passage[] }>();
		for (const passage of passages ?? []) {
			const group = byItem.get(passage.item_id) ?? {
				id: passage.item_id,
				title: passage.item_title,
				passages: []
			};
			group.passages.push(passage);
			byItem.set(passage.item_id, group);
		}
		return [...byItem.values()];
	});
	let adding = $state(false);

	async function loadItems(before?: string) {
		const { data } = await listItems({ query: { limit: PAGE, before } });
		if (!data) return;
		items = before ? [...items, ...data] : data;
		more = data.length === PAGE;
	}

	$effect(() => {
		loadItems();
	});

	// Address → field, e.g. after Back.
	$effect(() => {
		const q = searched;
		if (untrack(() => query.trim()) !== q) query = q;
	});

	// Field → address, a moment after the last key. Starting a search adds a
	// history entry (Back returns to the list); refining it replaces it.
	$effect(() => {
		const q = query.trim();
		const timer = setTimeout(() => {
			if (q === untrack(() => searched)) return;
			const url = q ? `${resolve('/')}?q=${encodeURIComponent(q)}` : resolve('/');
			goto(url, {
				replace: Boolean(untrack(() => searched)) && Boolean(q),
				reset: false
			});
		}, 250);
		return () => clearTimeout(timer);
	});

	// Results for the searched words.
	$effect(() => {
		const q = searched;
		if (!q) {
			passages = null;
			return;
		}
		search({ query: { q } }).then(({ data }) => {
			if (q === untrack(() => searched)) passages = data ?? [];
		});
	});

	function clearSearch() {
		query = '';
		goto(resolve('/'), { reset: false });
	}

	// While the server reads new files, refresh to show their real titles.
	$effect(() => {
		if (!items.some((item) => item.processing)) return;
		const timer = setInterval(() => loadItems(), 2000);
		return () => clearInterval(timer);
	});

	// Reload when uploads (dropped anywhere, or picked below) finish.
	$effect(() => {
		if (uploads.finished) loadItems();
	});
</script>

<div class="library">
	<div class="search">
		<svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true">
			<circle cx="10.5" cy="10.5" r="6.5" />
			<path d="m15.5 15.5 5 5" />
		</svg>
		<input
			type="search"
			bind:value={query}
			placeholder="Search by words or meaning"
			aria-label="Search the library"
			onkeydown={(event) => {
				if (event.key === 'Escape') clearSearch();
			}}
		/>
	</div>

	<div class="actions row">
		<button class="quiet" onclick={() => (adding = !adding)} aria-expanded={adding}>
			{adding ? 'Close' : 'Add by DOI or details'}
		</button>
	</div>

	{#if adding}<AddItem />{/if}

	{#if searched}
		<div class="results-head row">
			<h1 class="count">
				{passages === null
					? 'Searching…'
					: `${groups.length} ${groups.length === 1 ? 'item' : 'items'} for “${searched}”`}
			</h1>
			<button class="quiet" onclick={clearSearch}>Clear search</button>
		</div>
	{/if}

	{#if passages !== null}
		{#if passages.length === 0}
			<p class="muted">Nothing found for “{query}”.</p>
		{:else}
			<ul class="results">
				{#each groups as group (group.id)}
					<li>
						<a class="source" href={resolve('/items/[id]', { id: group.id })}>{group.title}</a>
						<ul class="passages">
							{#each group.passages as passage (passage.passage_id)}
								<li>
									<a
										class="where"
										href="{resolve('/items/[id]', { id: passage.item_id })}{passage.page
											? `?page=${passage.page}`
											: ''}"
									>
										{passage.page ? `Page ${passage.page}` : 'Open'}
									</a>
									{#if !passage.matched.includes('keyword')}
										<span class="badge">Similar meaning</span>
									{/if}
									<!-- Snippets are HTML-escaped on the server; only <mark> is added. -->
									<blockquote>{@html passage.snippet}</blockquote>
								</li>
							{/each}
						</ul>
					</li>
				{/each}
			</ul>
		{/if}
	{:else if items.length === 0}
		<div class="empty">
			<h2>Nothing in the library yet</h2>
			<p class="muted">
				Drop PDFs anywhere in this window. paperus reads them, finds their title and authors, and
				makes the full text searchable.
			</p>
		</div>
	{:else}
		<h1 class="count">{items.length}{more ? '+' : ''} items</h1>
		<ul class="items">
			{#each items as item (item.id)}<ItemRow {item} />{/each}
		</ul>
		{#if more}
			<div><button onclick={() => loadItems(items.at(-1)?.id)}>Show more</button></div>
		{/if}
	{/if}
</div>

<style>
	.library {
		display: grid;
		gap: 20px;
	}
	.search {
		position: relative;
	}
	.search input {
		font-size: var(--step-1);
		padding: 12px 14px 12px 46px;
		border-radius: 10px;
		border-color: var(--rule);
		background: var(--surface);
	}
	.search-icon {
		position: absolute;
		left: 15px;
		top: 50%;
		width: 20px;
		height: 20px;
		transform: translateY(-50%);
		fill: none;
		stroke: var(--muted);
		stroke-width: 2;
		stroke-linecap: round;
		pointer-events: none;
	}
	.actions {
		margin: -12px 0 0 -8px;
	}
	.results-head {
		justify-content: space-between;
		margin: 8px 0 -12px;
	}
	.results-head .count {
		margin: 0;
	}
	.quiet {
		border-color: transparent;
		background: none;
		color: var(--royal);
		padding: 4px 8px;
	}
	.quiet:hover:not(:disabled) {
		background: var(--rail);
		border-color: transparent;
	}
	.count {
		font-size: var(--step-0);
		font-family: var(--sans);
		font-weight: 600;
		color: var(--muted);
		margin: 8px 0 -12px;
		letter-spacing: 0;
	}
	ul {
		margin: 0;
		padding: 0;
	}
	.results > li {
		list-style: none;
		padding: 18px 0 20px;
		border-bottom: 1px solid var(--rule);
		display: grid;
		gap: 10px;
	}
	.source {
		font-family: var(--serif);
		font-weight: 600;
		font-size: var(--step-1);
		line-height: 1.3;
		color: var(--ink);
		text-decoration: none;
		max-width: 70ch;
	}
	.source:hover {
		color: var(--royal);
		text-decoration: underline;
	}
	.passages {
		display: grid;
		gap: 12px;
	}
	.passages li {
		list-style: none;
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 4px 12px;
		align-items: baseline;
		padding-left: 12px;
		border-left: 2px solid var(--rule);
	}
	.where {
		font-size: var(--step--1);
		font-weight: 600;
		white-space: nowrap;
	}
	.passages .badge {
		justify-self: start;
	}
	.passages blockquote {
		grid-column: 1 / -1;
	}
	blockquote {
		margin: 0;
		font-family: var(--serif);
		font-size: var(--step-0);
		line-height: 1.65;
		max-width: 72ch;
		color: var(--ink);
	}
	.empty {
		padding: 48px 0;
		max-width: 52ch;
	}
	.empty h2 {
		font-size: var(--step-2);
		margin: 0 0 8px;
	}
</style>
