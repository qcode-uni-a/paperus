<script lang="ts">
	import {
		mdiCommentPlusOutline,
		mdiFormatStrikethroughVariant,
		mdiFormatUnderline
	} from '@mdi/js';
	import Icon from '#lib/Icon.svelte';
	import {
		COLORS,
		type AnnotationKind,
		type FileAnnotations
	} from '#lib/annotations/annotations.svelte.ts';
	import { boxToRect, lineBoxes, type Viewport } from '#lib/annotations/geometry.ts';

	/** Over text selected on a page: highlight it in a colour, underline or
	 * strike it through, or comment on it (a highlight with a comment). */
	let {
		store,
		root,
		viewportOf,
		labelOf
	}: {
		store: FileAnnotations;
		/** The viewer: only selections in its pages. */
		root: HTMLElement | undefined;
		viewportOf: (page: number) => Viewport | undefined;
		labelOf: (index: number) => string | null;
	} = $props();

	let shown = $state<{ x: number; y: number; page: number; range: Range } | null>(null);

	function check() {
		const selection = window.getSelection();
		if (store.tool !== 'select' || !selection || selection.isCollapsed || !selection.rangeCount) {
			shown = null;
			return;
		}
		const range = selection.getRangeAt(0);
		const start = range.startContainer.parentElement?.closest('.page');
		if (
			!start ||
			!root?.contains(start) ||
			!start.querySelector('.textLayer')?.contains(range.startContainer)
		) {
			shown = null;
			return;
		}
		const page = Number(start.id.replace('page-', ''));
		const bounds = range.getBoundingClientRect();
		shown = {
			x: Math.min(Math.max(bounds.left + bounds.width / 2, 150), window.innerWidth - 150),
			y: Math.max(bounds.top - 8, 60),
			page,
			range
		};
	}

	$effect(() => {
		let timer = 0;
		const later = () => {
			clearTimeout(timer);
			timer = window.setTimeout(check, 150);
		};
		document.addEventListener('selectionchange', later);
		window.addEventListener('scroll', later, { passive: true });
		return () => {
			clearTimeout(timer);
			document.removeEventListener('selectionchange', later);
			window.removeEventListener('scroll', later);
		};
	});

	async function make(kind: AnnotationKind, color: string, open = false) {
		if (!shown) return;
		const { page, range } = shown;
		const viewport = viewportOf(page);
		const node = document.getElementById(`page-${page}`);
		if (!viewport || !node) return;
		// The page's end of a selection running on into the next page.
		const ownEnd = node.querySelector('.textLayer');
		const part = range.cloneRange();
		if (ownEnd && !ownEnd.contains(part.endContainer)) part.setEndAfter(ownEnd.lastChild ?? ownEnd);
		const boxes = lineBoxes(part.getClientRects(), node.getBoundingClientRect());
		const text = part.toString().replace(/\s+/g, ' ').trim();
		window.getSelection()?.removeAllRanges();
		shown = null;
		if (!boxes.length || !text) return;
		await store.add(
			{
				kind,
				page_index: page - 1,
				page_label: labelOf(page - 1),
				color,
				text,
				position: { rects: boxes.map((b) => boxToRect(viewport, b)) }
			},
			open
		);
	}
</script>

{#if shown}
	<div
		class="menu"
		style:left="{shown.x}px"
		style:top="{shown.y}px"
		role="toolbar"
		aria-label="Annotate the selection"
	>
		{#each COLORS as color (color.value)}
			<button
				class="swatch"
				style:background={color.value}
				aria-label="Highlight {color.name.toLowerCase()}"
				title="Highlight {color.name.toLowerCase()}"
				onpointerdown={(event) => event.preventDefault()}
				onclick={() => make('highlight', color.value)}
			></button>
		{/each}
		<span class="divider"></span>
		<button
			class="tool"
			aria-label="Underline"
			title="Underline"
			onpointerdown={(event) => event.preventDefault()}
			onclick={() => make('underline', store.color)}
			><Icon path={mdiFormatUnderline} size={18} /></button
		>
		<button
			class="tool"
			aria-label="Strike through"
			title="Strike through"
			onpointerdown={(event) => event.preventDefault()}
			onclick={() => make('strikeout', store.color)}
			><Icon path={mdiFormatStrikethroughVariant} size={18} /></button
		>
		<button
			class="tool"
			aria-label="Comment"
			title="Highlight and comment"
			onpointerdown={(event) => event.preventDefault()}
			onclick={() => make('highlight', store.color, true)}
			><Icon path={mdiCommentPlusOutline} size={18} /></button
		>
	</div>
{/if}

<style>
	.menu {
		position: fixed;
		z-index: 25;
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 6px 8px;
		border: 1px solid var(--rule);
		border-radius: 999px;
		background: var(--surface);
		box-shadow: var(--shadow);
		transform: translate(-50%, -100%);
	}
	.swatch {
		width: 22px;
		height: 22px;
		padding: 0;
		border: none;
		border-radius: 50%;
		box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.15);
	}
	.swatch:hover {
		transform: scale(1.15);
	}
	.divider {
		width: 1px;
		height: 20px;
		margin: 0 2px;
		background: var(--rule);
	}
	.tool {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		padding: 0;
		border: none;
		border-radius: 50%;
		background: none;
	}
	.tool:hover {
		background: var(--rail);
	}
	@media (prefers-reduced-motion: no-preference) {
		.swatch {
			transition: transform 80ms;
		}
	}
</style>
