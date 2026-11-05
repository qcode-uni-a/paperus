<script lang="ts">
	import { resolve } from '$app/paths';
	import type { Item } from '#lib/api/client.ts';
	import { shortAuthors, typeName } from '#lib/format.ts';
	import { libraryName, severalLibraries } from '#lib/organize.svelte.ts';

	let { item }: { item: Item } = $props();

	const authors = $derived(shortAuthors(item.authors));
</script>

<li>
	<a class="title" href={resolve('/items/[id]', { id: item.id })}>{item.title}</a>
	<p class="reference">
		<span
			>{#if authors}{authors}{/if}{#if item.year}{authors
					? ' '
					: ''}({item.year}){/if}{#if item.container_title}{authors || item.year ? '. ' : ''}<em
					>{item.container_title}</em
				>{/if}</span
		>
		<span class="badge">{typeName(item.type)}</span>
		{#if severalLibraries()}<span class="library" title="Library"
				>{libraryName(item.library_id)}</span
			>{/if}
		{#each item.tags as tag (tag.id)}<span class="tag" data-tag-color={tag.color}>{tag.name}</span
			>{/each}
		{#if item.processing}<span class="badge reading">Looking up details…</span>{/if}
	</p>
</li>

<style>
	li {
		list-style: none;
		padding: 14px 0 16px;
		border-bottom: 1px solid var(--rule);
		display: grid;
		gap: 4px;
	}
	.library {
		font-size: var(--step--1);
		color: var(--muted);
	}
	.library::before {
		content: '';
		display: inline-block;
		width: 0.7em;
		height: 0.55em;
		margin-right: 5px;
		border: 1.5px solid currentColor;
		border-top-width: 3px;
		border-radius: 2px;
		vertical-align: 0.02em;
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
