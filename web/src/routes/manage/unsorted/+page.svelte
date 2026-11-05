<script lang="ts">
	import { addVersion, errorMessage, listItems, type Item } from '#lib/api/client.ts';
	import ItemRow from '#lib/ItemRow.svelte';

	/** Papers whose details were only guessed from their file: no DOI or
	 * arXiv ID found in it. A DOI looks the details up. */
	let items = $state<Item[] | null>(null);
	let total = $state(0);
	let entered = $state<Record<string, string>>({});
	let errors = $state<Record<string, string>>({});
	let busy = $state<string | null>(null);
	let fixed = $state(0);

	async function load() {
		const { data, response } = await listItems({ query: { unsorted: true, limit: 200 } });
		items = data ?? [];
		total = Number(response?.headers.get('X-Total-Count') ?? items.length);
	}

	$effect(() => {
		load();
	});

	/** A DOI, a doi.org link, or an arXiv ID (as its DOI). */
	function asDoi(text: string): string {
		const value = text.trim();
		const arxiv = value.match(/^(?:arxiv:\s*)?(\d{4}\.\d{4,5})(v\d+)?$/i);
		return arxiv ? `10.48550/arXiv.${arxiv[1]}` : value;
	}

	async function lookUp(event: SubmitEvent, item: Item) {
		event.preventDefault();
		const doi = asDoi(entered[item.id] ?? '');
		if (!doi) return;
		busy = item.id;
		errors[item.id] = '';
		const { error } = await addVersion({ path: { item_id: item.id }, body: { doi } });
		busy = null;
		if (error) {
			errors[item.id] = errorMessage(error);
			return;
		}
		fixed += 1;
		await load();
	}
</script>

<svelte:head><title>Unsorted · paperus</title></svelte:head>

<header class="head">
	<h1>Unsorted</h1>
	<p class="muted">
		Papers whose details could not be found: their files had no DOI or arXiv ID, so the title is
		only a guess. Enter the DOI or arXiv ID to look the details up, or open a paper to type them in.
	</p>
</header>

{#if fixed}<p class="saved" role="status">
		{fixed}
		{fixed === 1 ? 'paper' : 'papers'} sorted.
	</p>{/if}

{#if items === null}
	<p class="muted">Loading…</p>
{:else if items.length === 0}
	<p class="muted">Nothing to sort: every paper has its details.</p>
{:else}
	{#if total > items.length}<p class="muted">The first {items.length} of {total}.</p>{/if}
	<ul>
		{#each items as item (item.id)}
			<ItemRow {item}>
				{#snippet actions()}
					<form onsubmit={(event) => lookUp(event, item)}>
						<input
							bind:value={entered[item.id]}
							placeholder="DOI or arXiv ID, e.g. 10.1038/… or 2611.04768"
							aria-label="DOI or arXiv ID of {item.title}"
						/>
						<button disabled={busy === item.id || !entered[item.id]?.trim()}>
							{busy === item.id ? 'Looking up…' : 'Look up'}
						</button>
					</form>
					{#if errors[item.id]}<p class="error">{errors[item.id]}</p>{/if}
				{/snippet}
			</ItemRow>
		{/each}
	</ul>
{/if}

<style>
	.head {
		margin-bottom: 12px;
	}
	h1 {
		margin: 0 0 6px;
	}
	.head p {
		max-width: 70ch;
		margin: 0;
	}
	ul {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	form {
		display: flex;
		gap: 8px;
		max-width: 560px;
	}
	form input {
		flex: 1;
		min-width: 0;
	}
	.error {
		margin: 6px 0 0;
	}
	.saved {
		color: var(--success);
	}
</style>
