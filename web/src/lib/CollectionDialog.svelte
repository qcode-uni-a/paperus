<script lang="ts">
	import {
		changeCollection,
		createCollection,
		errorMessage,
		previewMove
	} from '#lib/api/client.ts';
	import {
		defaultLibrary,
		flatTree,
		libraryById,
		libraryName,
		loadOrganize,
		organize,
		writableLibraries,
		type Collection
	} from '#lib/organize.svelte.ts';

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
	let library = $state('');
	let error = $state('');
	let saving = $state(false);
	// Moving to another library: how many papers are not there yet, and
	// whether they join it or leave the collection.
	let missing = $state<number | null>(null);
	let addPapers = $state(true);
	const moving = $derived(collection !== null && library !== collection.library_id);
	const toGroup = $derived(libraryById(library)?.kind === 'group');

	$effect(() => {
		const id = collection?.id;
		const target = library;
		missing = null;
		if (!id || !moving) return;
		previewMove({ path: { collection_id: id }, query: { library: target } }).then(({ data }) => {
			if (library === target) missing = data?.not_in_library ?? null;
		});
	});

	/** Collections of the same library, but not the collection itself or
	 * anything inside it (collections nest only within one library). */
	const parents = $derived.by(() => {
		if (!collection || moving) return flatTree(library || undefined);
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
		return flatTree(collection.library_id).filter(({ collection: c }) => !excluded.has(c.id));
	});

	/** ``inLibrary``: preselect this library for a new collection. */
	export function open(inLibrary?: string) {
		name = collection?.name ?? '';
		description = collection?.description ?? '';
		parent = collection ? (collection.parent_id ?? '') : (parentId ?? '');
		const parentLibrary = organize.collections.find((c) => c.id === parentId)?.library_id;
		library = collection?.library_id ?? parentLibrary ?? inLibrary ?? defaultLibrary()?.id ?? '';
		error = '';
		dialog?.showModal();
	}

	async function save(event: SubmitEvent) {
		event.preventDefault();
		saving = true;
		const body = { name, description: description.trim() || null, parent_id: parent || null };
		const move = moving ? { library_id: library, add_papers: addPapers } : {};
		const result = collection
			? await changeCollection({
					path: { collection_id: collection.id },
					body: { ...body, ...move }
				})
			: await createCollection({ body: { ...body, library_id: library || null } });
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
		{#if writableLibraries().length > 1}
			<label>
				{collection ? 'Belongs to' : 'Library'}
				<select bind:value={library} onchange={() => (parent = '')}>
					{#each writableLibraries() as option (option.id)}
						<option value={option.id}>{libraryName(option.id)}</option>
					{/each}
				</select>
			</label>
			{#if moving}
				<div class="move">
					<p>
						The collection and those inside it move to {libraryName(library)}.
						{#if !toGroup}
							The group's tags stay with the group.
						{/if}
					</p>
					{#if toGroup && missing}
						<p>
							{missing}
							{missing === 1 ? 'paper is' : 'papers are'} not in {libraryName(library)} yet:
						</p>
						<label class="choice"
							><input type="radio" bind:group={addPapers} value={true} /> Add {missing === 1
								? 'it'
								: 'them'} to {libraryName(library)}</label
						>
						<label class="choice"
							><input type="radio" bind:group={addPapers} value={false} /> Leave {missing === 1
								? 'it'
								: 'them'} out of the collection</label
						>
					{/if}
				</div>
			{/if}
		{/if}
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
	.move {
		display: grid;
		gap: 6px;
		padding: 10px 12px;
		border-left: 3px solid var(--highlighter);
		background: var(--rail);
		border-radius: 0 6px 6px 0;
		font-size: var(--step--1);
	}
	.move p {
		margin: 0;
	}
	.choice {
		display: flex;
		align-items: center;
		gap: 8px;
		font-weight: 400;
	}
	.choice input {
		width: auto;
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
