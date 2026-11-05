<script lang="ts">
	import { addFiles } from '#lib/uploads.svelte.ts';
</script>

<label class="upload" title="Upload files (or drop them anywhere)">
	<input
		type="file"
		multiple
		onchange={(event) => {
			addFiles(event.currentTarget.files ?? []);
			event.currentTarget.value = '';
		}}
	/>
	<svg viewBox="0 0 24 24" aria-hidden="true">
		<path
			d="M12 15V4M7.5 8.5 12 4l4.5 4.5M5 15v3.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V15"
		/>
	</svg>
	<span>Upload</span>
</label>

<style>
	.upload {
		position: relative;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 36px;
		padding: 0 14px 0 11px;
		border-radius: var(--radius);
		background: var(--royal);
		color: var(--on-royal);
		font-weight: 600;
		cursor: pointer;
	}
	.upload:hover {
		background: var(--royal-hover);
	}
	.upload:focus-within {
		outline: 2px solid var(--focus);
		outline-offset: 2px;
	}
	input {
		position: absolute;
		inset: 0;
		opacity: 0;
		width: 1px;
		pointer-events: none;
	}
	svg {
		width: 18px;
		height: 18px;
		fill: none;
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	@media (max-width: 720px) {
		.upload {
			padding: 0 9px;
		}
		span {
			position: absolute;
			width: 1px;
			height: 1px;
			overflow: hidden;
			clip: rect(0 0 0 0);
		}
	}
</style>
