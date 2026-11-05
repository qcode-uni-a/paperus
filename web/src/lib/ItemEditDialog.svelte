<script lang="ts">
	import { errorMessage, setOverrides, setOwner, type ItemDetail } from '#lib/api/client.ts';
	import { isShared, libraryName, writableLibraries } from '#lib/organize.svelte.ts';

	/** Edit a paper: its title and its owner. */
	let { item, etag, onsaved }: { item: ItemDetail; etag: string | undefined; onsaved: () => void } =
		$props();

	let dialog = $state<HTMLDialogElement>();
	let title = $state('');
	let owner = $state('');
	let error = $state('');
	let saving = $state(false);

	const owners = $derived(writableLibraries());
	const leavingGroup = $derived(owner !== item.library_id && isShared(item.library_id));

	export function open() {
		title = item.title;
		owner = item.library_id;
		error = '';
		dialog?.showModal();
	}

	async function save(event: SubmitEvent) {
		event.preventDefault();
		saving = true;
		error = '';
		if (title.trim() && title !== item.title) {
			const { error: failure, response } = await setOverrides({
				path: { item_id: item.id },
				body: { ...item.overrides, title: title.trim() },
				headers: { 'if-match': etag }
			});
			if (response?.status === 412) {
				error = 'Someone changed this paper in the meantime; close and try again.';
			} else if (failure) {
				error = errorMessage(failure);
			}
		}
		if (!error && owner !== item.library_id) {
			const { error: failure } = await setOwner({
				path: { item_id: item.id },
				body: { library_id: owner }
			});
			if (failure) error = errorMessage(failure);
		}
		saving = false;
		if (error) return;
		dialog?.close();
		onsaved();
	}
</script>

<dialog bind:this={dialog} aria-labelledby="item-edit-title">
	<form onsubmit={save}>
		<h2 id="item-edit-title">Edit</h2>
		<label>Title <textarea bind:value={title} rows="3" required></textarea></label>
		{#if owners.length > 1 || owner !== owners[0]?.id}
			<label>
				Owner
				<select bind:value={owner}>
					{#if !owners.some((o) => o.id === item.library_id)}
						<option value={item.library_id}>{libraryName(item.library_id)}</option>
					{/if}
					{#each owners as option (option.id)}
						<option value={option.id}>{libraryName(option.id)}</option>
					{/each}
				</select>
			</label>
			<p class="note">
				{#if owner === item.library_id}
					{isShared(owner)
						? 'Shared: everyone in the group sees it.'
						: 'Private: only you see it, until you give it to a group.'}
				{:else if isShared(owner)}
					{libraryName(owner)} gets this paper; everyone in the group sees it.
				{:else}
					It becomes yours.
				{/if}
				{#if leavingGroup}
					{libraryName(item.library_id)} no longer sees it, and its collections let it go.
				{/if}
			</p>
		{/if}
		{#if error}<p class="error">{error}</p>{/if}
		<div class="buttons">
			<button type="button" onclick={() => dialog?.close()}>Cancel</button>
			<button class="primary" disabled={saving}>Save</button>
		</div>
	</form>
</dialog>

<style>
	dialog {
		width: min(520px, calc(100vw - 32px));
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
	label :global(textarea),
	label :global(select) {
		font-weight: 400;
	}
	textarea {
		resize: vertical;
		font-family: var(--serif);
	}
	.note {
		margin: -6px 0 0;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
	.error {
		margin: 0;
	}
</style>
