<script lang="ts">
	import { resolve } from '$app/paths';
	import { addItems, addTag, errorMessage, removeItem, removeTag } from '#lib/api/client.ts';
	import type { ItemDetail } from '#lib/api/client.ts';
	import { collectionPath, flatTree, loadOrganize, organize } from '#lib/organize.svelte.ts';

	let { item, onchange }: { item: ItemDetail; onchange: () => void } = $props();

	let tagInput = $state('');
	let tagging = $state(false);
	let adding = $state(false);
	let error = $state('');

	const suggestions = $derived(
		organize.tags.filter((t) => !item.tags.some((own) => own.id === t.id)).map((t) => t.name)
	);
	const choices = $derived(
		flatTree().filter(({ collection }) => !item.collection_ids.includes(collection.id))
	);

	async function done(result: { error?: unknown }) {
		error = result.error ? errorMessage(result.error) : '';
		await Promise.all([loadOrganize(), onchange()]);
	}

	async function submitTag(event: SubmitEvent) {
		event.preventDefault();
		const name = tagInput.trim();
		if (!name) return;
		tagInput = '';
		tagging = false;
		await done(await addTag({ path: { item_id: item.id }, body: { name } }));
	}

	/** Open the list right away; the + was the click that asked for it. */
	function openPicker(select: HTMLSelectElement) {
		select.focus();
		try {
			select.showPicker();
		} catch {
			// Not supported everywhere; the focused list opens on the next tap.
		}
	}

	async function addToCollection(id: string) {
		adding = false;
		if (id)
			await done(await addItems({ path: { collection_id: id }, body: { item_ids: [item.id] } }));
	}
</script>

<div class="organize">
	<div class="line">
		<span class="label">Tags</span>
		{#each item.tags as tag (tag.id)}
			<span class="chip" data-tag-color={tag.color}>
				<a href="{resolve('/')}?tag={tag.id}">{tag.name}</a>
				<button
					onclick={async () =>
						done(await removeTag({ path: { item_id: item.id, tag_id: tag.id } }))}
					aria-label="Remove tag {tag.name}">×</button
				>
			</span>
		{/each}
		{#if tagging}
			<form onsubmit={submitTag}>
				<!-- svelte-ignore a11y_autofocus -->
				<input
					bind:value={tagInput}
					list="tag-suggestions"
					placeholder="New tag"
					aria-label="Add a tag"
					autofocus
					onblur={() => {
						if (!tagInput.trim()) tagging = false;
					}}
					onkeydown={(event) => {
						if (event.key === 'Escape') tagging = false;
					}}
				/>
				<datalist id="tag-suggestions">
					{#each suggestions as name (name)}<option value={name}></option>{/each}
				</datalist>
			</form>
		{:else}
			{@render plus('Add a tag', () => (tagging = true))}
		{/if}
	</div>

	<div class="line">
		<span class="label">Collections</span>
		{#each item.collection_ids as id (id)}
			<span class="chip">
				<a href={resolve('/collections/[id]', { id })}>{collectionPath(id) || '…'}</a>
				<button
					onclick={async () =>
						done(await removeItem({ path: { collection_id: id, item_id: item.id } }))}
					aria-label="Remove from {collectionPath(id)}">×</button
				>
			</span>
		{/each}
		{#if adding}
			<select
				{@attach openPicker}
				aria-label="Add to collection"
				onchange={(event) => addToCollection(event.currentTarget.value)}
				onblur={() => (adding = false)}
			>
				<option value="">Choose a collection…</option>
				{#each choices as { collection, depth } (collection.id)}
					<option value={collection.id}>{'  '.repeat(depth)}{collection.name}</option>
				{/each}
			</select>
		{:else if choices.length}
			{@render plus('Add to a collection', () => (adding = true))}
		{:else if organize.collections.length === 0}
			<span class="hint">Create collections in the menu with +.</span>
		{/if}
	</div>
	{#if error}<p class="error">{error}</p>{/if}
</div>

{#snippet plus(label: string, onclick: () => void)}
	<button class="plus" {onclick} aria-label={label} title={label}>
		<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 6v12M6 12h12" /></svg>
	</button>
{/snippet}

<style>
	.organize {
		display: grid;
		gap: 6px;
		margin-top: 10px;
	}
	.line {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
	}
	.label {
		width: 84px;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		padding: 1px 4px 1px 10px;
		border-radius: 999px;
		background: var(--tag-bg, var(--rail));
		font-size: 0.92em;
	}
	.chip a {
		color: var(--tag-ink, var(--ink));
		text-decoration: none;
	}
	.chip a:hover {
		text-decoration: underline;
	}
	.chip button {
		width: 22px;
		height: 22px;
		padding: 0;
		border: none;
		border-radius: 50%;
		background: none;
		color: var(--tag-ink, var(--muted));
		line-height: 1;
	}
	.chip button:hover {
		background: var(--rule);
	}
	input {
		width: 130px;
		padding: 3px 10px;
		border-radius: 999px;
		font-size: 0.92em;
	}
	select {
		width: auto;
		padding: 3px 8px;
		font-size: 0.92em;
	}
	.plus {
		display: grid;
		place-items: center;
		width: 26px;
		height: 26px;
		padding: 0;
		border: 1px dashed var(--rule);
		border-radius: 50%;
		background: none;
	}
	.plus:hover:not(:disabled) {
		border-color: var(--royal);
		background: var(--rail);
	}
	.plus svg {
		width: 14px;
		height: 14px;
		fill: none;
		stroke: var(--muted);
		stroke-width: 2.4;
		stroke-linecap: round;
	}
	.hint {
		color: var(--faint);
		font-size: var(--step--1);
	}
	.error {
		margin: 0;
	}
</style>
