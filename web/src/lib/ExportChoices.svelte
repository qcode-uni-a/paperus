<script lang="ts">
	import { deleteImport, errorMessage, startPaperusImport } from '#lib/api/client.ts';
	import type { ImportOut } from '#lib/api/generated/types.gen.ts';
	import { libraryName, organize, writableLibraries } from '#lib/organize.svelte.ts';

	/** A paperus export waiting for the person's choice: where each of its
	 * owners goes (their own library, or a group they may add to), and
	 * which of its zips are still missing. */
	let {
		record,
		onchange,
		onstart
	}: { record: ImportOut; onchange: () => void; onstart: (record: ImportOut) => void } = $props();

	const choices = $derived(record.choices!);
	const own = $derived(organize.libraries.find((library) => library.kind === 'personal'));
	// Nothing goes into a group unless chosen: everything to "Me" at first.
	let targets = $state<Record<string, string>>({});
	let error = $state('');
	let busy = $state(false);
	let sending = $state<number | null>(null);

	function target(ownerId: string): string {
		return targets[ownerId] ?? own?.id ?? '';
	}

	function count(n: number, one: string, many: string): string {
		return `${n} ${n === 1 ? one : many}`;
	}

	async function start() {
		error = '';
		busy = true;
		const owners = Object.fromEntries(choices.owners.map((owner) => [owner.id, target(owner.id)]));
		const { data, error: failure } = await startPaperusImport({
			path: { import_id: record.id },
			body: { owners }
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
		const body = new FormData();
		for (const file of list) body.append('parts', file);
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
		request.send(body);
	}
</script>

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
			<label class="owner">
				<span>
					<strong>{owner.kind === 'me' ? `${choices.exported_by}'s own` : owner.name}</strong>
					<small
						>{count(owner.items, 'paper', 'papers')}, {count(owner.notes, 'note', 'notes')}</small
					>
				</span>
				<select
					value={target(owner.id)}
					onchange={(event) => (targets[owner.id] = event.currentTarget.value)}
				>
					{#each writableLibraries() as library (library.id)}
						<option value={library.id}
							>{library.kind === 'personal'
								? 'Mine (private)'
								: libraryName(library.id)}{library.id === owner.suggested
								? ' (same name)'
								: ''}</option
						>
					{/each}
				</select>
			</label>
		{/each}
	</fieldset>
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
		gap: 8px;
	}
	legend {
		padding: 0;
		margin-bottom: 6px;
		font-weight: 600;
	}
	.owner {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: center;
		gap: 6px 12px;
	}
	.owner span {
		display: grid;
	}
	.owner select {
		width: auto;
		max-width: 100%;
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
	.buttons {
		display: flex;
		gap: 10px;
	}
	progress {
		width: 100%;
	}
</style>
