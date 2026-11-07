<script lang="ts">
	import { resolve } from '$app/paths';
	import { listSimilar } from '#lib/api/client.ts';
	import type { SimilarItem } from '#lib/api/generated/types.gen.ts';
	import { shortAuthors } from '#lib/format.ts';
	import Title from '#lib/Title.svelte';

	/** Papers closest in meaning to this one (by their full text), loaded
	 * when opened. */
	let { item }: { item: string } = $props();

	let similar = $state<SimilarItem[] | null>(null);
	let open = $state(false);

	$effect(() => {
		const about = item;
		similar = null;
		if (!open) return;
		listSimilar({ path: { item_id: about }, query: { limit: 8 } }).then(({ data }) => {
			if (about === item) similar = data ?? [];
		});
	});

	const byline = (paper: SimilarItem) =>
		[shortAuthors(paper.authors), paper.year ? `(${paper.year})` : ''].filter(Boolean).join(' ');
</script>

<details bind:open>
	<summary>Similar papers</summary>
	{#if similar === null}
		<p class="muted">Looking…</p>
	{:else if similar.length === 0}
		<p class="muted">None yet: papers are compared by their text, once it has been read.</p>
	{:else}
		<ul>
			{#each similar as paper (paper.id)}
				<li>
					<a href={resolve('/items/[id]', { id: paper.id })}><Title text={paper.title} /></a>
					{#if byline(paper)}<span class="by">{byline(paper)}</span>{/if}
				</li>
			{/each}
		</ul>
	{/if}
</details>

<style>
	details {
		margin-top: 10px;
		font-size: var(--step--1);
	}
	summary {
		cursor: pointer;
		color: var(--muted);
		width: fit-content;
	}
	summary:hover {
		color: inherit;
	}
	ul {
		margin: 8px 0 0;
		padding: 0;
		list-style: none;
		display: grid;
		gap: 6px;
	}
	li {
		display: grid;
		gap: 1px;
		min-width: 0;
	}
	a {
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.by {
		color: var(--muted);
	}
	p {
		margin: 8px 0 0;
	}
</style>
