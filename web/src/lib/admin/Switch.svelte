<script lang="ts">
	/** An on/off switch (a checkbox underneath, for keyboard and readers). */
	let {
		checked = $bindable(false),
		id,
		label
	}: { checked?: boolean; id?: string; label: string } = $props();
</script>

<label class="switch">
	<input type="checkbox" role="switch" {id} bind:checked aria-label={label} />
	<span class="track"><span class="knob"></span></span>
</label>

<style>
	.switch {
		position: relative;
		display: inline-flex;
		cursor: pointer;
	}
	input {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		margin: 0;
		opacity: 0;
		cursor: pointer;
	}
	.track {
		display: flex;
		align-items: center;
		width: 46px;
		height: 26px;
		padding: 3px;
		border-radius: 999px;
		background: var(--rule);
		transition: background 0.15s;
	}
	.knob {
		width: 20px;
		height: 20px;
		border-radius: 50%;
		background: var(--surface);
		box-shadow: 0 1px 2px rgb(0 0 0 / 0.25);
		transition: transform 0.15s;
	}
	input:checked + .track {
		background: var(--royal);
	}
	input:checked + .track .knob {
		transform: translateX(20px);
	}
	input:focus-visible + .track {
		outline: 2px solid var(--focus);
		outline-offset: 2px;
	}
	@media (prefers-reduced-motion: reduce) {
		.track,
		.knob {
			transition: none;
		}
	}
</style>
