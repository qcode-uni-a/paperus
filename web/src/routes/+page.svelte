<script lang="ts">
	import { resolve } from '$app/paths';
	import {
		addItem,
		errorMessage,
		listItems,
		search,
		uploadToItem,
		type Item,
		type Passage
	} from '#lib/api/client.ts';
	import AddItem from '#lib/AddItem.svelte';
	import ItemRow from '#lib/ItemRow.svelte';

	const PAGE = 50;

	let items = $state<Item[]>([]);
	let more = $state(false);
	let query = $state('');
	let passages = $state<Passage[] | null>(null);
	let adding = $state(false);
	let dragging = $state(false);
	let uploads = $state<string[]>([]);
	let error = $state('');

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

	/** Each dropped file becomes an item titled after the file. */
	async function drop(event: DragEvent) {
		event.preventDefault();
		dragging = false;
		error = '';
		for (const file of event.dataTransfer?.files ?? []) {
			uploads = [...uploads, file.name];
			const title = file.name.replace(/\.[^.]+$/, '');
			const { data: item, error: failure } = await addItem({ body: { metadata: { title } } });
			if (item) {
				const { error: uploadFailure } = await uploadToItem({
					path: { item_id: item.id },
					body: { upload: file, role: 'main' }
				});
				if (uploadFailure) error = `${file.name}: ${errorMessage(uploadFailure)}`;
			} else {
				error = `${file.name}: ${errorMessage(failure)}`;
			}
			uploads = uploads.filter((name) => name !== file.name);
		}
		await loadItems();
	}
</script>

<div
	class="library"
	class:dragging
	role="region"
	aria-label="Library; drop files here to add them"
	ondragover={(event) => {
		event.preventDefault();
		dragging = true;
	}}
	ondragleave={() => (dragging = false)}
	ondrop={drop}
>
	<div class="top row">
		<input
			type="search"
			bind:value={query}
			placeholder="Search the full text of the library…"
			aria-label="Search"
		/>
		<button class="primary" onclick={() => (adding = !adding)}>{adding ? 'Close' : 'Add'}</button>
	</div>

	{#if adding}<AddItem />{/if}
	{#if uploads.length}<p class="muted">Adding {uploads.join(', ')}…</p>{/if}
	{#if error}<p class="error">{error}</p>{/if}

	{#if passages !== null}
		{#if passages.length === 0}
			<p class="muted">Nothing found for “{query}”.</p>
		{/if}
		<ul class="passages">
			{#each passages as passage (passage.passage_id)}
				<li>
					<a href={resolve('/items/[id]', { id: passage.item_id })}>{passage.item_title}</a>
					{#if passage.page}<span class="badge">p. {passage.page}</span>{/if}
					<!-- Snippets are HTML-escaped on the server; only <mark> is added. -->
					<p>{@html passage.snippet}</p>
				</li>
			{/each}
		</ul>
	{:else if items.length === 0}
		<div class="empty card">
			<h2>Your library is empty</h2>
			<p>Drop PDFs anywhere on this page, or add a paper by its DOI.</p>
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
		min-height: 60vh;
		border-radius: var(--radius);
		outline: 2px dashed transparent;
		outline-offset: 8px;
	}
	.dragging {
		outline-color: var(--accent);
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
