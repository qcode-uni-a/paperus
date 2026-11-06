<script lang="ts">
	import { titleHtml } from '#lib/title.svelte.ts';

	/** A paper's title, with its formulas typeset (see title.svelte.ts). */
	let { text }: { text: string } = $props();
	const html = $derived(titleHtml(text));
</script>

<span class="title-text">{@html html}</span>

<style>
	/* Formulas at the size of the words around them (KaTeX enlarges). */
	.title-text :global(.katex) {
		font-size: 1em;
		line-height: 1;
	}
</style>
