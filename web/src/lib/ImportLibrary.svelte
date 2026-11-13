<script lang="ts">
	import { untrack } from 'svelte';
	import { errorMessage, importArxiv, listImports } from '#lib/api/client.ts';
	import type { ImportOut } from '#lib/api/generated/types.gen.ts';
	import { ago } from '#lib/format.ts';
	import ExportChoices from '#lib/ExportChoices.svelte';
	import { importFolder } from '#lib/folderImport.ts';
	import { watchImport } from '#lib/processing.svelte.ts';
	import { notify } from '#lib/toasts.svelte.ts';
	import {
		defaultLibrary,
		libraryName,
		loadOrganize,
		writableLibraries
	} from '#lib/organize.svelte.ts';

	/** Import a library exported from another reference manager (Settings →
	 * Import: usually done once, so not in the way elsewhere). */
	const SOURCES: { name: string; steps: string }[] = [
		{
			name: 'Zotero',
			steps:
				'Right-click “My Library” (or a collection) → Export… → format “Zotero RDF”, tick “Export Notes” and “Export Files”. Then “Choose a folder” here and pick the folder Zotero wrote: no need to zip it, however large. Its files are sent one by one; if the upload breaks off, choose the same folder again and it goes on where it stopped. Collections, tags, notes and PDFs come along.'
		},
		{
			name: 'JabRef',
			steps:
				'Choose your .bib file. With the PDFs: “Choose a folder” and pick the folder that holds the .bib and the PDFs (keep the folders as they are). Groups become collections.'
		},
		{
			name: 'Mendeley',
			steps:
				'Select all references → Export → BibTeX (.bib) or RIS. For the PDFs, put the export and your PDFs in one folder and “Choose a folder”: the new Mendeley Reference Manager does not say which PDF is whose, so each PDF is read and joins the paper whose DOI it carries; the rest become papers of their own. Mendeley does not export collections.'
		},
		{
			name: 'EndNote, Citavi, others',
			steps:
				'Export as RIS (.ris) or BibTeX (.bib) and choose the file here; in EndNote: File → Export…, style “RefMan (RIS) Export”. With the PDFs: put the export and the PDFs (EndNote: the library’s .Data folder) in one folder and “Choose a folder”. A PDF the export does not name joins the paper whose DOI it carries, or becomes a paper of its own.'
		},
		{
			name: 'paperus',
			steps:
				'Settings → Export on the other paperus. Choose all of its zips here at once (a large export comes in several); you then choose where its papers go: yours, or a group of yours.'
		},
		{
			name: 'arXiv (the references of a paper)',
			steps:
				'Type its arXiv ID or link under “Import the references of an arXiv paper”. Or choose a LaTeX source yourself: the .tar.gz from arXiv (“TeX Source”), a zip of a LaTeX project, or a .bbl file. The papers it cites come into a collection named after it; references that cannot be recognised are listed in the report.'
		}
	];

	type Report = {
		papers: number;
		added: number;
		found: number;
		files: number;
		notes: number;
		collections: number;
		loose_pdfs?: number;
		/** Already in other libraries one sees, by name ("your library", a group). */
		found_elsewhere?: Record<string, number>;
		/** Files left out, by library: the paper is there, and only to read. */
		files_not_added?: Record<string, number>;
		missing_files: string[];
		problems: string[];
	};

	let imports = $state<ImportOut[]>([]);
	let owner = $state('');
	let files = $state<File[]>([]);
	const file = $derived(files[0] ?? null);
	let over = $state(false);
	let dropProblem = $state('');

	/** A dropped export: one file (the export, or a zip of it with its
	 * files), or the zips of a paperus export. A folder cannot be read from
	 * a drop; it has to be zipped. */
	function dropped(event: DragEvent) {
		event.preventDefault();
		over = false;
		dropProblem = '';
		const items = [...(event.dataTransfer?.items ?? [])];
		if (items.some((item) => item.webkitGetAsEntry?.()?.isDirectory)) {
			dropProblem =
				'That is a folder. Zip it first (with the export file and its files folder inside), then drop or choose the zip.';
			return;
		}
		const dropped = [...(event.dataTransfer?.files ?? [])];
		if (!dropped.length) {
			dropProblem = 'Drop the export, or a zip of it together with its files folder.';
			return;
		}
		files = dropped;
	}
	let sending = $state<number | null>(null);
	/** A folder on its way: files sent, of all. */
	let folderSent = $state<{ files: number; of: number } | null>(null);

	/** A whole folder, sent file by file (``#lib/folderImport.ts``). */
	async function chooseFolder(event: Event & { currentTarget: HTMLInputElement }) {
		const chosen = [...(event.currentTarget.files ?? [])];
		event.currentTarget.value = '';
		if (!chosen.length) return;
		error = '';
		sending = 0;
		try {
			const record = await importFolder(chosen, owner, (sent, total, files, of) => {
				sending = total ? sent / total : 1;
				folderSent = { files, of };
			});
			started(record);
		} catch (failed) {
			error = `${failed instanceof Error ? failed.message : failed}. Choose the same folder again to go on where it stopped.`;
			load();
		} finally {
			sending = null;
			folderSent = null;
		}
	}
	let error = $state('');
	let timer: ReturnType<typeof setTimeout> | undefined;

	let alive = true;

	async function load() {
		const { data } = await listImports();
		if (!alive) return;
		imports = data ?? [];
		// A message when one still running is done, also after leaving.
		for (const record of imports)
			if (record.status === 'waiting' || record.status === 'running')
				watchImport(record.id, record.filename);
		clearTimeout(timer);
		// Follow imports still running.
		if (imports.some((i) => i.status === 'waiting' || i.status === 'running')) {
			timer = setTimeout(load, 1500);
		}
	}

	$effect(() => {
		untrack(async () => {
			await loadOrganize();
			owner = defaultLibrary()?.id ?? writableLibraries()[0]?.id ?? '';
			await load();
		});
		return () => {
			alive = false;
			clearTimeout(timer);
		};
	});

	let arxiv = $state('');
	let fetching = $state(false);
	let arxivError = $state('');

	/** The server downloads the paper's source from arXiv and imports it. */
	async function startArxiv(event: SubmitEvent) {
		event.preventDefault();
		if (!arxiv.trim()) return;
		arxivError = '';
		fetching = true;
		const { data, error: failed } = await importArxiv({
			body: { arxiv_id: arxiv.trim(), library_id: owner || null }
		});
		fetching = false;
		if (!data) {
			arxivError = `Could not start: ${errorMessage(failed)}`;
			return;
		}
		started(data);
		arxiv = '';
	}

	function started(record: ImportOut) {
		watchImport(record.id, record.filename);
		notify({
			kind: 'info',
			title: 'Import started',
			text: 'It runs in the background: you can leave this page; you get a message when it is done.'
		});
		load();
	}

	/** With XMLHttpRequest, for the upload's progress (exports with PDFs are big). */
	function start(event: SubmitEvent) {
		event.preventDefault();
		if (!file) return;
		error = '';
		const body = new FormData();
		body.append('upload', file);
		for (const part of files.slice(1)) body.append('parts', part);
		if (owner) body.append('library_id', owner);
		const request = new XMLHttpRequest();
		request.open('POST', '/api/imports');
		request.responseType = 'json';
		request.upload.onprogress = (progress) => {
			if (progress.lengthComputable) sending = progress.loaded / progress.total;
		};
		request.onload = () => {
			sending = null;
			if (request.status === 201) {
				const record = request.response as ImportOut;
				if (record.status === 'needs_choices') load();
				else started(record);
				files = [];
			} else {
				error =
					request.status === 413
						? 'The file is too large for one upload. Unpack it and “Choose a folder” instead: its files are sent one by one.'
						: request.status === 422
							? ((request.response as { detail?: string })?.detail ?? 'This cannot be imported.')
							: `The upload failed (${request.status}).`;
			}
		};
		request.onerror = () => {
			sending = null;
			error = 'The upload failed: the connection broke off.';
		};
		sending = 0;
		request.send(body);
	}

	function count(n: number | undefined, one: string, many: string): string {
		return `${n ?? 0} ${n === 1 ? one : many}`;
	}

	/** "Lab (10) and Team (5)", or just "Lab": the libraries, with how many
	 * when more than one. */
	function listed(by: Record<string, number>): string {
		const entries = Object.entries(by);
		if (entries.length === 1) return entries[0][0];
		const parts = entries.map(([name, n]) => `${name} (${n})`);
		return `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}`;
	}

	const total = (by: Record<string, number> | undefined) =>
		Object.values(by ?? {}).reduce((a, b) => a + b, 0);

	/** "15 already in Lab (10) and Team (5)": papers found in other
	 * libraries one sees; '' if none. */
	function elsewhere(report: Report): string {
		const n = total(report.found_elsewhere);
		return n ? `${n} already in ${listed(report.found_elsewhere ?? {})}` : '';
	}
