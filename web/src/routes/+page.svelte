<script lang="ts">
	import { resolve } from '$app/paths';
	import { listItems, search, type Item, type Passage } from '#lib/api/client.ts';
	import AddItem from '#lib/AddItem.svelte';
	import ItemRow from '#lib/ItemRow.svelte';
	import { addFiles, uploads } from '#lib/uploads.svelte.ts';

	const PAGE = 50;

	let items = $state<Item[]>([]);
	let more = $state(false);
	let query = $state('');
	let passages = $state<Passage[] | null>(null);
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

	// Search as you type, a moment after the last key.
	$effect(() => {
		const q = query.trim();
		if (!q) {
			passages = null;
			return;
		}
		const timer = setTimeout(async () => {
			const { data } = await search({ query: { q } });
			if (q === query.trim()) passages = data ?? [];
		}, 250);
		return () => clearTimeout(timer);
	});

	// Reload when uploads (dropped anywhere, or picked below) finish.
	$effect(() => {
		if (uploads.finished) loadItems();
	});
</script>

<div class="library">
	<div class="top row">
		<input
			type="search"
			bind:value={query}
			placeholder="Search the full text of the library…"
			aria-label="Search"
		/>
		<label class="pick">
			<input
				type="file"
				multiple
				onchange={(event) => {
					addFiles(event.currentTarget.files ?? []);
					event.currentTarget.value = '';
				}}
			/>
			<span>Upload files</span>
		</label>
		<button class="primary" onclick={() => (adding = !adding)}>{adding ? 'Close' : 'Add'}</button>
	</div>

	{#if adding}<AddItem />{/if}

	{#if passages !== null}
		{#if passages.length === 0}
			<p class="muted">Nothing found for “{query}”.</p>
		{/if}
		<ul class="passages">
			{#each passages as passage (passage.passage_id)}
				<li>
					<a
						href="{resolve('/items/[id]', { id: passage.item_id })}{passage.page
							? `?page=${passage.page}`
							: ''}">{passage.item_title}</a
					>
					{#if passage.page}<span class="badge">p. {passage.page}</span>{/if}
					<!-- Snippets are HTML-escaped on the server; only <mark> is added. -->
					<p>{@html passage.snippet}</p>
				</li>
			{/each}
		</ul>
	{:else if items.length === 0}
		<div class="empty card">
			<h2>Your library is empty</h2>
			<p>Drop files anywhere in this window, or add a paper by its DOI.</p>
		</div>
	{:else}
		<ul class="items">
			{#each items as item (item.id)}<ItemRow {item} />{/each}
		</ul>
		{#if more}
			<button onclick={() => loadItems(items.at(-1)?.id)}>Show more</button>
		{/if}
	{/if}
</div>

<style>
	.library {
		display: grid;
		gap: var(--gap);
	}
	.pick input {
		position: absolute;
		opacity: 0;
		width: 1px;
	}
	.pick span {
		display: inline-block;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 7px 14px;
		cursor: pointer;
		background: var(--surface);
	}
	.pick:focus-within span {
		outline: 2px solid var(--accent);
	}
	.top input {
		flex: 1;
		min-width: 0;
	}
	ul {
		margin: 0;
		padding: 0;
	}
	.passages li {
		list-style: none;
		padding: 10px 0;
		border-bottom: 1px solid var(--border);
	}
	.passages p {
		margin: 4px 0 0;
	}
	.passages a {
		font-weight: 600;
		text-decoration: none;
	}
	.empty {
		text-align: center;
	}
</style>
