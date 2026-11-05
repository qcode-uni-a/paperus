<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { deleteCollection } from '#lib/api/client.ts';
	import { closeOnScroll } from '#lib/dismiss.ts';
	import CollectionDialog from '#lib/CollectionDialog.svelte';
	import ItemList from '#lib/ItemList.svelte';
	import { childrenOf, loadOrganize, organize } from '#lib/organize.svelte.ts';

	const id = $derived(page.params.id ?? '');
	let loaded = $state(false);
	let editDialog = $state<CollectionDialog>();
	let menu = $state<HTMLElement>();
	let moreButton = $state<HTMLElement>();

	$effect(() => closeOnScroll(() => menu?.hidePopover()));

	/** Open the actions menu below its button, right-aligned with it. */
	function placeMenu() {
		if (!menu || !moreButton) return;
		const rect = moreButton.getBoundingClientRect();
		menu.style.setProperty('--top', `${rect.bottom + 6}px`);
		menu.style.setProperty('--left', `${Math.max(12, rect.right - 250)}px`);
	}
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
	<div class="top">
		<nav class="trail" aria-label="Collection path">
			<a href={resolve('/collections')}>Collections</a>
			{#each trail.slice(0, -1) as step (step.id)}
				<span aria-hidden="true">/</span>
				<a href={resolve('/collections/[id]', { id: step.id })}>{step.name}</a>
			{/each}
		</nav>
		<button
			bind:this={moreButton}
			class="more"
			popovertarget="collection-menu"
			aria-haspopup="menu"
			aria-label="Collection actions"
			title="Edit or delete"
		>
			<svg viewBox="0 0 24 24" aria-hidden="true">
				<circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle
					cx="19"
					cy="12"
					r="1.8"
				/>
			</svg>
		</button>
		<div
			id="collection-menu"
			popover
			bind:this={menu}
			role="menu"
			class="menu"
			onbeforetoggle={placeMenu}
		>
			{#if inside.length}
				<button
					role="menuitemcheckbox"
					aria-checked={includeInside}
					class="check"
					onclick={() => (menu?.hidePopover(), (includeInside = !includeInside))}
				>
					<svg viewBox="0 0 24 24" aria-hidden="true">
						{#if includeInside}<path d="m5 12.5 4.5 4.5L19 7.5" />{/if}
					</svg>
					Include items of the collections inside
				</button>
				<hr />
			{/if}
			<button role="menuitem" onclick={() => (menu?.hidePopover(), editDialog?.open())}>
				Edit
			</button>
			<button role="menuitem" class="danger" onclick={() => (menu?.hidePopover(), remove())}>
				Delete
			</button>
		</div>
	</div>

	<header class="head">
		<div>
			<h1>{collection.name}</h1>
			{#if collection.description}<p class="description">{collection.description}</p>{/if}
		</div>
	</header>

	<section>
		{#key id}
			<ItemList collection={id} nested={includeInside} />
		{/key}
	</section>

	{#key collection.id}
		<CollectionDialog bind:this={editDialog} {collection} />
	{/key}
{/if}

<style>
	.top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 2px;
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
	.more {
		flex: none;
		display: grid;
		place-items: center;
		width: 36px;
		height: 36px;
		margin-right: -6px;
		padding: 0;
		border-color: transparent;
		border-radius: 50%;
		background: none;
	}
	.more:hover:not(:disabled),
	.more:focus-visible {
		background: var(--rail);
		border-color: transparent;
	}
	.more svg {
		width: 20px;
		height: 20px;
		fill: var(--muted);
	}
	.menu {
		position: fixed;
		inset: var(--top) auto auto var(--left);
		margin: 0;
		padding: 6px;
		width: 250px;
		border: 1px solid var(--rule);
		border-radius: 10px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	.menu button {
		display: block;
		width: 100%;
		text-align: left;
		padding: 9px 12px;
		border: none;
		border-radius: var(--radius);
		background: none;
		color: var(--ink);
	}
	.menu button:hover:not(:disabled) {
		background: var(--rail);
	}
	.menu .check {
		display: flex;
		gap: 8px;
		align-items: flex-start;
		padding-left: 8px;
	}
	.check svg {
		flex: none;
		width: 18px;
		height: 18px;
		margin-top: 2px;
		fill: none;
		stroke: var(--royal);
		stroke-width: 2.4;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.menu hr {
		margin: 6px 4px;
		border: none;
		border-top: 1px solid var(--rule);
	}
	.menu button:not(.check) {
		padding-left: 34px;
	}
	.menu button.danger {
		color: var(--danger);
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
