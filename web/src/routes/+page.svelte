<script lang="ts">
	import Title from '#lib/Title.svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import { listItems, search, type Item, type Passage } from '#lib/api/client.ts';
	import { organize } from '#lib/organize.svelte.ts';
	import GettingStarted from '#lib/GettingStarted.svelte';
	import HandedOver from '#lib/HandedOver.svelte';
	import ItemRow from '#lib/ItemRow.svelte';
	import { shortAuthors } from '#lib/format.ts';
	import { uploads } from '#lib/uploads.svelte.ts';
	import LibraryFilter from '#lib/LibraryFilter.svelte';
	import { fromAddress, isEmpty, toQuery } from '#lib/libraryFilter.ts';
	import { keepPlace } from '#lib/keepPlace.svelte.ts';
	import BulkBar from '#lib/BulkBar.svelte';
	import { Selection } from '#lib/selection.svelte.ts';

	const PAGE = 50;
	// The most the server lists at once.
	const MOST = 200;
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
	const selection = new Selection(() => items.map((item) => item.id));
	/** The getting-started steps are shown (they say how to add papers). */
	let starting = $state(false);
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
	/** The search under way (for Back to the results' place). */
	let searching: Promise<unknown> = Promise.resolve();

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
			// A paper's details (title, abstract) belong with its passages.
			const kind = passage.kind === 'note' ? 'note' : 'paper';
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

	// Filters from the address: the rules of smart collections (?tag=…,
	// several: all of them), an author (LibraryFilter).
	const collectionId = $derived(page.url.searchParams.get('collection'));
	const filter = $derived(fromAddress(page.url.searchParams));
	const filtered = $derived(!isEmpty(filter));

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

	async function loadItems(before?: string, limit = PAGE) {
		if (before && loading) return;
		const request = ++latest;
		loading = true;
		const { data, response } = await listItems({
			query: {
				limit,
				before,
				collection: collectionId ?? undefined,
				...toQuery(filter)
			}
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
			await loadItems(undefined, Math.min(Math.max(count, PAGE), MOST));
			while (more && items.length < count) {
				await loadItems(items.at(-1)?.id, Math.min(count - items.length, MOST));
			}
		} finally {
			refilling = false;
		}
	}

	keepPlace(
		'library',
		() => items.length,
		async (count) => {
			await Promise.all([loadUpTo(count), searching]);
		}
	);

	/** Load the next page when the end of the list comes near. */
	function loadMoreNearby(node: HTMLElement) {
		const observer = new IntersectionObserver(
			([entry]) => {
				if (entry.isIntersecting && more && !refilling) loadItems(items.at(-1)?.id);
			},
			{ rootMargin: '800px 0px' }
		);
		observer.observe(node);
		return () => observer.disconnect();
	}

	// The list for the current filter (reloads when it changes).
	const filterKey = $derived(JSON.stringify(toQuery(filter)));
	$effect(() => {
		void collectionId;
		void filterKey;
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
		searching = search({
			query: { q, limit: SEARCH_PASSAGES, per_item: PER_PAPER, ...options }
		}).then(({ data }) => {
			if (key === untrack(() => page.url.search)) passages = data ?? [];
		});
	});

	// While the server reads new files, refresh to show their real titles.
	$effect(() => {
		if (!items.some((item) => item.processing)) return;
		const timer = setInterval(() => !refilling && loadUpTo(items.length), 2000);
		return () => clearInterval(timer);
	});

	// Reload when uploads (dropped anywhere, or picked below) finish.
	$effect(() => {
		if (uploads.finished) untrack(() => loadUpTo(items.length));
	});
</script>

<div class="library">
	<HandedOver />
	{#if !searched && !filtered}<GettingStarted bind:shown={starting} />{/if}
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
									{#if passage.kind === 'details'}
										<a class="where" href={resolve('/items/[id]', { id: group.id })}
											>Title, abstract</a
										>
									{:else if group.kind === 'paper'}
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
	{:else if items.length === 0 && filtered}
		<LibraryFilter count={heading} />
		<p class="muted">No papers match the filter.</p>
	{:else if items.length === 0 && starting}
		<!-- The getting-started steps say how to add papers. -->
	{:else if items.length === 0}
		<div class="empty">
			<h2>Nothing in the library yet</h2>
			<p class="muted">
				Drop PDFs anywhere in this window, or use Add at the top. paperus reads them, finds their
				title and authors, and makes the full text searchable.
			</p>
		</div>
	{:else}
		<LibraryFilter count={heading} />
		<ul class="items">
			{#each items as item (item.id)}<ItemRow {item} {selection} />{/each}
		</ul>
		<BulkBar {selection} {items} onchange={() => loadUpTo(items.length)} />
		{#if more}
			<div {@attach loadMoreNearby} class="more">
				<button onclick={() => loadItems(items.at(-1)?.id)}>Show more</button>
			</div>
		{/if}
	{/if}
</div>

{#snippet heading()}
	<h1 class="count listed">
		{(total ?? items.length).toLocaleString()}
		{(total ?? items.length) === 1 ? 'item' : 'items'}
	</h1>
	{#if items.length && !selection.active}<button
			class="select"
			onclick={() => (selection.active = true)}>Select</button
		>{/if}
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
	.count {
		font-size: var(--step-0);
		font-family: var(--sans);
		font-weight: 600;
		color: var(--muted);
		margin: 8px 0 -12px;
		letter-spacing: 0;
	}
	/* Beside the Filter button. */
	.count.listed {
		margin: 0;
	}
	.select {
		margin-left: auto;
		padding: 3px 12px;
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
