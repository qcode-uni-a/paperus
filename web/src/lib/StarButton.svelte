<script lang="ts">
	import { starItem, unstarItem } from '#lib/api/client.ts';

	/** Star a paper as a favourite (each person their own). */
	let {
		item,
		starred = $bindable(false),
		size = 18
	}: { item: string; starred?: boolean; size?: number } = $props();

	async function toggle(event: MouseEvent) {
		event.preventDefault();
		event.stopPropagation();
		const next = !starred;
		starred = next; // at once; undone if the server says no
		const { error } = next
			? await starItem({ path: { item_id: item } })
			: await unstarItem({ path: { item_id: item } });
		if (error) starred = !next;
	}
</script>

<button
	class="star"
	class:on={starred}
	aria-pressed={starred}
	aria-label={starred ? 'Remove from favourites' : 'Add to favourites'}
	title={starred ? 'Remove from favourites' : 'Add to favourites'}
	onclick={toggle}
>
	<svg viewBox="0 0 24 24" aria-hidden="true" style:width="{size}px" style:height="{size}px">
		<path d="m12 3.6 2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z" />
	</svg>
</button>

<style>
	.star {
		display: inline-flex;
		padding: 4px;
		border: none;
		border-radius: 6px;
		background: none;
		color: var(--faint, var(--muted));
	}
	.star:hover {
		color: var(--ink);
		background: var(--rail);
	}
	svg {
		fill: none;
		stroke: currentColor;
		stroke-width: 1.6;
		stroke-linejoin: round;
	}
	.on {
		color: var(--highlighter);
	}
	.on svg {
		fill: currentColor;
		stroke: color-mix(in srgb, var(--highlighter) 70%, var(--ink));
	}
</style>
