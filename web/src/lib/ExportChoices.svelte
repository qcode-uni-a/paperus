<script lang="ts">
	import {
		deleteImport,
		errorMessage,
		previewPaperusImport,
		startPaperusImport
	} from '#lib/api/client.ts';
	import type {
		Choices,
		Clash,
		ExportOwner,
		ImportOut,
		NameChoice,
		OwnerChoice,
		Preview
	} from '#lib/api/generated/types.gen.ts';
	import { libraryName, writableLibraries } from '#lib/organize.svelte.ts';

	/** A paperus export waiting for the person's choices (the rule book is
	 * docs/import-mapping.md): where each of its groups goes, which of its
	 * zips are still missing, and what its tags and collections become where
	 * names clash with those already there. */
	let {
		record,
		onchange,
		onstart
	}: { record: ImportOut; onchange: () => void; onstart: (record: ImportOut) => void } = $props();

	const choices = $derived(record.choices!);
	const groups = $derived(writableLibraries().filter((library) => library.kind === 'group'));

	// A group's choice as a select's value: "collection" (the default),
	// "library", "create" or "into:<library id>". Never a group by itself.
	let owners = $state<Record<string, string>>({});
	// A clash's choice, by "tag:<id>" or "collection:<id>": "new",
	// "merge:<id>" or "map:<id>"; unset: the default.
	let names = $state<Record<string, string>>({});
	let allNew = $state(false);
	let preview = $state<Preview | null>(null);
	let error = $state('');
	let busy = $state(false);
	let sending = $state<number | null>(null);

	function ownerValue(owner: ExportOwner): string {
		return owners[owner.id] ?? 'collection';
	}

	function ownerChoice(value: string): OwnerChoice {
		return value.startsWith('into:')
			? { action: 'into', library_id: value.slice(5) }
			: { action: value as OwnerChoice['action'] };
	}

	function nameChoice(value: string): NameChoice {
		const [action, target] = value.split(':');
		return { action: action as NameChoice['action'], target_id: target ?? null };
	}

	function nameValue(choice: NameChoice): string {
		return choice.action === 'new' ? 'new' : `${choice.action}:${choice.target_id}`;
	}

	/** What is sent: the owners' choices and those made for clashes still
	 * listed (a clash can go when the collection above it changes). */
	function body(listed: Preview | null): Choices {
		const keep = new Set(
			[...(listed?.tags ?? []), ...(listed?.collections ?? [])].map((c) => `${c.kind}:${c.id}`)
		);
		const chosen = (kind: string) =>
			Object.fromEntries(
				Object.entries(names)
					.filter(([key]) => key.startsWith(`${kind}:`) && (listed === null || keep.has(key)))
					.map(([key, value]) => [key.slice(kind.length + 1), nameChoice(value)])
			);
		return {
			owners: Object.fromEntries(
				choices.owners
					.filter((owner) => owner.kind === 'group')
					.map((owner) => [owner.id, ownerChoice(ownerValue(owner))])
			),
			tags: chosen('tag'),
			collections: chosen('collection'),
			all_new: allNew
		};
	}

	// The clashes follow the choices (a moment after the last change).
	let waiting: ReturnType<typeof setTimeout> | undefined;
	$effect(() => {
		const sent = $state.snapshot(body(null));
		clearTimeout(waiting);
		waiting = setTimeout(async () => {
			const { data, error: failure } = await previewPaperusImport({
				path: { import_id: record.id },
				body: sent
			});
			if (data) {
				preview = data;
				error = '';
			} else error = errorMessage(failure);
		}, 200);
	});

	function explained(owner: ExportOwner): string {
		const value = ownerValue(owner);
		const name = owner.name.split('/').at(-1);
		if (value === 'collection')
			return `Into your library, all in a new collection “${name}” with the group's collections inside. Once the group exists here, give that collection to it (Edit → Owner, also moving the papers).`;
		if (value === 'library') return 'Into your library, as your own papers, without a collection.';
		if (value === 'create')
			return `The group “${owner.name}” is created here, you its administrator; add its members afterwards.`;
		return `Into the group ${libraryName(value.slice(5))}: its members see the papers.`;
	}

	function count(n: number, one: string, many: string): string {
		return `${n} ${n === 1 ? one : many}`;
	}

	function papers(n: number): string {
		return count(n, 'paper', 'papers');
	}

	function setAllNew(on: boolean) {
		allNew = on;
		if (on) names = {};
	}

	async function start() {
		error = '';
		busy = true;
		const { data, error: failure } = await startPaperusImport({
			path: { import_id: record.id },
			body: body(preview)
		});
		busy = false;
		if (!data) {
			error = errorMessage(failure);
			return;
		}
		onstart(data);
	}

	async function cancel() {
		await deleteImport({ path: { import_id: record.id } });
		onchange();
	}

	/** More zips of the export (with XMLHttpRequest, for the progress). */
	function addParts(list: FileList | null) {
		if (!list?.length) return;
		error = '';
		const form = new FormData();
		for (const file of list) form.append('parts', file);
		const request = new XMLHttpRequest();
		request.open('POST', `/api/imports/${record.id}/parts`);
		request.responseType = 'json';
		request.upload.onprogress = (progress) => {
			if (progress.lengthComputable) sending = progress.loaded / progress.total;
		};
		request.onload = () => {
			sending = null;
			if (request.status === 200) onchange();
			else error = (request.response as { detail?: string })?.detail ?? 'The upload failed.';
		};
		request.onerror = () => {
			sending = null;
			error = 'The upload failed: the connection broke off.';
		};
		sending = 0;
		request.send(form);
	}

	function others(clash: Clash) {
		const there = preview?.targets?.[clash.library_id];
		const listed = new Set(clash.suggestions.map((s) => s.id));
		const all = clash.kind === 'tag' ? there?.tags : there?.collections;
		return (all ?? []).filter((t) => !listed.has(t.id) && !t.smart);
	}
