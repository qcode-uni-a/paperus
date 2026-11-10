<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { mdiFormatListBulleted } from '@mdi/js';
	import Icon from '#lib/Icon.svelte';
	import { apiHref, createNote, errorMessage } from '#lib/api/client.ts';
	import {
		COLORS,
		KIND_NAMES,
		colorName,
		type AnnotationOut,
		type FileAnnotations
	} from '#lib/annotations/annotations.svelte.ts';
	import { notify } from '#lib/toasts.svelte.ts';

	/** The file's annotations by page: find one, go to it; share one's own
	 * with the group; gather them into a note. */
	let {
		store,
		title,
		go
	}: {
		store: FileAnnotations;
		/** The paper's, for the note. */
		title: string;
		go: (annotation: AnnotationOut) => void;
	} = $props();

	let open = $state(false);
	let words = $state('');
	let colors = $state<string[]>([]);
	let onlyMine = $state(false);
	let panel = $state<HTMLElement>();

	const others = $derived(store.list.some((a) => !a.mine));
	// Zotero's colours first, then others the PDF's own annotations brought.
	const used = $derived(
		[...new Set(store.list.map((a) => a.color))]
			.map((value) => ({ value, name: colorName(value) }))
			.sort(
				(a, b) =>
					((COLORS.findIndex((c) => c.value === a.value) + 99) % 99) -
					((COLORS.findIndex((c) => c.value === b.value) + 99) % 99)
			)
	);
	const shown = $derived(
		store.list.filter((a) => {
			if (onlyMine && !a.mine) return false;
			if (colors.length && !colors.includes(a.color)) return false;
			const wanted = words.trim().toLowerCase();
			if (!wanted) return true;
			return [a.text, a.comment, ...a.tags, a.author]
				.filter(Boolean)
				.some((t) => t!.toLowerCase().includes(wanted));
		})
	);

	const page = (a: AnnotationOut) => a.page_label ?? String(a.page_index + 1);

	function choose(a: AnnotationOut) {
		if (window.matchMedia('(max-width: 720px)').matches) open = false;
		go(a);
	}

	/** The annotations shown, as Markdown: quotes, comments, pages. */
	function markdown(list: AnnotationOut[]): string {
		const lines = [`# Annotations: ${title}`, ''];
		for (const a of list) {
			const where = `(p. ${page(a)})`;
			if (a.text && ['highlight', 'underline', 'strikeout'].includes(a.kind)) {
				lines.push(`> “${a.text}” ${where}`, '');
			} else if (a.kind === 'text' && a.text) {
				lines.push(`*${a.text}* ${where}`, '');
			} else {
				lines.push(`**${KIND_NAMES[a.kind]}** ${where}`, '');
			}
			if (a.comment) lines.push(a.comment, '');
			if (a.tags.length) lines.push(`Tags: ${a.tags.join(', ')}`, '');
			if (!a.mine) lines.push(`— ${a.author}`, '');
		}
		return lines.join('\n').trim() + '\n';
	}

	async function toNote() {
		const list = shown.filter((a) => a.kind !== 'ink' || a.comment);
		if (!list.length) return;
		const { data, error } = await createNote({
			body: { text: markdown(list), items: [{ item_id: store.itemId }] }
		});
		if (!data) {
			notify({ kind: 'warning', title: 'No note made', text: errorMessage(error) });
			return;
		}
		await goto(resolve('/notes/[id]', { id: data.id }));
	}

	$effect(() => {
		if (!open) return;
		const away = (event: PointerEvent) => {
			const target = event.target as Node;
			if (panel && !panel.contains(target) && !(target as HTMLElement).closest?.('.toggle-list'))
				open = false;
		};
		document.addEventListener('pointerdown', away);
		return () => document.removeEventListener('pointerdown', away);
	});
</script>

