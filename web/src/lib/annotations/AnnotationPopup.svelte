<script lang="ts">
	import { mdiClose, mdiDeleteOutline } from '@mdi/js';
	import Icon from '#lib/Icon.svelte';
	import {
		COLORS,
		FONT_SIZES,
		KIND_NAMES,
		type AnnotationOut,
		type FileAnnotations
	} from '#lib/annotations/annotations.svelte.ts';
	import type { Box } from '#lib/annotations/geometry.ts';

	/** One annotation: its comment, colour and tags (and for words on the
	 * page, the words and their size); others' only to read. Under the
	 * annotation on a large screen, at the bottom on a phone. */
	let {
		store,
		annotation,
		box,
		pageWidth
	}: {
		store: FileAnnotations;
		annotation: AnnotationOut;
		box: Box;
		pageWidth: number;
	} = $props();

	const WIDTH = 320;
	let comment = $state('');
	let words = $state('');
	let tag = $state('');
	let commentField = $state<HTMLTextAreaElement>();

	// Start from the annotation each time another one opens.
	$effect(() => {
		void annotation.id;
		comment = annotation.comment ?? '';
		words = annotation.text ?? '';
		tag = '';
	});
	// A new note or area: straight to its comment; words: to the words.
	$effect(() => {
		if (!annotation?.mine) return;
		const fresh = Date.now() - new Date(annotation.created_at).getTime() < 3000;
		if (fresh && !annotation.comment && annotation.kind !== 'text') commentField?.focus();
	});

	const left = $derived(Math.max(8, Math.min(box.left, pageWidth - WIDTH - 8)));
	const top = $derived(box.top + box.height + 10);
	const marksText = $derived(['highlight', 'underline', 'strikeout'].includes(annotation.kind));

	function save() {
		// Also on blur while the popup closes: then it is gone.
		if (!annotation) return;
		const changes: { comment?: string; text?: string } = {};
		if (comment !== (annotation.comment ?? '')) changes.comment = comment;
		if (annotation.kind === 'text' && words !== (annotation.text ?? '')) changes.text = words;
		if (Object.keys(changes).length) store.change(annotation.id, changes);
	}

	function close() {
		if (annotation.mine) save();
		store.selected = null;
	}

	function addTag() {
		const name = tag.trim();
		tag = '';
		if (name && !annotation.tags.includes(name))
			store.change(annotation.id, { tags: [...annotation.tags, name] });
	}

	function key(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			event.preventDefault();
			close();
		}
	}
</script>

<div
	class="popup"
	style:left="{left}px"
	style:top="{top}px"
	style:--mark={annotation.color}
	role="dialog"
	aria-label={KIND_NAMES[annotation.kind]}
	tabindex="-1"
	onkeydown={key}
	onpointerdown={(event) => event.stopPropagation()}
