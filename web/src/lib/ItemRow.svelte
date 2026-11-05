<script lang="ts">
	import type { Snippet } from 'svelte';
	import { resolve } from '$app/paths';
	import type { Item } from '#lib/api/client.ts';
	import { shortAuthors, typeName } from '#lib/format.ts';
	import { isShared } from '#lib/organize.svelte.ts';
	import SharedIcon from '#lib/SharedIcon.svelte';
	import StarButton from '#lib/StarButton.svelte';

	/** ``note``: a line above the title, e.g. why it is in a list. */
	let { item, note, actions }: { item: Item; note?: string; actions?: Snippet } = $props();

	const authors = $derived(shortAuthors(item.authors));
</script>

<li>
	<span class="corner"
		>{#if isShared(item.library_id)}<SharedIcon owner={item.library_id} />{/if}<StarButton
			item={item.id}
			starred={item.favourite ?? false}
			size={16}
		/></span
	>
	{#if note}<span class="note">{note}</span>{/if}
	<a class="title" href={resolve('/items/[id]', { id: item.id })}>{item.title}</a>
	<p class="reference">
		{#if authors || item.year || item.container_title}<span
				>{#if authors}{authors}{/if}{#if item.year}{authors
						? ' '
						: ''}({item.year}){/if}{#if item.container_title}{authors || item.year ? '. ' : ''}<em
						>{item.container_title}</em
					>{/if}</span
			>{/if}
		<span class="badge">{typeName(item.type)}</span>

		{#each item.tags as tag (tag.id)}<span class="tag" data-tag-color={tag.color}>{tag.name}</span
			>{/each}
		{#if item.processing}<span class="badge reading">Looking up details…</span>{/if}
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
		gap: 4px;
	}
	.note {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.corner {
		position: absolute;
		top: 12px;
		right: 0;
		display: flex;
		align-items: center;
		gap: 2px;
	}
	/* Room for the corner's icons. */
	.title {
		padding-right: 56px;
	}
	.title {
		font-family: var(--serif);
		font-size: var(--step-1);
		font-weight: 600;
		line-height: 1.3;
		color: var(--ink);
		text-decoration: none;
		max-width: 70ch;
	}
	.title:hover {
		color: var(--royal);
		text-decoration: underline;
	}
	p {
		margin: 0;
	}
	.reference {
		color: var(--muted);
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 4px 10px;
	}
	.tag {
		font-size: var(--step--1);
		line-height: 1.6;
		padding: 0 8px;
		border-radius: 999px;
		border: 1px solid var(--tag-bg, var(--rule));
		background: var(--tag-bg, none);
		color: var(--tag-ink, var(--muted));
	}
	.reading {
		color: var(--royal);
	}
</style>
