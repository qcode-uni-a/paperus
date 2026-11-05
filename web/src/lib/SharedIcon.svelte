<script lang="ts">
	import { closeOnScroll } from '#lib/dismiss.ts';
	import { libraryName } from '#lib/organize.svelte.ts';

	/** The small mark of things shared with a group; with ``owner``, a click
	 * tells which group. */
	let { size = 16, owner }: { size?: number; owner?: string } = $props();

	const id = $props.id();
	let bubble = $state<HTMLElement>();
	let button = $state<HTMLElement>();

	$effect(() => closeOnScroll(() => bubble?.hidePopover()));

	/** Just below the icon, kept on screen. */
	function place() {
		if (!bubble || !button) return;
		const rect = button.getBoundingClientRect();
		const left = Math.min(Math.max(12, rect.left + rect.width / 2 - 120), innerWidth - 252);
		bubble.style.setProperty('--top', `${rect.bottom + 6}px`);
		bubble.style.setProperty('--left', `${left}px`);
	}
</script>

{#snippet icon()}
	<svg
		class="shared"
		viewBox="0 0 24 24"
		aria-hidden="true"
		style:width="{size}px"
		style:height="{size}px"
	>
		<circle cx="9" cy="8" r="3.2" />
		<path d="M3.5 19c.6-3.2 2.8-5 5.5-5s4.9 1.8 5.5 5" />
		<circle cx="16.5" cy="9" r="2.6" />
		<path d="M15.5 14.2c2.6-.3 4.6 1.3 5.2 4.3" />
	</svg>
{/snippet}

{#if owner}
	<button
		bind:this={button}
		class="mark"
		popovertarget="{id}-owner"
		aria-label="Shared with {libraryName(owner)}"
		title="Shared with {libraryName(owner)}"
		onclick={(event) => event.stopPropagation()}
	>
		{@render icon()}
	</button>
	<div id="{id}-owner" popover bind:this={bubble} class="bubble" onbeforetoggle={place}>
		Shared with <strong>{libraryName(owner)}</strong>
	</div>
{:else}
	<span class="mark" role="img" aria-label="Shared with a group" title="Shared with a group">
		{@render icon()}
	</span>
{/if}

<style>
	.mark {
		display: inline-flex;
		flex: none;
		padding: 2px;
		border: none;
		border-radius: 6px;
		background: none;
		vertical-align: middle;
	}
	button.mark:hover:not(:disabled),
	button.mark:focus-visible {
		background: var(--rail);
	}
	.shared {
		fill: none;
		stroke: var(--muted);
		stroke-width: 1.8;
		stroke-linecap: round;
	}
	.bubble {
		position: fixed;
		inset: var(--top) auto auto var(--left);
		margin: 0;
		max-width: 240px;
		padding: 8px 12px;
		border: 1px solid var(--rule);
		border-radius: 8px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
		font-family: var(--sans);
		font-size: var(--step--1);
		font-weight: 400;
		line-height: 1.4;
	}
</style>