>
	<header>
		<span class="dot" aria-hidden="true"></span>
		<strong>{KIND_NAMES[annotation.kind]}</strong>
		<span class="muted"
			>page {annotation.page_label ?? annotation.page_index + 1}{#if !annotation.mine}, by {annotation.author}{/if}{#if annotation.imported},
				from the PDF{/if}</span
		>
		<button class="icon" aria-label="Close" onclick={close}
			><Icon path={mdiClose} size={18} /></button
		>
	</header>

	{#if marksText && annotation.text}
		<blockquote>{annotation.text}</blockquote>
	{/if}

	{#if annotation.mine}
		{#if annotation.kind === 'text'}
			<label class="field"
				>Text <textarea bind:value={words} rows="3" onblur={save} placeholder="Words on the page"
				></textarea></label
			>
			<label class="inline"
				>Size <select
					value={annotation.position.font_size ?? 12}
					onchange={(event) =>
						store.change(annotation.id, {
							position: {
								...annotation.position,
								font_size: Number((event.currentTarget as HTMLSelectElement).value)
							}
						})}
				>
					{#each FONT_SIZES as size (size)}<option value={size}>{size} pt</option>{/each}
				</select></label
			>
		{/if}
		<label class="field"
			>Comment <textarea
				bind:this={commentField}
				bind:value={comment}
				rows="3"
				onblur={save}
				placeholder="Your thoughts"></textarea></label
		>
		<div class="colors" role="radiogroup" aria-label="Colour">
			{#each COLORS as color (color.value)}
				<button
					class="swatch"
					class:chosen={annotation.color === color.value}
					style:background={color.value}
					role="radio"
					aria-checked={annotation.color === color.value}
					aria-label={color.name}
					title={color.name}
					onclick={() => store.change(annotation.id, { color: color.value })}
				></button>
			{/each}
		</div>
		<div class="tags">
			{#each annotation.tags as name (name)}
				<span class="tag"
					>{name}<button
						aria-label="Remove tag {name}"
						onclick={() =>
							store.change(annotation.id, { tags: annotation.tags.filter((t) => t !== name) })}
						>×</button
					></span
				>
			{/each}
			<input
				bind:value={tag}
				placeholder="Add a tag"
				aria-label="Add a tag"
				onkeydown={(event) => {
					if (event.key === 'Enter') {
						event.preventDefault();
						addTag();
					}
				}}
				onblur={addTag}
			/>
		</div>
		<footer>
			<button class="delete" onclick={() => store.remove(annotation.id)}
				><Icon path={mdiDeleteOutline} size={18} />Delete</button
			>
		</footer>
	{:else}
		{#if annotation.kind === 'text' && annotation.text}<p class="words">{annotation.text}</p>{/if}
		{#if annotation.comment}<p class="comment">{annotation.comment}</p>{/if}
		{#if annotation.tags.length}
			<div class="tags">
				{#each annotation.tags as name (name)}<span class="tag">{name}</span>{/each}
			</div>
		{/if}
	{/if}
</div>

<style>
	.popup {
		position: absolute;
		z-index: 5;
		display: grid;
		gap: 10px;
		width: 320px;
		max-width: calc(100% - 16px);
		padding: 12px 14px;
		border: 1px solid var(--rule);
		border-top: 4px solid var(--mark);
		border-radius: 10px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
		pointer-events: auto;
		font-size: var(--step--1);
		text-align: left;
		cursor: auto;
	}
	header {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	header .muted {
		flex: 1;
		min-width: 0;
	}
	.dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--mark);
	}
	.icon {
		display: grid;
		place-items: center;
		width: 28px;
		height: 28px;
		padding: 0;
		border: none;
		background: none;
	}
	blockquote {
		margin: 0;
		padding: 2px 0 2px 10px;
		border-left: 3px solid var(--mark);
		font-family: var(--serif);
		max-height: 7.5em;
		overflow-y: auto;
	}
	.field {
		display: grid;
		gap: 4px;
		font-weight: 600;
	}
	.field textarea {
		font-weight: 400;
		resize: vertical;
	}
	.inline {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.inline select {
		width: auto;
	}
	.colors {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.swatch {
		width: 24px;
		height: 24px;
		padding: 0;
		border: 2px solid transparent;
		border-radius: 50%;
		box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.15);
	}
	.swatch.chosen {
		border-color: var(--ink);
	}
	.tags {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px;
	}
	.tag {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		padding: 0 4px 0 8px;
		border-radius: 999px;
		background: var(--rail);
	}
	.tag button {
		padding: 0 4px;
		border: none;
		background: none;
		line-height: 1.4;
	}
	.tags input {
		flex: 1 1 8rem;
		width: auto;
		padding: 4px 8px;
	}
	footer {
		display: flex;
		justify-content: flex-end;
	}
	.delete {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 4px 12px;
		border-color: var(--danger);
		color: var(--danger);
	}
	.words,
	.comment {
		margin: 0;
		white-space: pre-wrap;
	}
	/* On a phone: a sheet at the bottom of the screen. */
	@media (max-width: 720px) {
		.popup {
			position: fixed;
			left: 8px !important;
			right: 8px;
			top: auto !important;
			bottom: 8px;
			width: auto;
			max-width: none;
			max-height: 60vh;
			overflow-y: auto;
			z-index: 30;
		}
	}
</style>
