<script lang="ts">
	import NoteIcon from '#lib/NoteIcon.svelte';
	import type { Snippet } from 'svelte';
	import { resolve } from '$app/paths';
	import type { NoteOut } from '#lib/api/generated/types.gen.ts';
	import { ago } from '#lib/format.ts';
	import { isShared } from '#lib/organize.svelte.ts';
	import SharedIcon from '#lib/SharedIcon.svelte';

	/** A note in a list; ``about`` false hides the papers it is about (on a paper's page). */
	let {
		note,
		about = true,
		actions
	}: { note: NoteOut; about?: boolean; actions?: Snippet } = $props();
</script>

<li>
	{#if isShared(note.library_id)}<span class="corner"><SharedIcon owner={note.library_id} /></span
		>{/if}
	<a class="title" href={resolve('/notes/[id]', { id: note.id })}>
		<NoteIcon size={18} />
		<span>{note.title || 'Untitled note'}</span>
	</a>
	{#if note.excerpt}<p class="excerpt">{note.excerpt}</p>{/if}
	<p class="meta">
		{#if about && note.items.length}
			<span
				>About {#each note.items as paper, i (paper.item_id)}{i ? ', ' : ''}<a
						href={resolve('/items/[id]', { id: paper.item_id })}>{paper.title}</a
					>{/each}</span
			>
		{/if}
		<span>{note.changed_by ? `${note.changed_by}, ` : ''}{ago(note.changed_at)}</span>
	</p>
	{#if actions}<div class="actions">{@render actions()}</div>{/if}
</li>

<style>
	.actions {
		margin-top: 6px;
	}
	li {
		position: relative;
		list-style: none;
		padding: 14px 0 16px;
		border-bottom: 1px solid var(--rule);
		display: grid;
		/* Never wider than the list (see ItemRow). */
		grid-template-columns: minmax(0, 1fr);
		gap: 4px;
		overflow-wrap: anywhere;
	}
	.corner {
		position: absolute;
		top: 16px;
		right: 0;
		display: flex;
	}
	.title {
		padding-right: 32px;
		display: inline-flex;
		align-items: baseline;
		gap: 8px;
		max-width: 70ch;
		font-family: var(--serif);
		font-size: var(--step-1);
		font-weight: 600;
		line-height: 1.3;
		color: var(--ink);
		text-decoration: none;
	}
	.title span {
		min-width: 0;
	}
	.title:hover span {
		color: var(--royal);
		text-decoration: underline;
	}
	p {
		margin: 0;
		max-width: 70ch;
	}
	.excerpt {
		color: var(--ink);
		overflow: hidden;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 14px;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.meta a {
		color: inherit;
	}
</style>
