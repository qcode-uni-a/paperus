<script lang="ts">
	import Markdown from '#lib/Markdown.svelte';

	/** A text file shown as a page: Markdown rendered, plain text as written. */
	let { url, mediaType, filename }: { url: string; mediaType: string; filename: string } = $props();

	const markdown = $derived(mediaType === 'text/markdown' || /\.(md|markdown)$/i.test(filename));
	// Prose keeps the reading font; data and source files keep their columns.
	const prose = $derived(mediaType === 'text/plain' && !/\.(csv|tsv|log)$/i.test(filename));

	let text = $state<string | null>(null);
	let error = $state('');

	$effect(() => {
		const source = url;
		text = null;
		error = '';
		fetch(source)
			.then((response) => {
				if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
				return response.text();
			})
			.then((body) => {
				if (source === url) text = body;
			})
			.catch((failure: unknown) => (error = String(failure)));
	});
</script>

<div class="viewer">
	{#if error}
		<p class="error">Could not open the file: {error}</p>
	{:else if text === null}
		<p class="muted">Opening {filename}…</p>
	{:else}
		<div class="toolbar">
			<span class="muted">{filename}</span>
			<a href={url} target="_blank" rel="noreferrer">Open file</a>
		</div>
		<div class="desk">
			{#if markdown}
				<article class="sheet"><Markdown {text} onerror={(e) => (error = e)} /></article>
			{:else}
				<article class="sheet"><pre class:prose>{text}</pre></article>
			{/if}
		</div>
	{/if}
</div>

<style>
	.viewer {
		width: 100%;
	}
	.toolbar {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
		padding: 6px 0;
	}
	.toolbar span {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.desk {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		justify-items: center;
		padding: 20px 12px 32px;
		background: var(--desk);
		border-radius: 10px;
	}
	.sheet {
		width: 100%;
		min-width: 0;
		max-width: 76ch;
		min-height: 50vh;
		padding: clamp(20px, 5vw, 56px) clamp(18px, 6vw, 64px);
		background: var(--surface);
		color: var(--ink);
		border-radius: 3px;
		box-shadow:
			0 1px 2px rgb(27 36 64 / 0.12),
			0 4px 16px rgb(27 36 64 / 0.1);
		overflow-wrap: anywhere;
	}
	@media (max-width: 720px) {
		.desk {
			padding: 8px 6px 16px;
		}
	}
	pre {
		margin: 0;
		white-space: pre-wrap;
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
		font-size: 0.88em;
		line-height: 1.55;
	}
	pre.prose {
		font-family: var(--serif);
		font-size: var(--step-0);
		line-height: 1.7;
	}
</style>
