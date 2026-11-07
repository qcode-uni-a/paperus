<script lang="ts">
	import {
		emptyTrash,
		listItems,
		listNotes,
		restoreItem,
		restoreNote,
		type Item
	} from '#lib/api/client.ts';
	import { notify } from '#lib/toasts.svelte.ts';
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

	/** Everything here one may change, deleted for good (others' stays). */
	async function emptyAll() {
		const count = (items?.length ?? 0) + notes.length;
		if (
			!confirm(
				`Delete ${count} ${count === 1 ? 'thing' : 'things'} in the trash for good? ` +
					'This cannot be undone. (Things of groups where you only read stay.)'
			)
		)
			return;
		const { data } = await emptyTrash();
		if (data)
			notify({
				kind: 'success',
				title: 'Trash emptied',
				text: `${data.items} papers, ${data.notes} notes and ${data.files} files deleted for good.`
			});
		await load();
	}

	async function restore(id: string) {
		await restoreItem({ path: { item_id: id } });
		await load();
	}

	async function restoreWritten(id: string) {
		await restoreNote({ path: { note_id: id } });
		await load();
	}
</script>

<header class="head">
	<h1>Trash</h1>
	{#if (items?.length ?? 0) + notes.length > 0}
		<button class="danger-button" onclick={emptyAll}>Empty trash</button>
	{/if}
</header>
{#if items?.length === 0 && notes.length === 0}
	<p class="muted">The trash is empty.</p>
{/if}
<ul>
	{#each items ?? [] as item (item.id)}
		<ItemRow {item}>
			{#snippet actions()}<button onclick={() => restore(item.id)}>Restore</button>{/snippet}
		</ItemRow>
	{/each}
	{#each notes as note (note.id)}
		<NoteRow {note}>
			{#snippet actions()}<button onclick={() => restoreWritten(note.id)}>Restore</button>{/snippet}
		</NoteRow>
	{/each}
</ul>

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
	}
	.danger-button {
		border-color: var(--danger);
		color: var(--danger);
	}
	ul {
		padding: 0;
	}
</style>
