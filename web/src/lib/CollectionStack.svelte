<script lang="ts">
	import { resolve } from '$app/paths';
	import { libraryById, type Collection } from '#lib/organize.svelte.ts';
	import SharedIcon from '#lib/SharedIcon.svelte';

	let { collection }: { collection: Collection } = $props();

	const shared = $derived(libraryById(collection.library_id)?.kind === 'group');

	// Back to front: the newest item lies on top.
	const sheets = $derived([...(collection.recent ?? [])].reverse());
	// Back sheets fan out to the sides, so the stack reads as a stack.
	const fan = [
		{ angle: -10, shift: -22 },
		{ angle: 8, shift: 20 },
		{ angle: 0, shift: 0 }
	];
</script>

<div class="wrap">
	{#if shared}<span class="badge"><SharedIcon owner={collection.library_id} /></span>{/if}
	<a class="stack" href={resolve('/collections/[id]', { id: collection.id })}>
		<div class="desk" aria-hidden="true">
			{#if sheets.length === 0}
				<div class="sheet empty"></div>
			{/if}
			{#each sheets as sheet, index (sheet.id)}
				{@const front = index === sheets.length - 1}
				<div
					class="sheet"
					class:front
					style:--angle="{fan[3 - sheets.length + index].angle}deg"
					style:--shift="{fan[3 - sheets.length + index].shift}px"
					style:--lift="{(sheets.length - 1 - index) * 4}px"
				>
					<span class="fold"></span>
					<span class="title">{sheet.title}</span>
					<span class="line"></span>
					<span class="line short" class:marked={front}></span>
					<span class="line"></span>
				</div>
			{/each}
		</div>
		<div class="label">
			<strong>{collection.name}</strong>
			<span>{collection.count} {collection.count === 1 ? 'item' : 'items'}</span>
		</div>
	</a>
</div>

<style>
	.stack {
		display: grid;
		gap: 10px;
		color: var(--ink);
		text-decoration: none;
		border-radius: 12px;
		padding: 6px 6px 10px;
		transition: background-color 0.15s;
	}
	.stack:hover {
		background: var(--rail);
	}
	.stack:hover .sheet.front {
		transform: translateX(var(--shift)) rotate(var(--angle)) translateY(-5px);
	}
	.desk {
		position: relative;
		height: 150px;
		border-radius: 10px;
		background: var(--desk);
		overflow: hidden;
	}
	.wrap {
		position: relative;
	}
	/* Over the desk's top right corner, outside the link (it is a button). */
	.badge {
		position: absolute;
		top: 14px;
		right: 14px;
		z-index: 2;
		display: grid;
		place-items: center;
		border-radius: 50%;
		background: var(--surface);
		box-shadow: 0 1px 2px rgb(27 36 64 / 0.15);
	}
	.sheet {
		position: absolute;
		left: 50%;
		bottom: -18px;
		width: 100px;
		height: 132px;
		margin-left: -50px;
		padding: 14px 12px;
		display: grid;
		align-content: start;
		gap: 6px;
		background: var(--surface);
		border-radius: 4px;
		box-shadow:
			0 1px 2px rgb(27 36 64 / 0.12),
			0 6px 14px rgb(27 36 64 / 0.1);
		transform: translateX(var(--shift)) rotate(var(--angle)) translateY(var(--lift));
		transform-origin: 50% 100%;
		transition: transform 0.2s;
	}
	.sheet.empty {
		background: none;
		border: 2px dashed var(--rule);
		box-shadow: none;
		transform: none;
	}
	.fold {
		position: absolute;
		top: 0;
		right: 0;
		width: 16px;
		height: 16px;
		background: linear-gradient(225deg, var(--desk) 50%, var(--rule) 50%);
		border-bottom-left-radius: 3px;
	}
	.title {
		font-family: var(--serif);
		font-size: 9px;
		font-weight: 600;
		line-height: 1.25;
		color: var(--ink);
		display: -webkit-box;
		-webkit-line-clamp: 3;
		line-clamp: 3;
		-webkit-box-orient: vertical;
		overflow: hidden;
		padding-right: 8px;
	}
	.line {
		height: 3px;
		border-radius: 2px;
		background: var(--rule);
	}
	.line.short {
		width: 70%;
	}
	.line.marked {
		background: var(--highlighter);
		height: 6px;
	}
	.label {
		display: grid;
		gap: 2px;
		padding: 0 4px;
	}
	.label strong {
		font-family: var(--serif);
		font-size: var(--step-1);
		font-weight: 600;
		line-height: 1.25;
	}
	.label span {
		color: var(--muted);
		font-size: var(--step--1);
	}
	@media (prefers-reduced-motion: reduce) {
		.stack:hover .sheet.front {
			transform: translateX(var(--shift)) rotate(var(--angle));
		}
	}
</style>
