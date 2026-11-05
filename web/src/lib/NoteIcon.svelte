<script lang="ts">
	/** The mark of a note (a page with lines), in lists and chips. */
	let { size = 18 }: { size?: number } = $props();
</script>

<svg viewBox="0 0 24 24" aria-hidden="true" style:width="{size}px" style:height="{size}px"
	><path d="M6 3.5h8.5L19 8v12.5H6zM14 3.5V8.5h5M9 12.5h7M9 16h5" /></svg
>

<style>
	svg {
		flex: none;
		align-self: center;
		fill: none;
		stroke: var(--royal);
		stroke-width: 1.7;
		stroke-linejoin: round;
	}
</style>
