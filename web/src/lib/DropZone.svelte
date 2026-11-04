<script lang="ts">
	import { addFiles } from '#lib/uploads.svelte.ts';

	// dragenter/dragleave fire for every element passed; count them.
	let depth = $state(0);

	function hasFiles(event: DragEvent): boolean {
		return event.dataTransfer?.types.includes('Files') ?? false;
	}
</script>

<svelte:window
	ondragenter={(event) => {
		if (hasFiles(event)) depth++;
	}}
	ondragleave={(event) => {
		if (hasFiles(event)) depth = Math.max(0, depth - 1);
	}}
	ondragover={(event) => {
		if (hasFiles(event)) event.preventDefault();
	}}
	ondrop={(event) => {
		if (!hasFiles(event)) return;
		event.preventDefault();
		depth = 0;
		addFiles(event.dataTransfer?.files ?? []);
	}}
/>

{#if depth > 0}
	<div class="overlay" aria-hidden="true">
		<div>Drop files to add them</div>
	</div>
{/if}

<style>
	.overlay {
		position: fixed;
		inset: 0;
		z-index: 30;
		display: grid;
		place-items: center;
		background: color-mix(in srgb, var(--bg) 70%, transparent);
		border: 3px dashed var(--accent);
		pointer-events: none;
		font-size: 1.4em;
		color: var(--accent);
	}
	.overlay div {
		background: var(--surface);
		padding: 16px 24px;
		border-radius: var(--radius);
		box-shadow: 0 8px 24px rgb(0 0 0 / 0.15);
	}
</style>
