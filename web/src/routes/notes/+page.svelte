<script lang="ts">
	import { untrack } from 'svelte';
	import { listNotes } from '#lib/api/client.ts';
	import type { NoteOut } from '#lib/api/generated/types.gen.ts';
	import NoteRow from '#lib/NoteRow.svelte';
	import { startNote } from '#lib/notes.ts';
	import { loadOrganize } from '#lib/organize.svelte.ts';

	const PAGE = 50;
	let notes = $state<NoteOut[]>([]);
	let total = $state<number | null>(null);
	let error = $state('');

	async function load(offset = 0) {
		const { data, response } = await listNotes({ query: { limit: PAGE, offset } });
		if (!data) return;
		notes = offset ? [...notes, ...data] : data;
		total = Number(response?.headers.get('X-Total-Count') ?? notes.length);
	}

	$effect(() => {
		loadOrganize();
		untrack(() => load());
	});

	async function write() {
		error = (await startNote()) ?? '';
	}
</script>

<svelte:head><title>Notes · paperus</title></svelte:head>

<header class="head">
	<h1>Notes</h1>
	<button class="primary" onclick={write}>New note</button>
</header>
{#if error}<p class="error">{error}</p>{/if}

{#if total === 0}
	<div class="empty">
		<p class="muted">
			Notes are your own writing about papers: summaries, ideas, what the reading group said. Start
			one here, or with “New note” on a paper. They are searched together with the papers.
		</p>
	</div>
{/if}
<ul>
	{#each notes as note (note.id)}<NoteRow {note} />{/each}
</ul>
{#if total !== null && notes.length < total}
	<div class="more"><button onclick={() => load(notes.length)}>Show more</button></div>
{/if}

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 12px;
		margin-bottom: 8px;
	}
	h1 {
		margin: 0;
	}
	.empty p {
		max-width: 60ch;
	}
	ul {
		margin: 0;
		padding: 0;
	}
	.more {
		display: flex;
		justify-content: center;
		padding: 8px 0 24px;
	}
</style>
