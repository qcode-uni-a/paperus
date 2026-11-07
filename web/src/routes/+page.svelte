<script lang="ts">
	import Title from '#lib/Title.svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import { listItems, search, type Item, type Passage } from '#lib/api/client.ts';
	import { organize } from '#lib/organize.svelte.ts';
	import ItemRow from '#lib/ItemRow.svelte';
	import { shortAuthors } from '#lib/format.ts';
	import { uploads } from '#lib/uploads.svelte.ts';

	const PAGE = 50;
	// Passages fetched per search: the best few per paper (as the AI
	// assistants get them), so one paper cannot fill the list; "More from
	// this paper" fetches the rest of that one.
	const SEARCH_PASSAGES = 60;
	const PER_PAPER = 3;
	/** Paper id → all its passages, once fetched. */
	let allOf = $state<Record<string, Passage[]>>({});
	let loadingMore = $state<string | null>(null);

	async function showMore(itemId: string) {
		loadingMore = itemId;
		const { data } = await search({
			query: {
				q: searched,
				item: itemId,
				limit: 50,
				mode,
				type: types.length ? types : undefined,
				archived: archived || undefined
			}
		});
		loadingMore = null;
		allOf[itemId] = data ?? [];
	}

	let items = $state<Item[]>([]);
	let more = $state(false);
	// The search lives in the address (?q=…), typed in the top bar
	// (SearchBar), so Back and links keep it.
	const searched = $derived(page.url.searchParams.get('q')?.trim() ?? '');
	const mode = $derived(
		(page.url.searchParams.get('mode') ?? 'hybrid') as 'hybrid' | 'keyword' | 'meaning'
	);
	const types = $derived(page.url.searchParams.getAll('type'));
	const archived = $derived(page.url.searchParams.has('archived'));
	let passages = $state<Passage[] | null>(null);

	/** Passages grouped by paper or note, in the order of their best passage. */
	const groups = $derived.by(() => {
		type Group = {
			id: string;
			kind: 'paper' | 'note';
			title: string;
			/** "Vicente-Serrano and Beguería (2010)": how people know a paper. */
			byline: string;
			passages: Passage[];
		};
		const bySource = new Map<string, Group>();
		for (const passage of passages ?? []) {
			const id = passage.item_id ?? passage.note_id ?? '';
			const kind = passage.kind ?? 'paper';
			const authors = shortAuthors(passage.item_authors ?? []);
			const year = passage.item_year ? `(${passage.item_year})` : '';
			const byline = [authors, year].filter(Boolean).join(' ');
			const group = bySource.get(id) ?? {
				id,
				kind,
				title: passage.item_title,
				byline,
				passages: []
			};
			group.passages.push(passage);
			bySource.set(id, group);
		}
		return [...bySource.values()];
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

	// Results for the searched words.
	$effect(() => {
		const q = searched;
		const options = {
			mode,
			type: types.length ? types : undefined,
			archived: archived || undefined
		};
		allOf = {};
		if (!q) {
			passages = null;
			return;
		}
		const key = page.url.search;
		search({ query: { q, limit: SEARCH_PASSAGES, per_item: PER_PAPER, ...options } }).then(
			({ data }) => {
				if (key === untrack(() => page.url.search)) passages = data ?? [];
			}
		);
	});

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
			<p class="muted">Nothing found for “{searched}”.</p>
		{:else}
			<ul class="results">
				{#each groups as group (group.id)}
					<li>
						{#if group.kind === 'note'}
							<a class="source" href={resolve('/notes/[id]', { id: group.id })}
								><span class="badge">Note</span> {group.title || 'Untitled note'}</a
							>
						{:else}
							<a class="source" href={resolve('/items/[id]', { id: group.id })}
								><Title text={group.title} /></a
							>
							{#if group.byline}<p class="byline">{group.byline}</p>{/if}
						{/if}
						<ul class="passages">
							{#each allOf[group.id] ?? group.passages as passage (passage.passage_id)}
								<li>
									{#if group.kind === 'paper'}
										<a
											class="where"
											href="{resolve('/items/[id]', { id: group.id })}?{new URLSearchParams({
												...(passage.page ? { page: String(passage.page) } : {}),
												...(passage.file_id
													? { file: passage.file_id, passage: String(passage.position) }
													: {})
											})}"
										>
											{passage.page ? `Page ${passage.page}` : 'Open'}
										</a>
									{/if}
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
						{#if group.kind === 'paper' && group.passages.length >= PER_PAPER && !allOf[group.id]}
							<button
								class="more-passages"
								disabled={loadingMore === group.id}
								onclick={() => showMore(group.id)}
								>{loadingMore === group.id ? 'Looking…' : 'More from this paper'}</button
							>
						{/if}
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
	.byline {
		margin: 2px 0 0;
		color: var(--muted);
	}
	.source:hover {
		color: var(--royal);
		text-decoration: underline;
	}
	.more-passages {
		justify-self: start;
		margin: 2px 0 0 14px;
		padding: 2px 10px;
		border: none;
		background: none;
		color: var(--royal);
		font-size: var(--step--1);
	}
	.more-passages:hover:not(:disabled) {
		background: var(--accent-soft);
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
