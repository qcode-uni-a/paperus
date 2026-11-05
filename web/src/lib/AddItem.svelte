<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { addItem, addItems, errorMessage } from '#lib/api/client.ts';
	import { loadOrganize } from '#lib/organize.svelte.ts';

	/** Called once the item exists. Without ``collection`` the item opens
	 * then; with it, the item is put into that collection and stays closed. */
	let { ondone, collection }: { ondone?: () => void; collection?: string } = $props();

	let doi = $state('');
	let manual = $state(false);
	let title = $state('');
	let type = $state('document');
	let genre = $state('');
	let date = $state('');
	let error = $state('');
	let busy = $state(false);

	// CSL types people add by hand most often.
	const TYPES = [
		['document', 'Document (notes, meeting notes)'],
		['article-journal', 'Journal article'],
		['article', 'Preprint'],
		['book', 'Book'],
		['chapter', 'Book chapter'],
		['paper-conference', 'Conference paper'],
		['thesis', 'Thesis'],
		['report', 'Report'],
		['speech', 'Talk or lecture'],
		['dataset', 'Dataset'],
		['software', 'Software']
	];

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		busy = true;
		error = '';
		const body = manual
			? {
					metadata: {
						type,
						title,
						...(genre && { genre }),
						...(date && { issued: { 'date-parts': [date.split('-').map(Number)] } })
					}
				}
			: { doi };
		const { data, error: failure } = await addItem({ body });
		if (data && collection) {
			const added = await addItems({
				path: { collection_id: collection },
				body: { item_ids: [data.id] }
			});
			busy = false;
			if (added.error) {
				error = errorMessage(added.error);
				return;
			}
			await loadOrganize();
			ondone?.();
			return;
		}
		busy = false;
		if (!data) {
			error = errorMessage(failure);
			return;
		}
		ondone?.();
		await goto(resolve('/items/[id]', { id: data.id }));
	}
</script>

<form onsubmit={submit}>
	{#if manual}
		<div class="grid">
			<label class="wide">Title <input bind:value={title} required /></label>
			<label
				>Type
				<select bind:value={type}>
					{#each TYPES as [value, label] (value)}<option {value}>{label}</option>{/each}
				</select>
			</label>
			<label>Genre <input bind:value={genre} placeholder="e.g. Meeting notes" /></label>
			<label>Date <input type="date" bind:value={date} /></label>
		</div>
	{:else}
		<label
			>DOI or link <input
				bind:value={doi}
				placeholder="10.1038/… or https://doi.org/…"
				required
			/></label
		>
	{/if}
	{#if error}<p class="error">{error}</p>{/if}
	<div class="row">
		<button class="primary" disabled={busy}>{busy ? 'Adding…' : 'Add'}</button>
		<button type="button" onclick={() => (manual = !manual)}>
			{manual ? 'Add by DOI instead' : 'Enter details by hand'}
		</button>
	</div>
</form>

<style>
	form {
		display: grid;
		gap: 12px;
	}
	label {
		display: grid;
		gap: 4px;
	}
	.grid {
		display: grid;
		gap: 12px;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
	}
	.wide {
		grid-column: 1 / -1;
	}
</style>
