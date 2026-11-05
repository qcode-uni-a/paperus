<script lang="ts">
	import { renderMarkdown } from '#lib/markdown.ts';

	/** Markdown (notes, .md files) rendered as sanitized HTML, KaTeX included. */
	let { text, onerror }: { text: string; onerror?: (message: string) => void } = $props();

	let html = $state<string | null>(null);
	$effect(() => {
		const source = text;
		renderMarkdown(source)
			.then((rendered) => {
				if (source === text) html = rendered;
			})
			.catch((failure: unknown) => onerror?.(String(failure)));
	});
</script>

{#if html !== null}
	<!-- Sanitized with DOMPurify in renderMarkdown. -->
	<div class="markdown">{@html html}</div>
{/if}

<style>
	.markdown {
		font-family: var(--serif);
		line-height: 1.7;
	}
	.markdown :global(:first-child) {
		margin-top: 0;
	}
	.markdown :global(h1) {
		font-size: var(--step-3);
	}
	.markdown :global(h2) {
		font-size: var(--step-2);
	}
	.markdown :global(h3) {
		font-size: var(--step-1);
	}
	.markdown :global(:is(h1, h2, h3, h4)) {
		margin: 1.4em 0 0.5em;
		line-height: 1.25;
	}
	.markdown :global(code) {
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
		font-size: 0.86em;
		padding: 0.1em 0.3em;
		border-radius: 4px;
		background: var(--rail);
	}
	.markdown :global(pre) {
		padding: 12px 14px;
		border-radius: 6px;
		background: var(--rail);
		overflow-x: auto;
		line-height: 1.5;
	}
	.markdown :global(pre code) {
		padding: 0;
		background: none;
	}
	.markdown :global(blockquote) {
		margin: 1em 0;
		padding-left: 14px;
		border-left: 3px solid var(--highlighter);
		color: var(--muted);
	}
	.markdown :global(mark) {
		background: var(--highlighter);
		color: var(--on-highlighter);
	}
	.markdown :global(table) {
		border-collapse: collapse;
		display: block;
		overflow-x: auto;
	}
	.markdown :global(:is(th, td)) {
		padding: 6px 10px;
		border: 1px solid var(--rule);
		font-family: var(--sans);
		font-size: 0.92em;
	}
	/* Long formulas scroll sideways instead of widening the page. */
	.markdown :global(.katex-display) {
		overflow-x: auto;
		overflow-y: hidden;
		padding: 2px 0;
	}
	.markdown :global(img) {
		max-width: 100%;
	}
	.markdown :global(hr) {
		border: none;
		border-top: 1px solid var(--rule);
		margin: 2em 0;
	}
	.markdown :global(input[type='checkbox']) {
		width: auto;
		margin-right: 6px;
	}
</style>
