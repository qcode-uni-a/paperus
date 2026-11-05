<script lang="ts">
	import { changeCollection, createCollection, errorMessage } from '#lib/api/client.ts';
	import { flatTree, loadOrganize, organize, type Collection } from '#lib/organize.svelte.ts';

	/** Create a collection (optionally inside ``parentId``) or edit ``collection``. */
	let {
		collection = null,
		parentId = null,
		onsaved
	}: {
		collection?: Collection | null;
		parentId?: string | null;
		onsaved?: (id: string) => void;
	} = $props();

	let dialog = $state<HTMLDialogElement>();
	let name = $state('');
	let description = $state('');
	let parent = $state('');
	let error = $state('');
	let saving = $state(false);

	/** Not the collection itself or anything inside it. */
	const parents = $derived.by(() => {
		if (!collection) return flatTree();
		const excluded = new Set([collection.id]);
		let grew = true;
		while (grew) {
			grew = false;
			for (const c of organize.collections) {
				if (c.parent_id && excluded.has(c.parent_id) && !excluded.has(c.id)) {
					excluded.add(c.id);
					grew = true;
				}
			}
		}
		return flatTree().filter(({ collection: c }) => !excluded.has(c.id));
	});

	export function open() {
		name = collection?.name ?? '';
		description = collection?.description ?? '';
		parent = collection ? (collection.parent_id ?? '') : (parentId ?? '');
		error = '';
		dialog?.showModal();
	}

	async function save(event: SubmitEvent) {
		event.preventDefault();
		saving = true;
		const body = { name, description: description.trim() || null, parent_id: parent || null };
		const result = collection
			? await changeCollection({ path: { collection_id: collection.id }, body })
			: await createCollection({ body });
		saving = false;
		if (!result.data) {
			error = errorMessage(result.error);
			return;
		}
		dialog?.close();
		await loadOrganize();
		onsaved?.(result.data.id);
	}
</script>

<dialog bind:this={dialog} aria-labelledby="collection-dialog-title">
	<form onsubmit={save}>
		<h2 id="collection-dialog-title">{collection ? 'Edit collection' : 'New collection'}</h2>
		<label>Name <input bind:value={name} required maxlength="200" /></label>
		<label>
			Description <span class="optional">(optional)</span>
			<textarea bind:value={description} rows="3"></textarea>
		</label>
		<label>
			Inside
			<select bind:value={parent}>
				<option value="">No other collection (top level)</option>
				{#each parents as { collection: c, depth } (c.id)}
					<option value={c.id}>{'  '.repeat(depth)}{c.name}</option>
				{/each}
			</select>
		</label>
		{#if error}<p class="error">{error}</p>{/if}
		<div class="buttons">
			<button type="button" onclick={() => dialog?.close()}>Cancel</button>
			<button class="primary" disabled={saving}>{collection ? 'Save' : 'Create collection'}</button>
		</div>
	</form>
</dialog>

<style>
	dialog {
		width: min(480px, calc(100vw - 32px));
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
	label :global(input),
	label :global(textarea),
	label :global(select) {
		font-weight: 400;
	}
	.optional {
		font-weight: 400;
		color: var(--muted);
	}
	textarea {
		resize: vertical;
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
