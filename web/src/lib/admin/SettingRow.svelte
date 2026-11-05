<script lang="ts">
	import type { Snippet } from 'svelte';

	/** One setting: its name and what it does, and the control beside. */
	let {
		title,
		description,
		id,
		children
	}: { title: string; description?: string; id?: string; children: Snippet } = $props();
</script>

<div class="row">
	<div class="text">
		<label class="title" for={id}>{title}</label>
		{#if description}<p>{description}</p>{/if}
	</div>
	<div class="control">{@render children()}</div>
</div>

<style>
	.row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(0, 320px);
		gap: 8px 24px;
		align-items: center;
		padding: 14px 0;
	}
	.row + :global(.row) {
		border-top: 1px solid var(--rule);
	}
	@media (max-width: 720px) {
		.row {
			grid-template-columns: minmax(0, 1fr);
		}
	}
	.title {
		font-weight: 600;
	}
	p {
		margin: 2px 0 0;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.control {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
	@media (max-width: 720px) {
		.control {
			justify-content: flex-start;
		}
	}
</style>
