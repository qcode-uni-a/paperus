<script lang="ts">
	import { addItems, errorMessage, listItems, type Item } from '#lib/api/client.ts';
	import { shortAuthors } from '#lib/format.ts';
	import { libraryForCollection, loadOrganize } from '#lib/organize.svelte.ts';

	/** Choose papers from the library to put into ``collection``. */
	let { collection, onadded }: { collection: string; onadded?: () => void } = $props();

	const LIMIT = 50;
	let dialog = $state<HTMLDialogElement>();
	let words = $state('');
	let items = $state<Item[]>([]);
	let total = $state(0);
	let chosen = $state<string[]>([]);
	let error = $state('');
	let saving = $state(false);
	let latest = 0;

	export function open() {
		words = '';
		chosen = [];
		error = '';
		search();
		dialog?.showModal();
	}

	async function search() {
		const request = ++latest;
		const { data, response } = await listItems({
			// A group's collection takes only that group's items.
			query: {
				limit: LIMIT,
				title: words.trim() || undefined,
				library: libraryForCollection(collection)
			}
		});
		if (request !== latest || !data) return;
		items = data;
		total = Number(response?.headers.get('X-Total-Count') ?? data.length);
	}

	// Search a moment after the last key.
	$effect(() => {
		void words;
		const timer = setTimeout(search, 200);
		return () => clearTimeout(timer);
	});

	function toggle(id: string) {
		chosen = chosen.includes(id) ? chosen.filter((c) => c !== id) : [...chosen, id];
	}

	async function add() {
		saving = true;
		const result = await addItems({
			path: { collection_id: collection },
			body: { item_ids: chosen }
		});
		saving = false;
		if (result.error) {
			error = errorMessage(result.error);
			return;
		}
		dialog?.close();
		await loadOrganize();
		onadded?.();
	}
</script>

<dialog bind:this={dialog} aria-labelledby="picker-title">
	<h2 id="picker-title">Add from the library</h2>
	<input
		type="search"
		bind:value={words}
		placeholder="Words in the title"
		aria-label="Search titles"
	/>
	<ul>
		{#each items as item (item.id)}
			{@const here = item.collection_ids.includes(collection)}
			<li>
				<label class:here>
					<input
						type="checkbox"
						checked={here || chosen.includes(item.id)}
						disabled={here}
						onchange={() => toggle(item.id)}
					/>
					<span>
						<strong>{item.title}</strong>
						<small>{shortAuthors(item.authors)}{item.year ? ` (${item.year})` : ''}</small>
						{#if here}<small>Already in this collection</small>{/if}
					</span>
				</label>
			</li>
		{:else}
			<li class="muted">Nothing in the library matches.</li>
		{/each}
	</ul>
	{#if total > items.length}
		<p class="muted more">
			Showing {items.length} of {total.toLocaleString()}; type more of the title to narrow it down.
		</p>
	{/if}
	{#if error}<p class="error">{error}</p>{/if}
	<div class="buttons">
		<button type="button" onclick={() => dialog?.close()}>Cancel</button>
		<button class="primary" disabled={!chosen.length || saving} onclick={add}>
			{chosen.length > 1 ? `Add ${chosen.length} items` : 'Add item'}
		</button>
	</div>
</dialog>

<style>
	dialog {
		width: min(600px, calc(100vw - 32px));
		max-height: min(720px, calc(100dvh - 32px));
		padding: 22px 24px 20px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	dialog[open] {
		display: grid;
		grid-template-rows: auto auto minmax(0, 1fr) auto auto auto;
		gap: 12px;
	}
	dialog::backdrop {
		background: rgb(10 14 30 / 0.4);
	}
	h2 {
		margin: 0;
		font-size: var(--step-2);
	}
	ul {
		margin: 0 -8px;
		padding: 0;
		overflow-y: auto;
		min-height: 120px;
	}
	li {
		list-style: none;
	}
	label {
		display: flex;
		gap: 12px;
		align-items: flex-start;
		padding: 8px;
		border-radius: var(--radius);
		cursor: pointer;
	}
	label:hover {
		background: var(--rail);
	}
	label.here {
		cursor: default;
		opacity: 0.6;
	}
	label input {
		flex: none;
		width: auto;
		margin-top: 4px;
	}
	label span {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	strong {
		font-family: var(--serif);
		font-weight: 600;
		line-height: 1.3;
	}
	small {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.more,
	.error {
		margin: 0;
		font-size: var(--step--1);
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
</style>
