<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import { listItems, search, type Item, type Passage } from '#lib/api/client.ts';
	import { organize } from '#lib/organize.svelte.ts';
	import ItemRow from '#lib/ItemRow.svelte';
	import SearchFilters, { type Filters } from '#lib/SearchFilters.svelte';
	import { uploads } from '#lib/uploads.svelte.ts';

	const PAGE = 50;

	let items = $state<Item[]>([]);
	let more = $state(false);
	// The search lives in the address (?q=…), so Back and links keep it.
	const searched = $derived(page.url.searchParams.get('q')?.trim() ?? '');
	let query = $state(page.url.searchParams.get('q') ?? '');
	const mode = $derived(
		(page.url.searchParams.get('mode') ?? 'hybrid') as 'hybrid' | 'keyword' | 'meaning'
	);
	const types = $derived(page.url.searchParams.getAll('type'));
	const filters = $derived<Filters>({
		words: mode !== 'meaning',
		meaning: mode !== 'keyword',
		types
	});

	/** The library address for a search with filters. */
	function searchUrl(q: string, next: Filters): string {
		const params = new URLSearchParams();
		if (q) params.set('q', q);
		if (!next.meaning) params.set('mode', 'keyword');
		else if (!next.words) params.set('mode', 'meaning');
		for (const type of next.types) params.append('type', type);
		const search = params.toString();
		return search ? `${resolve('/')}?${search}` : resolve('/');
	}

	function setFilters(next: Filters) {
		goto(searchUrl(searched, next), { replace: true, reset: false });
	}
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

	let total = $state<number | null>(null);

	// Filters from the address: ?collection=…, ?tag=… (several: all of them).
	const collectionId = $derived(page.url.searchParams.get('collection'));
	const tagIds = $derived(page.url.searchParams.getAll('tag'));
	const tagNames = $derived(
		tagIds.map((id) => organize.tags.find((t) => t.id === id)?.name ?? '…')
	);

	// Collections have their own pages; older links still work.
	$effect(() => {
		if (collectionId) {
			goto(resolve('/collections/[id]', { id: collectionId }), { replace: true });
		}
	});
	let loading = false;

	/** The first page, or with ``before`` the page after that item. */
	// Answers can arrive out of order when filters change quickly; only the
	// latest request may update the list.
	let latest = 0;

	async function loadItems(before?: string) {
		if (before && loading) return;
		const request = ++latest;
		loading = true;
		const { data, response } = await listItems({
			query: {
				limit: PAGE,
				before,
				collection: collectionId ?? undefined,
				tag: tagIds.length ? tagIds : undefined
			}
		});
		if (request !== latest) return;
		loading = false;
		if (!data) return;
		items = before ? [...items, ...data] : data;
		total = Number(response?.headers.get('X-Total-Count') ?? items.length);
		more = data.length > 0 && items.length < total;
	}

	/** Load the next page when the end of the list comes near. */
	function loadMoreNearby(node: HTMLElement) {
		const observer = new IntersectionObserver(
			([entry]) => {
				if (entry.isIntersecting && more) loadItems(items.at(-1)?.id);
			},
			{ rootMargin: '800px 0px' }
		);
		observer.observe(node);
		return () => observer.disconnect();
	}

	// The list for the current collection or tags (reloads when they change).
	$effect(() => {
		void collectionId;
		void tagIds.join();
		untrack(() => loadItems());
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
			const url = searchUrl(
				q,
				untrack(() => filters)
			);
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
		const options = { mode, type: types.length ? types : undefined };
		if (!q) {
			passages = null;
			return;
		}
		const key = page.url.search;
		search({ query: { q, ...options } }).then(({ data }) => {
			if (key === untrack(() => page.url.search)) passages = data ?? [];
		});
	});

	function clearSearch() {
		query = '';
		goto(searchUrl('', filters), { reset: false });
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
		<div class="tools">
			{#if query}
				<button class="clear" onclick={clearSearch} aria-label="Clear search" title="Clear search">
					<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7l10 10M17 7 7 17" /></svg>
				</button>
			{/if}
			<SearchFilters {filters} onchange={setFilters} />
		</div>
	</div>

	{#if searched}
		<div class="results-head row">
			<h1 class="count">
				{passages === null
					? 'Searching…'
					: `${groups.length} ${groups.length === 1 ? 'item' : 'items'} for “${searched}”`}
			</h1>
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
									{#if passage.in_references}
										<span class="badge">In the references</span>
									{:else if !passage.matched.includes('keyword')}
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
	{:else if items.length === 0 && tagIds.length}
		{@render filterHead()}
		<p class="muted">No items with these tags.</p>
	{:else if items.length === 0}
		<div class="empty">
			<h2>Nothing in the library yet</h2>
			<p class="muted">
				Drop PDFs anywhere in this window, or use Add at the top. paperus reads them, finds their
				title and authors, and makes the full text searchable.
			</p>
		</div>
	{:else}
		{@render filterHead()}
		<h1 class="count">
			{(total ?? items.length).toLocaleString()}
			{(total ?? items.length) === 1 ? 'item' : 'items'}
		</h1>
		<ul class="items">
			{#each items as item (item.id)}<ItemRow {item} />{/each}
		</ul>
		{#if more}
			<div {@attach loadMoreNearby} class="more">
				<button onclick={() => loadItems(items.at(-1)?.id)}>Show more</button>
			</div>
		{/if}
	{/if}
</div>

{#snippet filterHead()}
	{#if tagIds.length}
		<div class="filter-head">
			<h1>Tagged {tagNames.join(' and ')}</h1>
			<a href={resolve('/')}>Show all items</a>
		</div>
	{/if}
{/snippet}

<style>
	.library {
		display: grid;
		gap: 20px;
	}
	.search {
		position: relative;
		display: grid;
	}
	.search input {
		grid-area: 1 / 1;
	}
	.search input {
		font-size: var(--step-1);
		padding: 12px 14px 12px 46px;
		border-radius: 10px;
		border-color: var(--rule);
		background: var(--surface);
	}
	.search input {
		padding-right: 84px;
	}
	.search input::-webkit-search-cancel-button {
		display: none;
	}
	/* Icons inside the field, in the same grid cell, so the options panel is
	   positioned against the whole search box. */
	.tools {
		grid-area: 1 / 1;
		justify-self: end;
		align-self: center;
		margin-right: 8px;
		display: flex;
		gap: 2px;
	}
	.clear {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		padding: 0;
		border-color: transparent;
		border-radius: 50%;
		background: none;
	}
	.clear:hover:not(:disabled) {
		background: var(--rail);
		border-color: transparent;
	}
	.clear svg {
		width: 18px;
		height: 18px;
		fill: none;
		stroke: var(--muted);
		stroke-width: 2.2;
		stroke-linecap: round;
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
	.results-head {
		justify-content: space-between;
		margin: 8px 0 -12px;
	}
	.results-head .count {
		margin: 0;
	}
	.filter-head {
		display: grid;
		gap: 6px;
		margin-top: 8px;
	}
	.filter-head h1 {
		margin: 0;
		font-size: var(--step-2);
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
	.more {
		display: flex;
		justify-content: center;
		padding: 8px 0 24px;
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