</script>

{#snippet clashRow(clash: Clash)}
	{@const key = `${clash.kind}:${clash.id}`}
	<label class="clash">
		<span>
			<strong>{clash.name}</strong>
			{#if clash.note}<small>{clash.note}</small>{/if}
		</span>
		<select
			value={names[key] ?? nameValue(clash.chosen)}
			onchange={(event) => (names[key] = event.currentTarget.value)}
		>
			{#each clash.suggestions.filter((s) => s.likeness !== 'similar') as found (found.id)}
				{#if !clash.smart || clash.default.target_id === found.id}
					<option value="merge:{found.id}"
						>→ the existing {clash.kind} “{found.name}” ({papers(found.papers)})</option
					>
				{/if}
			{/each}
			<option value="new">→ a new one, “{clash.new_name}”</option>
			{#if clash.may_map}
				{#each clash.suggestions.filter((s) => s.likeness === 'similar') as found (found.id)}
					<option value="map:{found.id}"
						>→ suggested: “{found.name}” ({papers(found.papers)})</option
					>
				{/each}
				{#if others(clash).length}
					<optgroup label="Another one">
						{#each others(clash) as target (target.id)}
							<option value="map:{target.id}">→ “{target.name}” ({papers(target.papers)})</option>
						{/each}
					</optgroup>
				{/if}
			{/if}
		</select>
	</label>
{/snippet}

<div class="choices">
	<p>
		A paperus export by <strong>{choices.exported_by}</strong>{choices.server_url
			? ` on ${choices.server_url}`
			: ''}, {new Date(choices.exported_at).toLocaleDateString()}.
	</p>
	{#each choices.missing as missing (missing.part)}
		<p class="warning">
			Part {missing.part} of {choices.parts} is missing (<code>{missing.name}</code>): add it, or
			import without its {count(missing.files, 'file', 'files')}.
		</p>
	{/each}
	{#if choices.missing.length}
		<label class="add"
			>Add the missing zips <input
				type="file"
				multiple
				accept=".zip,application/zip"
				onchange={(event) => addParts(event.currentTarget.files)}
			/></label
		>
		{#if sending !== null}<progress value={sending} max="1"></progress>{/if}
	{/if}
	{#each choices.refused as name (name)}
		<p class="muted">Left out: <code>{name}</code> is not part of this export.</p>
	{/each}

	<fieldset>
		<legend>Where its papers go</legend>
		{#each choices.owners as owner (owner.id)}
			<div class="owner">
				<span>
					<strong>{owner.kind === 'me' ? `${choices.exported_by}'s own` : owner.name}</strong>
					<small>{papers(owner.items)}, {count(owner.notes, 'note', 'notes')}</small>
				</span>
				{#if owner.kind === 'me'}
					<span>Into your library</span>
				{:else}
					<select
						aria-label="Where the papers of {owner.name} go"
						value={ownerValue(owner)}
						onchange={(event) => (owners[owner.id] = event.currentTarget.value)}
					>
						<option value="collection"
							>Into my library, in a collection “{owner.name.split('/').at(-1)}”</option
						>
						<option value="library">Into my library, without a collection</option>
						{#if owner.can_create}<option value="create">Create the group here</option>{/if}
						{#each groups as library (library.id)}
							<option value="into:{library.id}">Into the group {libraryName(library.id)}</option>
						{/each}
					</select>
					<small class="explained">{explained(owner)}</small>
					{#if owner.suggestions?.length && !ownerValue(owner).startsWith('into:')}
						<small class="suggested"
							>Suggested:
							{#each owner.suggestions ?? [] as suggestion, i (suggestion.library_id)}
								{i ? ', ' : ''}<button
									type="button"
									class="link"
									onclick={() => (owners[owner.id] = `into:${suggestion.library_id}`)}
									>into {suggestion.name}</button
								>
							{/each}</small
						>
					{/if}
				{/if}
			</div>
		{/each}
	</fieldset>

	{#if preview?.tags?.length || preview?.collections?.length}
		<fieldset>
			<legend>Tags and collections that exist there already</legend>
			<label class="all"
				><input
					type="checkbox"
					checked={allNew}
					onchange={(event) => setAllNew(event.currentTarget.checked)}
				/> Import all as new</label
			>
			{#each preview?.collections ?? [] as clash (clash.id)}{@render clashRow(clash)}{/each}
			{#each preview?.tags ?? [] as clash (clash.id)}{@render clashRow(clash)}{/each}
		</fieldset>
	{/if}

	<p class="muted">
		Papers you can already see (the same paper, DOI, arXiv ID or file) are found, not added twice.
	</p>
	{#if error}<p class="error">{error}</p>{/if}
	<div class="buttons">
		<button class="primary" disabled={busy || sending !== null} onclick={start}>Import</button>
		<button disabled={busy} onclick={cancel}>Cancel</button>
	</div>
</div>

<style>
	.choices {
		display: grid;
		gap: 10px;
	}
	p {
		margin: 0;
	}
	.warning {
		color: var(--danger);
	}
	fieldset {
		margin: 0;
		padding: 0;
		border: none;
		display: grid;
		gap: 10px;
	}
	legend {
		padding: 0;
		margin-bottom: 6px;
		font-weight: 600;
	}
	.owner {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 4px 12px;
		align-items: center;
	}
	.owner > span:first-child,
	.clash > span {
		display: grid;
	}
	.owner select,
	.clash select {
		width: auto;
		max-width: 100%;
	}
	.explained,
	.suggested {
		grid-column: 1 / -1;
	}
	.clash {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: center;
		gap: 4px 12px;
	}
	.all {
		display: flex;
		gap: 8px;
		align-items: center;
	}
	.all input {
		width: auto;
	}
	.add {
		display: grid;
		gap: 6px;
		font-weight: 600;
	}
	small {
		color: var(--muted);
		font-size: var(--step--1);
	}
	code {
		overflow-wrap: anywhere;
	}
	.link {
		padding: 0;
		border: none;
		background: none;
		color: var(--royal);
		font-size: inherit;
	}
	.buttons {
		display: flex;
		gap: 10px;
	}
	progress {
		width: 100%;
	}
</style>
