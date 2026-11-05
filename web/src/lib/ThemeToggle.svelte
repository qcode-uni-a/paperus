<script lang="ts">
	import { theme } from '#lib/theme.svelte.ts';

	const LABELS = {
		system: 'Theme follows the device',
		light: 'Light theme',
		dark: 'Dark theme'
	} as const;
</script>

<button
	class="toggle"
	onclick={() => theme.next()}
	title="{LABELS[theme.current]} (click to change)"
	aria-label="{LABELS[theme.current]}, click to change"
>
	<svg viewBox="0 0 24 24" aria-hidden="true">
		{#if theme.current === 'light'}
			<circle cx="12" cy="12" r="4.5" />
			<path
				d="M12 2.5v2.5M12 19v2.5M4.6 4.6l1.8 1.8M17.6 17.6l1.8 1.8M2.5 12H5M19 12h2.5M4.6 19.4l1.8-1.8M17.6 6.4l1.8-1.8"
			/>
		{:else if theme.current === 'dark'}
			<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />
		{:else}
			<circle cx="12" cy="12" r="8.5" />
			<path d="M12 3.5v17a8.5 8.5 0 0 0 0-17Z" class="filled" />
		{/if}
	</svg>
</button>

<style>
	.toggle {
		display: grid;
		place-items: center;
		width: 36px;
		height: 36px;
		padding: 0;
		border-color: transparent;
		background: none;
	}
	.toggle:hover:not(:disabled) {
		background: var(--rail);
		border-color: transparent;
	}
	svg {
		width: 20px;
		height: 20px;
		fill: none;
		stroke: var(--ink);
		stroke-width: 1.8;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.filled {
		fill: var(--ink);
		stroke: none;
	}
</style>
