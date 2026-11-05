<script lang="ts">
	import { changeCollection, deleteCollection, errorMessage } from '#lib/api/client.ts';
	import CollectionDialog from '#lib/CollectionDialog.svelte';
	import IconButton from '#lib/IconButton.svelte';
	import SharedIcon from '#lib/SharedIcon.svelte';
	import {
		childrenOf,
		libraryById,
		loadOrganize,
		organize,
		isShared,
		type Collection
	} from '#lib/organize.svelte.ts';

	let createDialog = $state<CollectionDialog>();
	let editDialog = $state<CollectionDialog>();
	let editing = $state<Collection | null>(null);
	let loaded = $state(false);
	let error = $state('');

	// Drag a card onto another to put it inside, or onto the top strip.
	let dragged = $state<string | null>(null);
	let over = $state<string | null>(null);

	$effect(() => {
		loadOrganize().then(() => (loaded = true));
	});

	const top = $derived(childrenOf(null));
	const writable = (collection: Collection) =>
		libraryById(collection.library_id)?.writable ?? false;
	const depth = $derived.by(() => {
		const level = (id: string): number =>
			1 + Math.max(0, ...childrenOf(id).map((c) => level(c.id)));
		return Math.max(0, ...top.map((c) => level(c.id)));
	});

	/** The collection and everything inside it. */
	function within(id: string): Set<string> {
		const found = new Set([id]);
		for (const child of childrenOf(id)) for (const inner of within(child.id)) found.add(inner);
		return found;
	}

	/** ``target``: a collection of the same owner, or the top level. */
	function canDrop(target: string): boolean {
		if (!dragged) return false;
		const moving = organize.collections.find((c) => c.id === dragged);
		if (!moving) return false;
		if (target === 'top') return moving.parent_id !== null;
		const into = organize.collections.find((c) => c.id === target);
		return (
			into !== undefined &&
			into.library_id === moving.library_id &&
			moving.parent_id !== target &&
			!within(dragged).has(target)
		);
	}

	async function move(id: string, parent: string | null) {
		error = '';
		const result = await changeCollection({
			path: { collection_id: id },
			body: { parent_id: parent }
		});
		if (result.error) error = errorMessage(result.error);
		await loadOrganize();
	}

	function dropTarget(target: string) {
		return {
			ondragover: (event: DragEvent) => {
				if (!canDrop(target)) return;
				event.preventDefault();
				over = target;
			},
			ondragleave: () => {
				if (over === target) over = null;
			},
			ondrop: (event: DragEvent) => {
				event.preventDefault();
				const id = dragged;
				const allowed = canDrop(target);
				dragged = over = null;
				if (id && allowed) move(id, target === 'top' ? null : target);
			}
		};
	}

	function edit(collection: Collection) {
		editing = collection;
		// After the dialog has the collection.
		queueMicrotask(() => editDialog?.open());
	}

	async function remove(collection: Collection) {
		const inside = within(collection.id).size - 1;
		const note = inside
			? ` The ${inside === 1 ? 'collection' : `${inside} collections`} inside go too.`
			: '';
		if (!confirm(`Delete “${collection.name}”?${note} The items stay in the library.`)) return;
		const result = await deleteCollection({ path: { collection_id: collection.id } });
		if (result.error) error = errorMessage(result.error);
		await loadOrganize();
	}

	function counts(collection: Collection): string {
		const items = `${collection.count} ${collection.count === 1 ? 'item' : 'items'}`;
		const children = childrenOf(collection.id).length;
		if (!children) return items;
		return `${items}, ${collection.direct} directly`;
	}
</script>

<svelte:head><title>Manage collections · paperus</title></svelte:head>

