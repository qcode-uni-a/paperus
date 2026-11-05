<script lang="ts">
	import type { Snippet } from 'svelte';
	import { closeOnScroll } from '#lib/dismiss.ts';

	// A quiet ⋯ button with a menu of actions; choosing one closes the menu.
	let { label, children }: { label: string; children: Snippet } = $props();

	const id = $props.id();
	const WIDTH = 250;
	let menu = $state<HTMLElement>();
	let button = $state<HTMLElement>();

	$effect(() => closeOnScroll(() => menu?.hidePopover()));

	/** Below the button, right-aligned with it. */
	function place() {
		if (!menu || !button) return;
		const rect = button.getBoundingClientRect();
		menu.style.setProperty('--top', `${rect.bottom + 6}px`);
		menu.style.setProperty('--left', `${Math.max(12, rect.right - WIDTH)}px`);
	}
</script>

<button
	bind:this={button}
	class="more"
	popovertarget="{id}-menu"
	aria-haspopup="menu"
	aria-label={label}
	title={label}
>
	<svg viewBox="0 0 24 24" aria-hidden="true">
		<circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle
			cx="19"
			cy="12"
			r="1.8"
		/>
	</svg>
</button>
<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
	id="{id}-menu"
	popover
	bind:this={menu}
	role="menu"
	tabindex="-1"
	class="menu"
	style:--width="{WIDTH}px"
	onbeforetoggle={place}
	onclick={(event) => {
		if ((event.target as Element).closest('button')) menu?.hidePopover();
	}}
>
	{@render children()}
</div>

<style>
	.more {
		flex: none;
		display: grid;
		place-items: center;
		width: 36px;
		height: 36px;
		margin-right: -6px;
		padding: 0;
		border-color: transparent;
		border-radius: 50%;
		background: none;
	}
	.more:hover:not(:disabled),
	.more:focus-visible {
		background: var(--rail);
		border-color: transparent;
	}
	.more svg {
		width: 20px;
		height: 20px;
		fill: var(--muted);
	}
	.menu {
		position: fixed;
		inset: var(--top) auto auto var(--left);
		margin: 0;
		padding: 6px;
		width: var(--width);
		border: 1px solid var(--rule);
		border-radius: 10px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	.menu :global(button) {
		display: flex;
		gap: 8px;
		align-items: flex-start;
		width: 100%;
		text-align: left;
		padding: 9px 12px 9px 34px;
		border: none;
		border-radius: var(--radius);
		background: none;
		color: var(--ink);
	}
	.menu :global(button:hover:not(:disabled)) {
		background: var(--rail);
	}
	.menu :global(button.danger) {
		color: var(--danger);
	}
	/* A switch: its check mark sits in the left margin. */
	.menu :global([role='menuitemcheckbox']) {
		padding-left: 8px;
	}
	.menu :global([role='menuitemcheckbox'] svg) {
		flex: none;
		width: 18px;
		height: 18px;
		margin-top: 2px;
		fill: none;
		stroke: var(--royal);
		stroke-width: 2.4;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.menu :global(hr) {
		margin: 6px 4px;
		border: none;
		border-top: 1px solid var(--rule);
	}
</style>
