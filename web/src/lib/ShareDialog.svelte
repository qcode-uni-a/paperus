<script lang="ts">
	import { errorMessage, setOwner } from '#lib/api/client.ts';
	import { isShared, libraryName, writableLibraries } from '#lib/organize.svelte.ts';
	import { notify } from '#lib/toasts.svelte.ts';

	/** Share a paper with a group: the group becomes its owner, so everyone
	 * in it sees the paper (one copy for all, not a copy per person). */
	let {
		item,
		onshared
	}: { item: { id: string; title: string; library_id: string }; onshared: () => void } = $props();

	let dialog = $state<HTMLDialogElement>();
	let group = $state('');
	let saving = $state(false);
	let error = $state('');

	const groups = $derived(
		writableLibraries().filter((l) => isShared(l.id) && l.id !== item.library_id)
	);

	export function open() {
		group = groups[0]?.id ?? '';
		error = '';
		dialog?.showModal();
	}

	async function share(event: SubmitEvent) {
		event.preventDefault();
		if (!group) return;
		saving = true;
		const { error: failure } = await setOwner({
			path: { item_id: item.id },
			body: { library_id: group }
		});
		saving = false;
		if (failure) {
			error = errorMessage(failure);
			return;
		}
		dialog?.close();
		notify({ kind: 'success', title: `Shared with ${libraryName(group)}` });
		onshared();
	}
</script>

<dialog bind:this={dialog} aria-labelledby="share-title">
	<form onsubmit={share}>
		<h2 id="share-title">Share with group</h2>
		{#if groups.length === 0}
			<p>You are in no group you may add papers to. A group's administrator can add you.</p>
			<div class="buttons">
				<button type="button" onclick={() => dialog?.close()}>Close</button>
			</div>
		{:else}
			<label>
				Group
				<select bind:value={group}>
					{#each groups as option (option.id)}
						<option value={option.id}>{libraryName(option.id)}</option>
					{/each}
				</select>
			</label>
			<p class="note">
				Everyone in {libraryName(group)} sees “{item.title}”, its files and the group's tags on it.
				{#if isShared(item.library_id)}
					{libraryName(item.library_id)} no longer sees it, and its collections let it go.
				{:else}
					Your own tags and notes on it stay yours.
				{/if}
			</p>
			{#if error}<p class="error">{error}</p>{/if}
			<div class="buttons">
				<button type="button" onclick={() => dialog?.close()}>Cancel</button>
				<button class="primary" disabled={saving || !group}>Share</button>
			</div>
		{/if}
	</form>
</dialog>

<style>
	dialog {
		width: min(460px, calc(100vw - 32px));
		padding: 22px 24px 24px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	dialog::backdrop {
		background: rgb(10 14 30 / 0.4);
	}
	form {
		display: grid;
		gap: 14px;
	}
	h2 {
		margin: 0;
		font-size: var(--step-2);
	}
	label {
		display: grid;
		gap: 6px;
		font-weight: 600;
	}
	label select {
		font-weight: 400;
	}
	p {
		margin: 0;
	}
	.note {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
</style>
