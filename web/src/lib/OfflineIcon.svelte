<script lang="ts">
	/** The small mark of a paper kept whole on this device, with its PDFs
	 * (in the app: read offline too). */
	let { size = 16 }: { size?: number } = $props();
</script>

<span
	class="mark"
	role="img"
	aria-label="Available offline on this device"
	title="Available offline on this device"
>
	<svg viewBox="0 0 24 24" aria-hidden="true" style:width="{size}px" style:height="{size}px">
		<path d="M12 4v10" />
		<path d="m7.5 9.5 4.5 4.5 4.5-4.5" />
		<path d="M5 19h14" />
	</svg>
</span>

<style>
	.mark {
		display: inline-flex;
		flex: none;
		padding: 2px;
		vertical-align: middle;
	}
	svg {
		fill: none;
		stroke: var(--muted);
		stroke-width: 1.8;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
</style>
