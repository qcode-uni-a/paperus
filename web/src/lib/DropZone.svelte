<script lang="ts">
	import { page } from '$app/state';
	import { organize } from '#lib/organize.svelte.ts';
	import { addFiles } from '#lib/uploads.svelte.ts';

	// On a collection's page, dropped files go into that collection too.
	const collection = $derived(
		page.route.id === '/collections/[id]'
			? organize.collections.find((c) => c.id === page.params.id)
			: undefined
	);

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
		addFiles(event.dataTransfer?.files ?? [], collection?.id);
	}}
/>

{#if depth > 0}
	<div class="overlay" aria-hidden="true">
		<div>Drop files to add them{collection ? ` to ${collection.name}` : ''}</div>
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