<div class="annotations">
	<button
		class="toggle-list"
		class:open
		aria-expanded={open}
		aria-controls="annotation-list"
		title="Annotations"
		onclick={() => (open = !open)}
	>
		<Icon path={mdiFormatListBulleted} size={18} /><span class="count">{store.list.length}</span>
	</button>
	{#if open}
		<section id="annotation-list" class="panel" aria-label="Annotations" bind:this={panel}>
			<div class="filters">
				<input
					type="search"
					bind:value={words}
					placeholder="Find in annotations"
					aria-label="Find in annotations"
				/>
				{#if used.length > 1}
					<div class="colors">
						{#each used as color (color.value)}
							<button
								class="swatch"
								class:chosen={colors.includes(color.value)}
								style:background={color.value}
								aria-pressed={colors.includes(color.value)}
								aria-label="Only {color.name.toLowerCase()}"
								title="Only {color.name.toLowerCase()}"
								onclick={() =>
									(colors = colors.includes(color.value)
										? colors.filter((c) => c !== color.value)
										: [...colors, color.value])}
							></button>
						{/each}
					</div>
				{/if}
				{#if others}
					<label class="mine"><input type="checkbox" bind:checked={onlyMine} /> Only mine</label>
				{/if}
			</div>

			{#if store.list.length === 0}
				<p class="muted empty">
					No annotations yet. Select text to highlight it, or take a tool from the toolbar.
				</p>
			{:else if shown.length === 0}
				<p class="muted empty">None fits.</p>
			{:else}
				<ol>
					{#each shown as a (a.id)}
						<li>
							<button
								class="item"
								class:current={store.selected === a.id}
								style:--mark={a.color}
								onclick={() => choose(a)}
							>
								<span class="meta"
									><span class="kind">{KIND_NAMES[a.kind]}</span>, page {page(a)}{#if !a.mine},
										{a.author}{/if}<span class="visually-hidden">, {colorName(a.color)}</span></span
								>
								{#if a.text}<span class="quote">{a.text}</span>{/if}
								{#if a.comment}<span class="comment">{a.comment}</span>{/if}
								{#if a.tags.length}<span class="tags">{a.tags.join(', ')}</span>{/if}
							</button>
						</li>
					{/each}
				</ol>
			{/if}

			<footer>
				{#if store.canShare}
					<label class="share" title="Everyone who may read this paper sees your annotations of it"
						><input
							type="checkbox"
							checked={store.shared}
							onchange={(event) => store.share(event.currentTarget.checked)}
						/> Show mine to the group</label
					>
				{/if}
				{#if store.list.length}
					<a
						class="download"
						href={apiHref(`/api/files/${store.fileId}/annotated`)}
						download
						title="The PDF with these annotations written in, for any PDF reader"
						>Download with annotations</a
					>
				{/if}
				{#if shown.length}
					<button onclick={toNote}
						>Add note from {shown.length === store.list.length ? 'all' : 'these'}</button
					>
				{/if}
			</footer>
		</section>
	{/if}
</div>

<style>
	.annotations {
		position: relative;
	}
	.toggle-list {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 3px 10px !important;
	}
	.toggle-list.open {
		background: var(--rail);
	}
	.count {
		font-variant-numeric: tabular-nums;
	}
	.panel {
		position: absolute;
		top: calc(100% + 8px);
		right: 0;
		z-index: 6;
		display: grid;
		grid-template-rows: auto 1fr auto;
		width: min(380px, calc(100vw - 32px));
		max-height: min(72vh, 680px);
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		box-shadow: var(--shadow);
		white-space: normal;
		overscroll-behavior: contain;
	}
	.filters {
		display: grid;
		gap: 8px;
		padding: 10px;
		border-bottom: 1px solid var(--rule);
	}
	.colors {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.swatch {
		width: 20px;
		height: 20px;
		padding: 0 !important;
		border: 2px solid transparent;
		border-radius: 50%;
	}
	.swatch.chosen {
		border-color: var(--ink);
	}
	.mine {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: var(--step--1);
	}
	.mine input {
		width: auto;
	}
	ol {
		margin: 0;
		padding: 6px;
		overflow-y: auto;
		list-style: none;
	}
	.item {
		display: grid;
		gap: 3px;
		width: 100%;
		padding: 8px 10px;
		border: none;
		border-left: 4px solid var(--mark);
		border-radius: 0 8px 8px 0;
		background: none;
		font-weight: normal;
		text-align: left;
	}
	.item:hover,
	.item.current {
		background: var(--rail);
	}
	.meta {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.kind {
		font-weight: 600;
	}
	.quote {
		display: -webkit-box;
		overflow: hidden;
		-webkit-line-clamp: 3;
		line-clamp: 3;
		-webkit-box-orient: vertical;
		font-family: var(--serif);
	}
	.comment {
		white-space: pre-wrap;
	}
	.tags {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.empty {
		margin: 0;
		padding: 16px;
	}
	footer {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
		padding: 10px;
		border-top: 1px solid var(--rule);
	}
	.share {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: var(--step--1);
	}
	.share input {
		width: auto;
	}
	.download {
		font-size: var(--step--1);
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
	}
</style>
