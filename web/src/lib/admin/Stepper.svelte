<script lang="ts">
	import { mdiMinus, mdiPlus } from '@mdi/js';
	import Icon from '#lib/Icon.svelte';

	/** A small whole number with − and + beside it. */
	let {
		value = $bindable(1),
		min = 1,
		max = 99,
		id,
		label
	}: { value?: number; min?: number; max?: number; id?: string; label: string } = $props();

	function step(by: number) {
		value = Math.min(max, Math.max(min, value + by));
	}
</script>

<div class="stepper">
	<button type="button" onclick={() => step(-1)} disabled={value <= min} aria-label="Fewer">
		<Icon path={mdiMinus} size={18} />
	</button>
	<input {id} type="number" {min} {max} bind:value aria-label={label} />
	<button type="button" onclick={() => step(1)} disabled={value >= max} aria-label="More">
		<Icon path={mdiPlus} size={18} />
	</button>
</div>

<style>
	.stepper {
		display: inline-flex;
		align-items: stretch;
		border: 1px solid var(--rule);
		border-radius: 999px;
		background: var(--surface);
		overflow: hidden;
	}
	button {
		display: grid;
		place-items: center;
		width: 38px;
		padding: 0;
		border: none;
		border-radius: 0;
		background: none;
		color: var(--royal);
	}
	button:hover:not(:disabled) {
		background: var(--rail);
	}
	button:disabled {
		color: var(--muted);
		opacity: 0.5;
	}
	input {
		width: 3.2em;
		padding: 6px 0;
		border: none;
		border-radius: 0;
		background: none;
		text-align: center;
		font-weight: 650;
		font-variant-numeric: tabular-nums;
		appearance: textfield;
		-moz-appearance: textfield;
	}
	input::-webkit-inner-spin-button,
	input::-webkit-outer-spin-button {
		appearance: none;
		margin: 0;
	}
	input:focus-visible {
		outline: 2px solid var(--royal);
		outline-offset: -2px;
	}
</style>
