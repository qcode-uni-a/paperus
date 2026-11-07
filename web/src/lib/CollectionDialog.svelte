<script lang="ts">
	import {
		changeCollection,
		createCollection,
		errorMessage,
		previewMove
	} from '#lib/api/client.ts';
	import type { Rules } from '#lib/api/generated/types.gen.ts';
	import {
		defaultLibrary,
		flatTree,
		isSmart,
		libraryById,
		libraryName,
		loadOrganize,
		organize,
		writableLibraries,
		type Collection
	} from '#lib/organize.svelte.ts';
	import RulesEditor from '#lib/RulesEditor.svelte';

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
	// A smart collection: papers matching rules instead of papers added.
	let smart = $state(false);
	let rules = $state<Rules>({});
	// Giving it to another owner: how many papers that owner does not have
	// yet, and whether they go along or leave the collection.
	let missing = $state<number | null>(null);
	let addPapers = $state(true);
	const moving = $derived(
		collection !== null && library !== '' && library !== collection.library_id
	);
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
		const holding = (rows: ReturnType<typeof flatTree>) =>
			rows.filter(({ collection: c }) => !isSmart(c));
		if (!collection || moving) return holding(flatTree(library || undefined));
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
		return holding(flatTree(collection.library_id)).filter(
			({ collection: c }) => !excluded.has(c.id)
		);
	});

	/** ``inLibrary``: preselect this library for a new collection;
	 * ``asSmart``: start as a smart collection, with ``startRules`` if given
	 * (e.g. the library's filter). */
	export function open(inLibrary?: string, asSmart = false, startRules?: Rules) {
		smart = collection ? isSmart(collection) : asSmart;
		rules = structuredClone($state.snapshot(startRules ?? collection?.rules) ?? {});
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
		const body = {
			name,
			description: description.trim() || null,
			parent_id: parent || null,
			...(smart ? { rules } : {})
		};
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
		<h2 id="collection-dialog-title">
			{collection ? (smart ? 'Edit smart collection' : 'Edit collection') : 'New collection'}
		</h2>
		{#if !collection}
			<fieldset class="kind">
				<legend class="visually-hidden">Kind of collection</legend>
				<label class="choice"
					><input type="radio" bind:group={smart} value={false} /> Papers you add to it</label
				>
				<label class="choice"
					><input type="radio" bind:group={smart} value={true} /> Smart: the papers that match rules,
					by themselves</label
				>
			</fieldset>
		{/if}
		<label>Name <input bind:value={name} required maxlength="200" /></label>
		{#if smart}
			<RulesEditor bind:rules library={library || collection?.library_id || ''} />
		{/if}
		<label>
			Description <span class="optional">(optional)</span>
			<textarea bind:value={description} rows="3"></textarea>
		</label>
		{#if writableLibraries().length > 1}
			<label>
				Owner
				<select bind:value={library} onchange={() => (parent = '')}>
					{#each writableLibraries() as option (option.id)}
						<option value={option.id}>{libraryName(option.id)}</option>
					{/each}
				</select>
			</label>
			{#if moving}
				<div class="move">
					<p>
						{toGroup
							? `The collection and those inside it are then shared with ${libraryName(library)}.`
							: 'The collection and those inside it become yours; the group no longer sees them.'}
					</p>
					{#if toGroup && missing}
						<p>
							{missing}
							{missing === 1 ? 'paper in it is' : 'papers in it are'} not shared with {libraryName(
								library
							)} yet:
						</p>
						<label class="choice"
							><input type="radio" bind:group={addPapers} value={true} /> Share {missing === 1
								? 'it'
								: 'them'} too</label
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
		width: min(560px, calc(100vw - 32px));
		max-height: calc(100dvh - 32px);
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
	.kind {
		display: grid;
		gap: 6px;
		/* A fieldset is otherwise as wide as its longest line (phones). */
		min-width: 0;
		margin: 0;
		padding: 0;
		border: none;
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
		white-space: nowrap;
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
