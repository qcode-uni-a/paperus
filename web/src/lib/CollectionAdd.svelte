<script lang="ts">
	import AddItem from '#lib/AddItem.svelte';
	import LibraryPicker from '#lib/LibraryPicker.svelte';
	import MenuButton from '#lib/MenuButton.svelte';
	import { addFiles } from '#lib/uploads.svelte.ts';

	/** The + of a collection: papers from the library, new files, or a DOI. */
	let { collection, onadded }: { collection: string; onadded: () => void } = $props();

	let picker = $state<LibraryPicker>();
	let fileInput = $state<HTMLInputElement>();
	let dialog = $state<HTMLDialogElement>();
	let formOpen = $state(false);
</script>

<MenuButton label="Add items" icon="plus">
	<button role="menuitem" onclick={() => picker?.open()}>Add from the library</button>
	<button role="menuitem" onclick={() => fileInput?.click()}>Upload files</button>
	<button
		role="menuitem"
		onclick={() => {
			formOpen = true;
			dialog?.showModal();
		}}>Add by DOI or details</button
	>
</MenuButton>

<LibraryPicker bind:this={picker} {collection} {onadded} />

<input
	class="hidden"
	type="file"
	multiple
	bind:this={fileInput}
	tabindex="-1"
	onchange={(event) => {
		addFiles(event.currentTarget.files ?? [], collection);
		event.currentTarget.value = '';
	}}
/>

<dialog bind:this={dialog} onclose={() => (formOpen = false)} aria-labelledby="add-here-title">
	<h2 id="add-here-title">Add to this collection</h2>
	{#if formOpen}
		<AddItem
			{collection}
			ondone={() => {
				dialog?.close();
				onadded();
			}}
		/>
	{/if}
</dialog>

<style>
	.hidden {
		display: none;
	}
	dialog {
		width: min(560px, calc(100vw - 32px));
		padding: 20px 24px 24px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	dialog::backdrop {
		background: rgb(10 14 30 / 0.4);
	}
	h2 {
		margin: 0 0 12px;
		font-size: var(--step-2);
	}
</style>
