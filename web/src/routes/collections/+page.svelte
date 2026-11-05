<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import CollectionDialog from '#lib/CollectionDialog.svelte';
	import CollectionStack from '#lib/CollectionStack.svelte';
	import {
		flatTree,
		libraryName,
		loadOrganize,
		organize,
		severalLibraries
	} from '#lib/organize.svelte.ts';

	let dialog = $state<CollectionDialog>();
	let loaded = $state(false);

	$effect(() => {
		loadOrganize().then(() => (loaded = true));
	});

	// All collections; nesting only organizes them, so each is shown alike.
	const all = $derived(flatTree().map((row) => row.collection));
	// Per library: those with collections, and those one may add to.
	const sections = $derived(
		organize.libraries
			.map((library) => ({
				library,
				collections: flatTree(library.id).map((row) => row.collection)
			}))
			.filter(({ library, collections }) => collections.length || library.writable)
	);
</script>

<svelte:head><title>Collections · paperus</title></svelte:head>

<header class="head">
	<div>
		<h1>Collections</h1>
		{#if organize.collections.length}
			<p class="muted">
				{organize.collections.length}
				{organize.collections.length === 1 ? 'collection' : 'collections'}; an item can be in
				several.
			</p>
		{/if}
	</div>
</header>

{#if loaded && all.length === 0}
	<div class="empty">
		<div class="sheet" aria-hidden="true"></div>
		<div>
			<h2>No collections yet</h2>
			<p class="muted">
				Collections group items for a project, a thesis or a reading list. They can hold other
				collections, and an item can be in several.
			</p>
			<button class="primary" onclick={() => dialog?.open()}>Create the first collection</button>
		</div>
	</div>
{:else}
	{#each sections as { library, collections } (library.id)}
		<section>
			{#if severalLibraries()}<h2 class="library">{libraryName(library.id)}</h2>{/if}
			<div class="grid">
				{#each collections as collection (collection.id)}
					<CollectionStack {collection} />
				{/each}
				{#if library.writable}
					<!-- A ghost collection: the place for the next one. -->
					<button class="ghost" onclick={() => dialog?.open(library.id)}>
						<span class="desk" aria-hidden="true">
							<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>
						</span>
						<span class="label">New collection</span>
					</button>
				{/if}
			</div>
		</section>
	{/each}
{/if}

<CollectionDialog bind:this={dialog} onsaved={(id) => goto(resolve('/collections/[id]', { id }))} />

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		gap: 16px;
		flex-wrap: wrap;
		margin-bottom: 24px;
	}
	h1 {
		margin: 0 0 4px;
	}
	section {
		margin-bottom: 32px;
	}
	h2.library {
		margin: 0 0 12px;
		font-size: var(--step-1);
	}
	.head p {
		margin: 0;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
		gap: 20px 16px;
	}
	.ghost {
		display: grid;
		align-content: start;
		gap: 10px;
		padding: 6px 6px 10px;
		border: none;
		border-radius: 12px;
		background: none;
		color: var(--muted);
		text-align: left;
		font: inherit;
	}
	.ghost:hover:not(:disabled) {
		background: var(--rail);
		color: var(--ink);
	}
	.ghost .desk {
		display: grid;
		place-items: center;
		height: 150px;
		border: 2px dashed var(--rule);
		border-radius: 10px;
	}
	.ghost:hover .desk {
		border-color: var(--royal);
	}
	.ghost svg {
		width: 36px;
		height: 36px;
		fill: none;
		stroke: currentColor;
		stroke-width: 1.6;
		stroke-linecap: round;
	}
	.ghost .label {
		padding: 0 4px;
		font-family: var(--serif);
		font-size: var(--step-1);
		font-weight: 600;
		line-height: 1.25;
	}
	.empty {
		display: flex;
		gap: 28px;
		align-items: center;
		padding: 32px 0;
		max-width: 60ch;
	}
	.empty h2 {
		margin: 0 0 6px;
		font-size: var(--step-2);
	}
	.empty p {
		margin: 0 0 16px;
	}
	.sheet {
		flex: none;
		width: 90px;
		height: 118px;
		border: 2px dashed var(--rule);
		border-radius: 6px;
		transform: rotate(-5deg);
	}
	@media (max-width: 520px) {
		.empty {
			flex-direction: column;
			align-items: flex-start;
		}
	}
</style>
