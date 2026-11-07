<script lang="ts">
	import { untrack } from 'svelte';
	import { errorMessage, importArxiv, listImports } from '#lib/api/client.ts';
	import type { ImportOut } from '#lib/api/generated/types.gen.ts';
	import { ago } from '#lib/format.ts';
	import { watchImport } from '#lib/processing.svelte.ts';
	import { notify } from '#lib/toasts.svelte.ts';
	import {
		defaultLibrary,
		libraryName,
		loadOrganize,
		writableLibraries
	} from '#lib/organize.svelte.ts';

	/** Import a library exported from another reference manager. */
	const SOURCES: { name: string; steps: string }[] = [
		{
			name: 'Zotero',
			steps:
				'Right-click “My Library” (or a collection) → Export… → format “Zotero RDF”, tick “Export Notes” and “Export Files”. Zip the folder Zotero writes and choose the zip here. Collections, tags, notes and PDFs come along.'
		},
		{
			name: 'JabRef',
			steps:
				'Choose your .bib file. With the PDFs: zip the .bib together with the folder of PDFs (keep the folders as they are). Groups become collections.'
		},
		{
			name: 'Mendeley',
			steps:
				'Select all references → Export → BibTeX (.bib) or RIS. Mendeley does not export collections; PDFs come along if you zip them with the export.'
		},
		{
			name: 'EndNote, Citavi, others',
			steps: 'Export as RIS (.ris) or BibTeX (.bib) and choose the file here.'
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
		missing_files: string[];
		problems: string[];
	};

	let imports = $state<ImportOut[]>([]);
	let owner = $state('');
	let file = $state<File | null>(null);
	let over = $state(false);
	let dropProblem = $state('');

	/** A dropped export: one file (the export, or a zip of it with its
	 * files). A folder cannot be read from a drop; it has to be zipped. */
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
		const files = [...(event.dataTransfer?.files ?? [])];
		if (files.length !== 1) {
			dropProblem = 'Drop one file: the export, or a zip of it together with its files folder.';
			return;
		}
		file = files[0];
	}
	let sending = $state<number | null>(null);
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
				started(request.response as ImportOut);
				file = null;
			} else {
				error =
					request.status === 413
						? 'The file is too large for an upload. An administrator can import it on the server with “paperus import”.'
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
</script>

<svelte:head><title>Import · paperus</title></svelte:head>

<h1>Import a library</h1>
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
					accept=".rdf,.bib,.bibtex,.ris,.json,.zip,.bbl,.tex,.gz,.tgz,.tar,application/zip,application/gzip"
					onchange={(event) => (file = event.currentTarget.files?.[0] ?? null)}
				/>
				<strong>{file ? file.name : 'Choose or drop the export'}</strong>
				<span class="muted"
					>{file
						? `${(file.size / 1024 / 1024).toFixed(1)} MB`
						: 'Zotero RDF, BibTeX, RIS or CSL-JSON, alone or zipped with the files; or a LaTeX source (.tar.gz, .bbl) for its references. A folder: zip it first.'}</span
				>
			</label>
			{#if dropProblem}<p class="error" role="alert">{dropProblem}</p>{/if}
			{#if sending !== null}
				<progress value={sending} max="1"></progress>
				<span class="muted">Uploading… {Math.round(sending * 100)} %</span>
			{/if}
			{#if error}<p class="error">{error}</p>{/if}
			<div><button class="primary" disabled={!file || sending !== null}>Import</button></div>
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
				{#if record.status === 'waiting'}
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
						{count(report.papers, 'paper', 'papers')}: {report.added} added, {report.found} already here.
						{count(report.files, 'file', 'files')}, {count(report.notes, 'note', 'notes')}, {count(
							report.collections,
							'new collection',
							'new collections'
						)}.
					</p>
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
	h1 {
		margin: 0 0 6px;
	}
	.lead {
		max-width: 68ch;
		margin: 0 0 20px;
	}
	.layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(0, 340px);
		gap: 28px;
		align-items: start;
	}
	@media (max-width: 820px) {
		.layout {
			grid-template-columns: minmax(0, 1fr);
		}
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