<header class="head">
	<div>
		<h1>Collections</h1>
		{#if organize.collections.length}
			<p class="muted">
				{organize.collections.length}
				{organize.collections.length === 1 ? 'collection' : 'collections'}, {top.length} at the top, up
				to {depth}
				{depth === 1 ? 'level' : 'levels'} deep. Drag a collection onto another to put it inside.
			</p>
		{/if}
	</div>
	<button onclick={() => createDialog?.open()}>New collection</button>
</header>

{#if error}<p class="error">{error}</p>{/if}

{#if loaded && organize.collections.length === 0}
	<p class="muted">No collections yet.</p>
{:else}
	<div
		class="root"
		class:target={dragged && canDrop('top')}
		class:over={over === 'top'}
		{...dropTarget('top')}
	>
		<span class="root-label">Top level</span>
		{#if dragged && canDrop('top')}<span class="hint">Drop here to move it to the top</span>{/if}
	</div>
	<ul class="tree">
		{#each top as collection (collection.id)}
			{@render node(collection)}
		{/each}
	</ul>
{/if}

{#snippet node(collection: Collection)}
	{@const children = childrenOf(collection.id)}
	<li>
		<div
			class="card"
			class:dragging={dragged === collection.id}
			class:over={over === collection.id}
			draggable={writable(collection)}
			role="group"
			aria-label={collection.name}
			ondragstart={(event) => {
				dragged = collection.id;
				event.dataTransfer?.setData('text/plain', collection.name);
				if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
			}}
			ondragend={() => (dragged = over = null)}
			{...dropTarget(collection.id)}
		>
			<span class="grip" aria-hidden="true">⋮⋮</span>
			<!-- A plain area, not a button: browsers start no drag inside buttons.
			     Keyboards edit through the ⋯ menu. -->
			<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
			<div class="body" onclick={() => writable(collection) && edit(collection)}>
				<strong
					>{collection.name}{#if isShared(collection.library_id)}<span class="shared-mark"
							><SharedIcon size={15} owner={collection.library_id} /></span
						>{/if}</strong
				>
				<span class="counts">{counts(collection)}</span>
				{#if collection.description}<span class="description">{collection.description}</span>{/if}
			</div>
			{#if writable(collection)}
				<IconButton icon="edit" label="Edit {collection.name}" onclick={() => edit(collection)} />
				<IconButton
					icon="delete"
					label="Delete {collection.name}"
					onclick={() => remove(collection)}
				/>
			{/if}
		</div>
		{#if children.length}
			<ul>
				{#each children as child (child.id)}
					{@render node(child)}
				{/each}
			</ul>
		{/if}
	</li>
{/snippet}

<CollectionDialog bind:this={createDialog} />
{#key editing?.id}
	<CollectionDialog bind:this={editDialog} collection={editing} />
{/key}

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		gap: 16px;
		margin-bottom: 20px;
	}
	h1 {
		margin: 0 0 4px;
	}
	.head button {
		white-space: nowrap;
	}
	.head p {
		margin: 0;
		max-width: 70ch;
	}
	.shared-mark {
		display: inline-flex;
		margin-left: 8px;
		vertical-align: -1px;
	}
	.root {
		display: flex;
		align-items: center;
		gap: 12px;
		margin-bottom: 10px;
		padding: 8px 12px;
		border: 2px dashed transparent;
		border-radius: 10px;
		color: var(--muted);
		font-size: var(--step--1);
		font-weight: 600;
	}
	.root.target {
		border-color: var(--rule);
	}
	.root.over {
		border-color: var(--royal);
		background: var(--rail);
	}
	.hint {
		font-weight: 400;
	}
	/* The tree: each level indented, joined to its parent by a rounded
	   elbow; the line runs on to the next sibling, never past the last. */
	ul {
		margin: 0;
		padding: 0;
		list-style: none;
		display: grid;
		gap: 10px;
	}
	.tree {
		padding-left: 30px;
	}
	.tree ul {
		margin-top: 10px;
		padding-left: 38px;
	}
	li {
		position: relative;
	}
	li::before {
		content: '';
		position: absolute;
		left: -20px;
		top: -10px;
		width: 20px;
		height: 38px;
		border-left: 2px solid var(--rule);
		border-bottom: 2px solid var(--rule);
		border-bottom-left-radius: 10px;
	}
	li:not(:last-child)::after {
		content: '';
		position: absolute;
		left: -20px;
		top: 18px;
		bottom: -10px;
		border-left: 2px solid var(--rule);
	}
	.card {
		display: flex;
		align-items: flex-start;
		gap: 2px;
		max-width: 560px;
		padding: 8px 8px 8px 4px;
		border: 1px solid var(--rule);
		border-radius: 10px;
		background: var(--surface);
		box-shadow: 0 1px 2px rgb(27 36 64 / 0.06);
	}
	.card.dragging {
		opacity: 0.5;
	}
	.card.over {
		border-color: var(--royal);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--royal) 25%, transparent);
	}
	.grip {
		align-self: center;
		padding: 0 4px;
		color: var(--faint);
		cursor: grab;
		letter-spacing: -0.2em;
		user-select: none;
	}
	.body {
		flex: 1;
		min-width: 0;
		display: grid;
		gap: 2px;
		padding: 2px 4px;
		cursor: pointer;
	}
	.body:hover strong {
		color: var(--royal);
	}
	strong {
		font-family: var(--serif);
		font-weight: 600;
		font-size: var(--step-1);
		line-height: 1.25;
		overflow-wrap: anywhere;
	}
	.counts {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.description {
		color: var(--muted);
		font-size: var(--step--1);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	@media (max-width: 720px) {
		.tree {
			padding-left: 24px;
		}
		.tree ul {
			padding-left: 26px;
		}
		li::before,
		li:not(:last-child)::after {
			left: -16px;
		}
		li::before {
			width: 16px;
		}
		.grip {
			display: none;
		}
	}
</style>
