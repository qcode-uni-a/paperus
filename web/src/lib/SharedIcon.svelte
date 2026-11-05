<script lang="ts">
	/** The small mark of things shared with a group. */
	let { size = 16 }: { size?: number } = $props();
</script>

<svg
	class="shared"
	viewBox="0 0 24 24"
	role="img"
	aria-label="Shared with a group"
	style:width="{size}px"
	style:height="{size}px"
>
	<title>Shared with a group</title>
	<circle cx="9" cy="8" r="3.2" />
	<path d="M3.5 19c.6-3.2 2.8-5 5.5-5s4.9 1.8 5.5 5" />
	<circle cx="16.5" cy="9" r="2.6" />
	<path d="M15.5 14.2c2.6-.3 4.6 1.3 5.2 4.3" />
</svg>

<style>
	.shared {
		flex: none;
		fill: none;
		stroke: var(--muted);
		stroke-width: 1.8;
		stroke-linecap: round;
	}
</style>
