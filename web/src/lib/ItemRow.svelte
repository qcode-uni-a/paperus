<script lang="ts">
	import { authorHref } from '#lib/authorLinks.ts';
	import Title from '#lib/Title.svelte';
	import type { Snippet } from 'svelte';
	import { resolve } from '$app/paths';
	import type { Item } from '#lib/api/client.ts';
	import { shortAuthors, typeName } from '#lib/format.ts';
	import { isShared } from '#lib/organize.svelte.ts';
	import FileIcon from '#lib/FileIcon.svelte';
	import SharedIcon from '#lib/SharedIcon.svelte';
	import StarButton from '#lib/StarButton.svelte';
	import { none } from '#lib/transitions.ts';
	import type { TransitionConfig } from 'svelte/transition';
	import { writtenName } from '#lib/names.svelte.ts';
	import type { Selection } from '#lib/selection.svelte.ts';

	/** ``note``: a line above the title, e.g. why it is in a list;
	 * ``leave``: how the row goes when it leaves its list; ``done``: shown
	 * as just done (e.g. its PDF saved), before it leaves; ``selection``:
	 * the list's picked rows (a box to pick this one). */
	let {
		item,
		note,
		actions,
		leave = none,
		done = false,
		selection
	}: {
		item: Item;
		note?: string;
		actions?: Snippet;
		leave?: (node: Element) => TransitionConfig;
		done?: boolean;
		selection?: Selection;
	} = $props();

	const picked = $derived(selection?.has(item.id) ?? false);

	/** While picking, a click on the row (its title too) picks it; other
	 * links and buttons do what they do. */
	function pickRow(event: MouseEvent) {
		if (!selection?.active) return;
		const target = event.target as HTMLElement;
		if (target.closest('input, button, a:not(.title)')) return;
		event.preventDefault();
		selection.toggle(item.id, event.shiftKey);
	}

	const authors = $derived(shortAuthors(item.authors));
	// The names shown (as shortAuthors: up to three, else two and "et al.").
	const shown = $derived(item.authors.length <= 3 ? item.authors : item.authors.slice(0, 2));
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions (the box is the control; the row only a larger target) -->
<li
	out:leave
	class:done
	class:picking={selection?.active}
	class:picked
	data-place={item.id}
	onclick={pickRow}
>
	{#if selection}<input
			type="checkbox"
			class="pick"
			checked={picked}
			aria-label="Select “{item.title}”"
			onclick={(event) => selection.toggle(item.id, event.shiftKey)}
		/>{/if}
	<span class="corner"
		><FileIcon files={item.files ?? []} />{#if isShared(item.library_id)}<SharedIcon
				owner={item.library_id}
			/>{/if}<StarButton item={item.id} starred={item.favourite ?? false} size={16} /></span
	>
	{#if note}<span class="note">{note}</span>{/if}
	<a class="title" href={resolve('/items/[id]', { id: item.id })}><Title text={item.title} /></a>
	<p class="reference">
		{#if authors || item.year || item.container_title}<span
				>{#if authors}{#each shown as author, i (i)}{i === 0
							? ''
							: i === item.authors.length - 1
								? ' and '
								: ', '}<a
							class="person"
							href={authorHref(item, i)}
							title="Papers by {writtenName(author)}">{author.split(',')[0].trim()}</a
						>{/each}{#if item.authors.length > 3}{' '}et al.{/if}{/if}{#if item.year}{authors
						? ' '
						: ''}({item.year}){/if}{#if item.container_title}{authors || item.year ? '. ' : ''}<em
						>{item.container_title}</em
					>{/if}</span
			>{/if}
		<span class="badge">{typeName(item.type)}</span>

		{#each item.tags.filter((t) => t.source !== 'automatic') as tag (tag.id)}<a
				class="tag"
				href="{resolve('/')}?tag={tag.id}"
				title="Papers tagged {tag.name}"
				data-tag-color={tag.color}>{tag.name}</a
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
		/* Never wider than the list: a long word (a LaTeX formula, a URL)
		   breaks instead of widening the page. */
		grid-template-columns: minmax(0, 1fr);
		gap: 4px;
		overflow-wrap: anywhere;
		transition: outline-color 0.25s;
		outline: 1.5px solid transparent;
		outline-offset: -1.5px;
		border-radius: 12px;
	}
	/* As the merge window marks what stays: a green outline, with room
	   inside (the text stays where it was). */
	li.done {
		margin-inline: -12px;
		padding-inline: 12px;
		outline-color: var(--success);
		border-bottom-color: transparent;
	}
	/* The box to pick the row: in the margin, seen on hover (or while
	   picking); on narrow screens only while picking, inside the row. */
	.pick {
		position: absolute;
		top: 17px;
		left: -34px;
		width: 18px;
		height: 18px;
		margin: 0;
		opacity: 0;
		accent-color: var(--royal);
		cursor: pointer;
	}
	li:hover .pick,
	.pick:focus-visible,
	li.picking .pick {
		opacity: 1;
	}
	li.picking {
		cursor: pointer;
	}
	li.picked {
		background: color-mix(in srgb, var(--royal) 7%, transparent);
		box-shadow: -40px 0 0 color-mix(in srgb, var(--royal) 7%, transparent);
	}
	@media (max-width: 760px), (pointer: coarse) {
		.pick {
			display: none;
		}
		li.picking {
			padding-left: 34px;
		}
		li.picking .pick {
			display: block;
			left: 4px;
		}
		li.picked {
			box-shadow: none;
		}
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
		padding-right: 84px;
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
	a.tag {
		text-decoration: none;
	}
	a.tag:hover {
		border-color: var(--royal);
	}
	.person {
		color: inherit;
		text-decoration: none;
	}
	.person:hover {
		color: var(--royal);
		text-decoration: underline;
	}
	.reading {
		color: var(--royal);
	}
</style>
