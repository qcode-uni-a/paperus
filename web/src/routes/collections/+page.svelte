<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import CollectionDialog from '#lib/CollectionDialog.svelte';
	import CollectionStack from '#lib/CollectionStack.svelte';
	import { childrenOf, loadOrganize, organize } from '#lib/organize.svelte.ts';

	let dialog = $state<CollectionDialog>();
	let loaded = $state(false);

	$effect(() => {
		loadOrganize().then(() => (loaded = true));
	});

	const top = $derived(childrenOf(null));
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
	<button class="primary" onclick={() => dialog?.open()}>New collection</button>
</header>

{#if loaded && top.length === 0}
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
	<div class="grid">
		{#each top as collection (collection.id)}
			<CollectionStack {collection} />
		{/each}
	</div>
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
	.head p {
		margin: 0;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
		gap: 20px 16px;
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
