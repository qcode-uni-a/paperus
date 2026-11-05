<script lang="ts">
	import AddItem from '#lib/AddItem.svelte';
	import { addFiles } from '#lib/uploads.svelte.ts';

	let menu = $state<HTMLElement>();
	let dialog = $state<HTMLDialogElement>();
	let fileInput = $state<HTMLInputElement>();
	let formOpen = $state(false);

	function uploadFiles() {
		menu?.hidePopover();
		fileInput?.click();
	}

	function openForm() {
		menu?.hidePopover();
		formOpen = true;
		dialog?.showModal();
	}

	function closeForm() {
		dialog?.close();
	}
</script>

<button class="add" popovertarget="add-menu" aria-haspopup="menu" title="Add papers and notes">
	<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
	<span>Add</span>
</button>

<div id="add-menu" popover bind:this={menu} role="menu" class="menu">
	<button role="menuitem" onclick={uploadFiles}>
		<strong>Upload files</strong>
		<span>PDFs and other files; details are found automatically</span>
	</button>
	<button role="menuitem" onclick={openForm}>
		<strong>Add by DOI or details</strong>
		<span>A paper by its DOI, or notes without a file</span>
	</button>
</div>

<input
	class="hidden"
	type="file"
	multiple
	bind:this={fileInput}
	tabindex="-1"
	onchange={(event) => {
		addFiles(event.currentTarget.files ?? []);
		event.currentTarget.value = '';
	}}
/>

<dialog bind:this={dialog} onclose={() => (formOpen = false)} aria-labelledby="add-title">
	<div class="dialog-head">
		<h2 id="add-title">Add to the library</h2>
		<button class="close" onclick={closeForm} aria-label="Close">
			<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
		</button>
	</div>
	{#if formOpen}<AddItem ondone={closeForm} />{/if}
</dialog>

<style>
	.add {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 36px;
		padding: 0 14px 0 10px;
		background: var(--royal);
		border-color: var(--royal);
		color: var(--on-royal);
		font-weight: 600;
	}
	.add:hover:not(:disabled) {
		background: var(--royal-hover);
		border-color: var(--royal-hover);
	}
	svg {
		width: 18px;
		height: 18px;
		fill: none;
		stroke: currentColor;
		stroke-width: 2.2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.menu {
		/* Below the button, which always sits at the header's right end. */
		position: fixed;
		inset: 60px 12px auto auto;
		margin: 0;
		padding: 6px;
		width: min(320px, calc(100vw - 24px));
		border: 1px solid var(--rule);
		border-radius: 10px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	.menu button {
		display: grid;
		gap: 2px;
		width: 100%;
		text-align: left;
		border-color: transparent;
		background: none;
		padding: 10px 12px;
	}
	.menu button:hover:not(:disabled),
	.menu button:focus-visible {
		background: var(--rail);
		border-color: transparent;
	}
	.menu span {
		color: var(--muted);
		font-size: var(--step--1);
	}
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
	.dialog-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 12px;
	}
	.dialog-head h2 {
		margin: 0;
		font-size: var(--step-2);
	}
	.close {
		display: grid;
		place-items: center;
		width: 36px;
		height: 36px;
		padding: 0;
		border-color: transparent;
		background: none;
	}
	.close:hover:not(:disabled) {
		background: var(--rail);
		border-color: transparent;
	}
	@media (max-width: 720px) {
		.add {
			padding: 0 9px;
		}
		.add span {
			position: absolute;
			width: 1px;
			height: 1px;
			overflow: hidden;
			clip: rect(0 0 0 0);
		}
	}
</style>
