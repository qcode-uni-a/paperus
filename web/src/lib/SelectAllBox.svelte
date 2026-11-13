<script lang="ts">
	import type { Selection } from '#lib/selection.svelte.ts';

	/** The list's own box, in the margin above the rows' (not on a phone,
	 * where Select starts picking): with none picked it picks every paper
	 * the list's filters match, loaded or not; with some or all, none. */
	let { selection, total }: { selection: Selection; total: number } = $props();

	const all = $derived(selection.everything || (total > 0 && selection.size >= total));
	const some = $derived(!all && selection.size > 0);

	function change() {
		if (all || some) selection.clear();
		else selection.everyMatching();
	}
</script>

<input
	type="checkbox"
	class="all"
	checked={all}
	indeterminate={some}
	aria-label={all || some ? 'Clear the selection' : `Select all ${total.toLocaleString()}`}
	onchange={change}
/>

<style>
	.all {
		position: absolute;
		left: -34px;
		top: 50%;
		width: 18px;
		height: 18px;
		margin: 0;
		transform: translateY(-50%);
		accent-color: var(--royal);
	}
	@media (max-width: 760px), (pointer: coarse) {
		.all {
			display: none;
		}
	}
</style>
