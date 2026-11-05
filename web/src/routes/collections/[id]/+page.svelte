<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { deleteCollection } from '#lib/api/client.ts';
	import CollectionAdd from '#lib/CollectionAdd.svelte';
	import MenuButton from '#lib/MenuButton.svelte';
	import NoteRow from '#lib/NoteRow.svelte';
	import { listNotes } from '#lib/api/client.ts';
	import type { NoteOut } from '#lib/api/generated/types.gen.ts';
	import { startNote } from '#lib/notes.ts';
	import { downloadCitations } from '#lib/citations.ts';
	import CollectionDialog from '#lib/CollectionDialog.svelte';
	import ItemList from '#lib/ItemList.svelte';
	import { childrenOf, libraryById, loadOrganize, organize } from '#lib/organize.svelte.ts';

	const id = $derived(page.params.id ?? '');
	let loaded = $state(false);
	let editDialog = $state<CollectionDialog>();
	let list = $state<ItemList>();
	let includeInside = $state(true);

	// Notes in the collection (and the collections inside), above its papers.
	let notes = $state<NoteOut[]>([]);
	let noteError = $state('');
	$effect(() => {
		const shown = id;
		listNotes({ query: { collection: shown, nested: includeInside, limit: 200 } }).then(
			({ data }) => {
				if (shown === id) notes = data ?? [];
			}
		);
	});

	async function writeNote() {
		noteError = (await startNote({ collection: id, library: collection?.library_id })) ?? '';
	}

	$effect(() => {
		loadOrganize().then(() => (loaded = true));
	});

	const collection = $derived(organize.collections.find((c) => c.id === id));
	const inside = $derived(childrenOf(id));
	const writable = $derived(libraryById(collection?.library_id)?.writable ?? false);
	/** From the top level down to this collection. */
	const trail = $derived.by(() => {
		const path = [];
		let current = collection;
		while (current) {
			path.unshift(current);
			current = organize.collections.find((c) => c.id === current?.parent_id);
		}
		return path;
	});

	async function remove() {
		if (!collection) return;
		const ok = confirm(
			`Delete “${collection.name}”${inside.length ? ' and the collections inside it' : ''}? ` +
				'The items stay in the library.'
		);
		if (!ok) return;
		const parent = collection.parent_id;
		await deleteCollection({ path: { collection_id: collection.id } });
		await loadOrganize();
		goto(parent ? resolve('/collections/[id]', { id: parent }) : resolve('/collections'));
	}
</script>

<svelte:head><title>{collection?.name ?? 'Collection'} · paperus</title></svelte:head>

{#if loaded && !collection}
	<p>This collection does not exist. <a href={resolve('/collections')}>All collections</a></p>
{:else if collection}
	<div class="top">
		<nav class="trail" aria-label="Collection path">
			<a href={resolve('/collections')}>Collections</a>
			{#each trail.slice(0, -1) as step (step.id)}
				<span aria-hidden="true">/</span>
				<a href={resolve('/collections/[id]', { id: step.id })}>{step.name}</a>
			{/each}
		</nav>
		<div class="tools">
			{#if writable}
				<CollectionAdd collection={collection.id} onadded={() => list?.refresh()} />
			{/if}
			{#if collection}
				<MenuButton label="Collection actions">
					{#if inside.length}
						<button
							role="menuitemcheckbox"
							aria-checked={includeInside}
							onclick={() => (includeInside = !includeInside)}
						>
							<svg viewBox="0 0 24 24" aria-hidden="true">
								{#if includeInside}<path d="m5 12.5 4.5 4.5L19 7.5" />{/if}
							</svg>
							Include items of the collections inside
						</button>
						<hr />
					{/if}
					<button
						role="menuitem"
						onclick={() => downloadCitations({ collection: id, nested: includeInside }, 'bibtex')}
						>Export BibTeX</button
					>
					<button
						role="menuitem"
						onclick={() => downloadCitations({ collection: id, nested: includeInside }, 'csl-json')}
						>Export CSL-JSON</button
					>
					{#if writable}
						<hr />
						<button role="menuitem" onclick={writeNote}>New note here</button>
						<button role="menuitem" onclick={() => editDialog?.open()}>Edit</button>
						<button role="menuitem" class="danger" onclick={remove}>Delete</button>
					{/if}
				</MenuButton>
			{/if}
		</div>
	</div>

	<header class="head">
		<div>
			<h1>{collection.name}</h1>
			{#if collection.description}<p class="description">{collection.description}</p>{/if}
		</div>
	</header>

	{#if notes.length}
		<section class="notes" aria-label="Notes">
			<ul>
				{#each notes as note (note.id)}<NoteRow {note} />{/each}
			</ul>
		</section>
	{/if}
	{#if noteError}<p class="error">{noteError}</p>{/if}

	<section>
		{#key id}
			<ItemList bind:this={list} collection={id} nested={includeInside} />
		{/key}
	</section>

	{#key collection.id}
		<CollectionDialog bind:this={editDialog} {collection} />
	{/key}
{/if}

<style>
	.notes ul {
		margin: 0 0 8px;
		padding: 0;
	}
	.top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 2px;
	}
	.tools {
		display: flex;
		margin-right: -6px;
	}
	.trail {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		font-size: var(--step--1);
		color: var(--faint);
	}
	.trail a {
		color: var(--muted);
		text-decoration: none;
	}
	.trail a:hover {
		color: var(--royal);
		text-decoration: underline;
	}
	.head {
		margin-bottom: 24px;
		overflow-wrap: anywhere;
	}
	h1 {
		margin: 0;
		font-size: var(--step-4);
		letter-spacing: -0.02em;
	}
	.description {
		margin: 8px 0 0;
		max-width: 65ch;
		color: var(--muted);
		font-family: var(--serif);
		font-size: var(--step-1);
		line-height: 1.5;
	}
	section {
		display: grid;
		gap: 14px;
		margin-bottom: 32px;
	}
	@media (max-width: 720px) {
		h1 {
			font-size: var(--step-3);
		}
		.description {
			margin-top: 4px;
			font-size: var(--step-0);
		}
		.head {
			margin-bottom: 12px;
		}
	}
</style>
