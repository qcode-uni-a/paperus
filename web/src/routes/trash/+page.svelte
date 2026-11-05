<script lang="ts">
	import { listItems, listNotes, restoreItem, restoreNote, type Item } from '#lib/api/client.ts';
	import type { NoteOut } from '#lib/api/generated/types.gen.ts';
	import ItemRow from '#lib/ItemRow.svelte';
	import NoteRow from '#lib/NoteRow.svelte';

	let items = $state<Item[] | null>(null);
	let notes = $state<NoteOut[]>([]);

	async function load() {
		const [papers, written] = await Promise.all([
			listItems({ query: { trashed: true, limit: 200 } }),
			listNotes({ query: { trashed: true, limit: 200 } })
		]);
		items = papers.data ?? [];
		notes = written.data ?? [];
	}

	$effect(() => {
		load();
	});

	async function restore(id: string) {
		await restoreItem({ path: { item_id: id } });
		await load();
	}

	async function restoreWritten(id: string) {
		await restoreNote({ path: { note_id: id } });
		await load();
	}
</script>

<h1>Trash</h1>
{#if items?.length === 0 && notes.length === 0}
	<p class="muted">The trash is empty.</p>
{/if}
<ul>
	{#each items ?? [] as item (item.id)}
		<div class="row">
			<div class="grow"><ItemRow {item} /></div>
			<button onclick={() => restore(item.id)}>Restore</button>
		</div>
	{/each}
	{#each notes as note (note.id)}
		<div class="row">
			<div class="grow"><NoteRow {note} /></div>
			<button onclick={() => restoreWritten(note.id)}>Restore</button>
		</div>
	{/each}
</ul>

<style>
	ul {
		padding: 0;
	}
	.grow {
		flex: 1;
		min-width: 0;
	}
</style>
