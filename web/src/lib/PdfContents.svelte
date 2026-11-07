<script lang="ts">
	import { mdiTableOfContents } from '@mdi/js';
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

	$effect(() => {
		if (!open) return;
		// The chapter being read in view when the panel opens.
		panel?.querySelector('[aria-current="true"]')?.scrollIntoView({ block: 'center' });
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
			<ol>
				{#each sections as section, index (index)}
					<li style:--depth={section.depth}>
						<button
							class:current={index === current}
							aria-current={index === current}
							onclick={() => choose(section)}
						>
							<span class="title">{section.title}</span>
							<span class="page">{section.page}</span>
						</button>
					</li>
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
		padding-left: calc(var(--depth) * 14px);
	}
	li button {
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
	li[style*='--depth: 0'] button {
		font-weight: 600;
	}
	li button:hover {
		background: var(--rail);
	}
	/* The chapter being read: the highlighter's mark. */
	li button.current {
		border-left-color: var(--highlighter);
		background: color-mix(in srgb, var(--highlighter) 18%, transparent);
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