</script>

<p class="lead muted">
	Bring your papers, files, collections, tags and notes from another reference manager. Papers you
	already have here are recognized (by DOI, arXiv ID or identical PDF) and not added twice; you can
	import the same file again safely.
</p>

<div class="layout">
	<div class="forms">
		{#if writableLibraries().length > 1}
			<label class="owner"
				>New papers belong to
				<select bind:value={owner}>
					{#each writableLibraries() as library (library.id)}
						<option value={library.id}>{libraryName(library.id)}</option>
					{/each}
				</select>
			</label>
		{/if}
		<form onsubmit={start}>
			<label
				class="drop"
				class:chosen={file}
				class:over
				ondragover={(event) => {
					event.preventDefault();
					over = true;
				}}
				ondragleave={() => (over = false)}
				ondrop={dropped}
			>
				<input
					type="file"
					multiple
					accept=".rdf,.bib,.bibtex,.ris,.json,.zip,.bbl,.tex,.gz,.tgz,.tar,application/zip,application/gzip"
					onchange={(event) => (files = [...(event.currentTarget.files ?? [])])}
				/>
				<strong
					>{files.length > 1
						? `${files.length} files`
						: file
							? file.name
							: 'Choose or drop the export'}</strong
				>
				<span class="muted"
					>{file
						? `${(files.reduce((sum, f) => sum + f.size, 0) / 1024 / 1024).toFixed(1)} MB`
						: 'Zotero RDF, BibTeX, RIS or CSL-JSON, alone or zipped with the files; a LaTeX source (.tar.gz, .bbl) for its references; or a paperus export (all its zips). A whole folder: “Choose a folder” below.'}</span
				>
			</label>
			{#if dropProblem}<p class="error" role="alert">{dropProblem}</p>{/if}
			{#if sending !== null}
				<progress value={sending} max="1"></progress>
				<span class="muted"
					>Uploading… {Math.round(sending * 100)} %{folderSent
						? ` (${folderSent.files} of ${folderSent.of} files)`
						: ''}</span
				>
			{/if}
			{#if error}<p class="error">{error}</p>{/if}
			<div class="buttons">
				<button class="primary" disabled={!file || sending !== null}>Import</button>
				<label class="button folder" class:disabled={sending !== null}>
					Choose a folder…
					<input type="file" webkitdirectory disabled={sending !== null} onchange={chooseFolder} />
				</label>
			</div>
			<p class="muted hint">
				A whole folder (a Zotero export with its files) needs no zip and no size limit: its files
				are sent one by one, and an interrupted upload goes on where it stopped.
			</p>
		</form>

		<form class="arxiv" onsubmit={startArxiv}>
			<h2>Import the references of an arXiv paper</h2>
			<p class="muted">
				paperus downloads the paper's LaTeX source from arXiv and adds the papers it cites, in a
				collection named after the paper.
			</p>
			<div class="row">
				<input
					type="text"
					bind:value={arxiv}
					placeholder="2401.12345 or https://arxiv.org/abs/2401.12345"
					aria-label="arXiv ID or link"
				/>
				<button disabled={!arxiv.trim() || fetching}>
					{fetching ? 'Downloading…' : 'Import references'}
				</button>
			</div>
			{#if arxivError}<p class="error">{arxivError}</p>{/if}
		</form>
	</div>

	<aside>
		<h2>How to export</h2>
		{#each SOURCES as source (source.name)}
			<details>
				<summary>{source.name}</summary>
				<p>{source.steps}</p>
			</details>
		{/each}
	</aside>
</div>

{#if imports.length}
	<h2>Your imports</h2>
	<ul class="imports">
		{#each imports as record (record.id)}
			<li>
				<div class="title">
					<strong>{record.filename}</strong>
					<span class="muted">{ago(record.created_at)}, to {libraryName(record.library_id)}</span>
				</div>
				{#if record.status === 'needs_choices' && record.choices}
					<ExportChoices {record} onchange={load} onstart={started} />
				{:else if record.status === 'receiving'}
					<p class="muted">
						Not all of its files arrived. Choose the same folder again to go on where it stopped.
					</p>
				{:else if record.status === 'waiting'}
					<p class="muted">Waiting to start…</p>
				{:else if record.status === 'running'}
					<progress value={record.done} max={record.total || 1}></progress>
					<p class="muted">
						{record.total ? `${record.done} of ${record.total}` : 'Reading the export…'}
					</p>
				{:else if record.status === 'failed'}
					<p class="error">{record.error}</p>
				{:else if record.report}
					{@const report = record.report as unknown as Report}
					<p>
						{count(report.papers, 'paper', 'papers')}: {report.added} added, {report.found} already here{#if elsewhere(report)},
							{elsewhere(report)}{/if}.
						{count(report.files, 'file', 'files')}, {count(report.notes, 'note', 'notes')}, {count(
							report.collections,
							'new collection',
							'new collections'
						)}.
						{#if report.loose_pdfs}
							{count(report.loose_pdfs, 'PDF', 'PDFs')} the export did not name: added like uploads, each
							joining its paper once read (by its DOI).
						{/if}
					</p>
					{#if total(report.files_not_added)}
						{@const n = total(report.files_not_added)}
						<p>
							<strong>{count(n, 'file', 'files')} not added:</strong>
							{n === 1 ? 'its paper is' : 'their papers are'} already in {listed(
								report.files_not_added ?? {}
							)}, which you can only read. Ask an editor of the group to add {n === 1
								? 'it'
								: 'them'}.
						</p>
					{/if}
					{#if report.missing_files?.length}
						<details>
							<summary>
								{count(report.missing_files.length, 'file', 'files')} not in the export
							</summary>
							<ul class="list">
								{#each report.missing_files as missing, i (i)}<li>
										<code>{missing}</code>
									</li>{/each}
							</ul>
						</details>
					{/if}
					{#if report.problems?.length}
						<details>
							<summary>{count(report.problems.length, 'problem', 'problems')}</summary>
							<ul class="list">
								{#each report.problems as problem, i (i)}<li>{problem}</li>{/each}
							</ul>
						</details>
					{/if}
				{/if}
			</li>
		{/each}
	</ul>
{/if}

<style>
	.lead {
		max-width: 68ch;
		margin: 0 0 20px;
	}
	.layout {
		display: grid;
		gap: 24px;
	}
	.forms,
	form {
		display: grid;
		gap: 14px;
	}
	.forms {
		gap: 24px;
	}
	.arxiv h2 {
		margin: 0;
	}
	.arxiv p {
		margin: 0;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
	}
	.row input {
		flex: 1 1 16rem;
		min-width: 0;
	}
	.drop {
		position: relative;
		display: grid;
		gap: 4px;
		justify-items: center;
		padding: 36px 16px;
		border: 2px dashed var(--rule);
		border-radius: 12px;
		text-align: center;
		cursor: pointer;
	}
	.drop:hover,
	.drop.over,
	.drop.chosen {
		border-color: var(--royal);
	}
	.drop input {
		position: absolute;
		inset: 0;
		opacity: 0;
		cursor: pointer;
	}
	.buttons {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		align-items: center;
	}
	/* A folder's dialog opens from a file input: hidden, in a button's looks. */
	.folder {
		position: relative;
		display: inline-flex;
		background: var(--surface);
		border: 1px solid var(--rule);
		border-radius: 999px;
		padding: 7px 18px;
		font-weight: 550;
		cursor: pointer;
	}
	.folder:hover:not(.disabled) {
		border-color: var(--faint);
	}
	.folder.disabled {
		opacity: 0.5;
		cursor: default;
	}
	.folder input {
		position: absolute;
		inset: 0;
		opacity: 0;
		cursor: inherit;
	}
	.folder:focus-within {
		outline: 2px solid var(--focus, var(--royal));
		outline-offset: 2px;
	}
	.hint {
		margin: 6px 0 0;
		font-size: var(--step--1);
	}
	.owner {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.owner select {
		width: auto;
	}
	progress {
		width: 100%;
	}
	aside h2,
	h2 {
		margin: 0 0 8px;
		font-size: var(--step-1);
	}
	h2 {
		margin-top: 28px;
	}
	aside h2 {
		margin-top: 0;
	}
	details {
		padding: 6px 0;
		border-bottom: 1px solid var(--rule);
	}
	summary {
		cursor: pointer;
		font-weight: 600;
	}
	details p {
		margin: 6px 0 4px;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.imports {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.imports > li {
		display: grid;
		gap: 6px;
		padding: 12px 0 14px;
		border-bottom: 1px solid var(--rule);
	}
	.imports p {
		margin: 0;
	}
	.title {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 12px;
		align-items: baseline;
	}
	.list {
		margin: 6px 0 0;
		padding-left: 18px;
		font-size: var(--step--1);
		overflow-wrap: anywhere;
	}
</style>
