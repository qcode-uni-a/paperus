<script lang="ts">
	import { untrack } from 'svelte';
	import { listImports } from '#lib/api/client.ts';
	import type { ImportOut } from '#lib/api/generated/types.gen.ts';
	import { ago } from '#lib/format.ts';
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
	let sending = $state<number | null>(null);
	let error = $state('');
	let timer: ReturnType<typeof setTimeout> | undefined;

	async function load() {
		const { data } = await listImports();
		imports = data ?? [];
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
		return () => clearTimeout(timer);
	});

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
		request.upload.onprogress = (progress) => {
			if (progress.lengthComputable) sending = progress.loaded / progress.total;
		};
		request.onload = () => {
			sending = null;
			if (request.status === 201) {
				file = null;
				load();
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
	<form onsubmit={start}>
		<label class="drop" class:chosen={file}>
			<input
				type="file"
				accept=".rdf,.bib,.bibtex,.ris,.json,.zip,application/zip"
				onchange={(event) => (file = event.currentTarget.files?.[0] ?? null)}
			/>
			<strong>{file ? file.name : 'Choose the export'}</strong>
			<span class="muted"
				>{file
					? `${(file.size / 1024 / 1024).toFixed(1)} MB`
					: 'Zotero RDF, BibTeX, RIS or CSL-JSON, alone or zipped with the files'}</span
			>
		</label>
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
		{#if sending !== null}
			<progress value={sending} max="1"></progress>
			<span class="muted">Uploading… {Math.round(sending * 100)} %</span>
		{/if}
		{#if error}<p class="error">{error}</p>{/if}
		<div><button class="primary" disabled={!file || sending !== null}>Import</button></div>
	</form>

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
								{#each report.missing_files as missing (missing)}<li>
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
	form {
		display: grid;
		gap: 14px;
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
