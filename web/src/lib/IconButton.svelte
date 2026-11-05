<script lang="ts">
	/** A small quiet button with an icon: edit (pencil) or delete (trash can). */
	let { icon, label, onclick }: { icon: 'edit' | 'delete'; label: string; onclick: () => void } =
		$props();
</script>

<button
	class="icon-button"
	class:danger={icon === 'delete'}
	{onclick}
	aria-label={label}
	title={label}
>
	<svg viewBox="0 0 24 24" aria-hidden="true">
		{#if icon === 'edit'}
			<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4Z" />
			<path d="m13.5 6.5 4 4" />
		{:else}
			<path d="M4 7h16M10 11v6M14 11v6" />
			<path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3" />
		{/if}
	</svg>
</button>

<style>
	.icon-button {
		flex: none;
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		padding: 0;
		border-color: transparent;
		border-radius: 50%;
		background: none;
		color: var(--muted);
	}
	.icon-button:hover:not(:disabled),
	.icon-button:focus-visible {
		background: var(--rail);
		border-color: transparent;
		color: var(--ink);
	}
	.icon-button.danger:hover:not(:disabled),
	.icon-button.danger:focus-visible {
		color: var(--danger);
	}
	svg {
		width: 18px;
		height: 18px;
		fill: none;
		stroke: currentColor;
		stroke-width: 1.8;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
</style>
