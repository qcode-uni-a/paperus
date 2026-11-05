<script lang="ts">
	/** Reset and Save at the end of a settings section. */
	let {
		changed,
		saving = false,
		onreset,
		onsave
	}: { changed: boolean; saving?: boolean; onreset: () => void; onsave: () => void } = $props();
</script>

<div class="buttons">
	<button onclick={onreset} disabled={!changed || saving}>Reset</button>
	<button class="primary" onclick={onsave} disabled={!changed || saving}>Save</button>
</div>

<style>
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding-top: 12px;
	}
</style>
