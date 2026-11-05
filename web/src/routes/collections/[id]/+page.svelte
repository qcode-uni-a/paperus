<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { deleteCollection } from '#lib/api/client.ts';
	import CollectionDialog from '#lib/CollectionDialog.svelte';
	import CollectionStack from '#lib/CollectionStack.svelte';
	import ItemList from '#lib/ItemList.svelte';
	import { childrenOf, loadOrganize, organize } from '#lib/organize.svelte.ts';

	const id = $derived(page.params.id ?? '');
	let loaded = $state(false);
	let editDialog = $state<CollectionDialog>();
	let includeInside = $state(true);

	$effect(() => {
		loadOrganize().then(() => (loaded = true));
	});

	const collection = $derived(organize.collections.find((c) => c.id === id));
	const inside = $derived(childrenOf(id));
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
	<nav class="trail" aria-label="Collection path">
		<a href={resolve('/collections')}>Collections</a>
		{#each trail.slice(0, -1) as step (step.id)}
			<span aria-hidden="true">/</span>
			<a href={resolve('/collections/[id]', { id: step.id })}>{step.name}</a>
		{/each}
	</nav>

	<header class="head">
		<div>
			<h1>{collection.name}</h1>
			{#if collection.description}<p class="description">{collection.description}</p>{/if}
		</div>
		<div class="row actions">
			<button onclick={() => editDialog?.open()}>Edit</button>
			<button class="danger" onclick={remove}>Delete</button>
		</div>
	</header>

	{#if inside.length}
		<section>
			<h2>Inside</h2>
			<div class="grid">
				{#each inside as child (child.id)}
					<CollectionStack collection={child} />
				{/each}
			</div>
		</section>
	{/if}

	<section>
		{#if inside.length}
			<label class="toggle">
				<input type="checkbox" bind:checked={includeInside} />
				Include items of the collections inside
			</label>
		{/if}
		{#key id}
			<ItemList collection={id} nested={includeInside} />
		{/key}
	</section>

	{#key collection.id}
		<CollectionDialog bind:this={editDialog} {collection} />
	{/key}
{/if}

<style>
	.trail {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		font-size: var(--step--1);
		color: var(--faint);
		margin-bottom: 6px;
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
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 16px;
		flex-wrap: wrap;
		margin-bottom: 24px;
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
	.actions {
		padding-top: 8px;
	}
	section {
		display: grid;
		gap: 14px;
		margin-bottom: 32px;
	}
	section h2 {
		margin: 0;
		font-size: var(--step-1);
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
		gap: 20px 16px;
	}
	.toggle {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--muted);
	}
	.toggle input {
		width: auto;
	}
</style>
