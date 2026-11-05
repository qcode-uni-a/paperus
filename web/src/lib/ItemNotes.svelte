<script lang="ts">
	import { resolve } from '$app/paths';
	import { listNotes } from '#lib/api/client.ts';
	import type { NoteOut } from '#lib/api/generated/types.gen.ts';
	import { startNote } from '#lib/notes.ts';

	/** A paper's notes in one line, with a button for a new one. */
	let { item }: { item: string } = $props();

	let notes = $state<NoteOut[]>([]);
	let error = $state('');

	$effect(() => {
		const about = item;
		listNotes({ query: { item: about, limit: 200 } }).then(({ data }) => {
			if (about === item) notes = data ?? [];
		});
	});

	async function write() {
		error = (await startNote({ items: [item] })) ?? '';
	}
</script>

<div class="notes">
	{#each notes as note (note.id)}
		<a class="note" href={resolve('/notes/[id]', { id: note.id })}>
			<svg viewBox="0 0 24 24" aria-hidden="true"
				><path d="M6 3.5h8.5L19 8v12.5H6zM14 3.5V8.5h5M9 12.5h7M9 16h5" /></svg
			>
			<span>{note.title || 'Untitled note'}</span>
		</a>
	{/each}
	<button class="new" onclick={write}>+ Note</button>
	{#if error}<span class="error">{error}</span>{/if}
</div>

<style>
	.notes {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px 8px;
		margin-top: 8px;
		font-size: var(--step--1);
	}
	.note {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		max-width: 100%;
		padding: 2px 10px;
		border: 1px solid var(--rule);
		border-radius: 999px;
		color: var(--ink);
		text-decoration: none;
	}
	.note span {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.note:hover {
		border-color: var(--royal);
	}
	svg {
		flex: none;
		width: 14px;
		height: 14px;
		fill: none;
		stroke: var(--royal);
		stroke-width: 1.8;
		stroke-linejoin: round;
	}
	.new {
		padding: 2px 10px;
		border: 1px dashed var(--rule);
		border-radius: 999px;
		background: none;
		color: var(--royal);
	}
</style>
