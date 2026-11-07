<script lang="ts">
	import { mdiChevronRight, mdiTableOfContents } from '@mdi/js';
	import Icon from '#lib/Icon.svelte';
	import type { Section } from '#lib/pdfContents.ts';

	/** The chapters of the PDF in a panel over the pages: where one is (the
	 * chapter being read is marked), and a click jumps to another. */
	let {
		sections,
		current,
		go
	}: {
		sections: Section[];
		/** Index of the chapter being read, or -1 before the first. */
		current: number;
		go: (section: Section) => void;
	} = $props();

	let open = $state(false);
	let panel = $state<HTMLElement>();
	let toggle = $state<HTMLButtonElement>();

	const reading = $derived(current >= 0 ? sections[current] : null);

	/** Index of each section's parent (-1 for chapters). */
	const parents = $derived.by(() => {
		const stack: number[] = [];
		return sections.map((section, index) => {
			while (stack.length && sections[stack.at(-1)!].depth >= section.depth) stack.pop();
			const parent = stack.at(-1) ?? -1;
			stack.push(index);
			return parent;
		});
	});
	const hasChildren = $derived(new Set(parents.filter((parent) => parent >= 0)));

	/** Folded chapters and sections: at first all but the one being read. */
	let folded = $state<Set<number>>(new Set());
	let foldedFor = $state<Section[] | null>(null);
	$effect(() => {
		if (foldedFor === sections) return;
		foldedFor = sections;
		folded = new Set(hasChildren);
	});

	function ancestors(index: number): number[] {
		const found = [];
		for (let at = parents[index] ?? -1; at >= 0; at = parents[at]) found.push(at);
		return found;
	}

	/** Shown unless a chapter or section above it is folded. */
	const visible = (index: number) => ancestors(index).every((at) => !folded.has(at));

	function fold(index: number) {
		const next = new Set(folded);
		if (next.has(index)) next.delete(index);
		else next.add(index);
		folded = next;
	}

	function foldAll(all: boolean) {
		folded = all ? new Set(hasChildren) : new Set();
	}

	$effect(() => {
		if (!open) return;
		// The chapter being read unfolded and in view when the panel opens.
		const opened = ancestors(current).filter((at) => folded.has(at));
		if (opened.length) folded = new Set([...folded].filter((at) => !opened.includes(at)));
		requestAnimationFrame(() =>
			panel?.querySelector('[aria-current="true"]')?.scrollIntoView({ block: 'center' })
		);
		const away = (event: PointerEvent) => {
			const target = event.target as Node;
			if (!panel?.contains(target) && !toggle?.contains(target)) open = false;
		};
		const escape = (event: KeyboardEvent) => {
			if (event.key === 'Escape') {
				open = false;
				toggle?.focus();
			}
		};
		document.addEventListener('pointerdown', away);
		document.addEventListener('keydown', escape);
		return () => {
			document.removeEventListener('pointerdown', away);
			document.removeEventListener('keydown', escape);
		};
	});

	function choose(section: Section) {
		go(section);
		// On a phone the panel covers the page: out of the way.
		if (window.matchMedia('(max-width: 700px)').matches) open = false;
	}
</script>

<div class="contents">
	<button
		bind:this={toggle}
		class="toggle"
		class:open
		aria-expanded={open}
		aria-controls="pdf-contents"
		onclick={() => (open = !open)}
		title="Contents"
	>
		<Icon path={mdiTableOfContents} size={18} />
		<span class="reading">{reading?.title ?? 'Contents'}</span>
	</button>

	{#if open}
		<nav id="pdf-contents" class="panel" aria-label="Contents of the PDF" bind:this={panel}>
			{#if hasChildren.size}
				<div class="folding">
					<button onclick={() => foldAll(false)}>Unfold all</button>
					<button onclick={() => foldAll(true)}>Fold all</button>
				</div>
			{/if}
			<ol>
				{#each sections as section, index (index)}
					{#if visible(index)}
						<li style:--depth={section.depth} class:chapter={section.depth === 0}>
							{#if hasChildren.has(index)}
								<button
									class="fold"
									class:folded={folded.has(index)}
									aria-expanded={!folded.has(index)}
									aria-label="{folded.has(index) ? 'Unfold' : 'Fold'} {section.title}"
									onclick={() => fold(index)}
								>
									<Icon path={mdiChevronRight} size={16} />
								</button>
							{:else if hasChildren.size}
								<span class="fold-space"></span>
							{/if}
							<button
								class="go"
								class:current={index === current ||
									(folded.has(index) && ancestors(current).includes(index))}
								aria-current={index === current}
								onclick={() => choose(section)}
							>
								<span class="title">{section.title}</span>
								<span class="page">{section.page}</span>
							</button>
						</li>
					{/if}
				{/each}
			</ol>
		</nav>
	{/if}
</div>

<style>
	.contents {
		position: relative;
		min-width: 0;
	}
	.toggle {
		display: flex;
		align-items: center;
		gap: 6px;
		max-width: min(46ch, 52vw);
		padding: 3px 12px 3px 9px;
	}
	.toggle.open {
		background: var(--rail);
	}
	.reading {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.panel {
		position: absolute;
		top: calc(100% + 8px);
		left: 0;
		z-index: 6;
		width: min(380px, calc(100vw - 32px));
		max-height: min(70vh, 640px);
		overflow-y: auto;
		padding: 8px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		box-shadow: var(--shadow);
		overscroll-behavior: contain;
	}
	ol {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		display: flex;
		align-items: flex-start;
		padding-left: calc(var(--depth) * 14px);
	}
	li .go {
		display: flex;
		align-items: baseline;
		gap: 12px;
		width: 100%;
		padding: 6px 10px;
		border: none;
		border-left: 3px solid transparent;
		border-radius: 0 6px 6px 0;
		background: none;
		color: var(--ink);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
	li.chapter .go {
		font-weight: 600;
	}
	li .go:hover {
		background: var(--rail);
	}
	/* The chapter being read: the highlighter's mark. */
	li .go.current {
		border-left-color: var(--highlighter);
		background: color-mix(in srgb, var(--highlighter) 18%, transparent);
	}
	.fold,
	.fold-space {
		flex: none;
		width: 22px;
		height: 30px;
	}
	.fold {
		display: grid;
		place-items: center;
		padding: 0;
		border: none;
		background: none;
		color: var(--faint);
		cursor: pointer;
	}
	.fold:hover {
		color: var(--ink);
	}
	.fold :global(svg) {
		transform: rotate(90deg);
	}
	.fold.folded :global(svg) {
		transform: none;
	}
	@media (prefers-reduced-motion: no-preference) {
		.fold :global(svg) {
			transition: transform 120ms ease-out;
		}
	}
	.folding {
		display: flex;
		justify-content: flex-end;
		gap: 4px;
		margin: -2px 0 4px;
	}
	.folding button {
		padding: 2px 8px;
		border: none;
		background: none;
		color: var(--muted);
		font-size: var(--step--1);
		cursor: pointer;
	}
	.folding button:hover {
		color: var(--ink);
		text-decoration: underline;
	}
	.title {
		flex: 1;
		min-width: 0;
	}
	.page {
		flex: none;
		color: var(--faint);
		font-size: var(--step--1);
		font-variant-numeric: tabular-nums;
	}
	@media (prefers-reduced-motion: no-preference) {
		.panel {
			animation: drop 120ms ease-out;
		}
		@keyframes drop {
			from {
				opacity: 0;
				transform: translateY(-4px);
			}
		}
	}
</style>
