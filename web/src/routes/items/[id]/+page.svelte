<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import {
		addVersion,
		errorMessage,
		etagOf,
		FILE_ROLES,
		getItem,
		pinVersion,
		restoreFile,
		restoreItem,
		setOverrides,
		trashFile,
		trashItem,
		uploadToVersion,
		VERSION_KINDS,
		type FileRole,
		type ItemDetail,
		type VersionKind
	} from '#lib/api/client.ts';
	import MenuButton from '#lib/MenuButton.svelte';
	import ItemOrganize from '#lib/ItemOrganize.svelte';
	import PdfViewer from '#lib/PdfViewer.svelte';
	import TextViewer from '#lib/TextViewer.svelte';
	import { libraryById } from '#lib/organize.svelte.ts';
	import { fullName } from '#lib/format.ts';

	const id = $derived(page.params.id ?? '');
	// Search results link to the page with the matching passage.
	const startPage = $derived(Number(page.url.searchParams.get('page')) || 1);

	let item = $state<ItemDetail | null>(null);
	let etag = $state<string | undefined>();
	let notFound = $state(false);
	let error = $state('');

	let editing = $state(false);
	let titleDraft = $state('');

	let addingVersion = $state(false);
	let versionDoi = $state('');
	let versionTitle = $state('');
	let versionKind = $state<VersionKind>('published');
	let versionLabel = $state('');

	let uploadRole = $state<FileRole>('main');
	let showDetails = $state(false);

	/** The PDF to show: the cited version's main PDF, else any PDF. */
	const pdfFile = $derived.by(() => {
		if (!item) return null;
		const pdfs = (files: ItemDetail['versions'][number]['files']) =>
			files.filter((f) => !f.deleted_at && f.media_type === 'application/pdf');
		const preferred = item.versions.find((v) => v.id === item?.preferred_version_id);
		const candidates = [
			...pdfs(preferred?.files ?? []).filter((f) => f.role === 'main'),
			...item.versions.flatMap((v) => pdfs(v.files).filter((f) => f.role === 'main')),
			...item.versions.flatMap((v) => pdfs(v.files))
		];
		return candidates[0] ?? null;
	});

	/** Without a PDF: the main text file (notes, Markdown), if any. */
	const textFile = $derived.by(() => {
		if (!item || pdfFile) return null;
		const preferred = item.versions.find((v) => v.id === item?.preferred_version_id);
		const texts = [preferred, ...item.versions]
			.flatMap((v) => v?.files ?? [])
			.filter((f) => !f.deleted_at && isText(f.media_type, f.filename));
		return texts.find((f) => f.role === 'main') ?? texts[0] ?? null;
	});
	const viewed = $derived(pdfFile ?? textFile);
	// Readers of a group's library see the item but change nothing of it.
	const writable = $derived(item?.library_ids.some((id) => libraryById(id)?.writable) ?? false);
	// Trash is for everyone: only with the right to change all its libraries
	// (otherwise remove it from one under Libraries).
	const canTrash = $derived(
		(item?.library_ids.every((id) => libraryById(id)?.writable) ?? false) &&
			item?.library_ids.length === 1
	);

	function isText(mediaType: string, filename: string): boolean {
		return (
			mediaType.startsWith('text/') ||
			['application/json', 'application/x-tex'].includes(mediaType) ||
			/\.(md|markdown|txt)$/i.test(filename)
		);
	}

	async function load() {
		const { data, response } = await getItem({ path: { item_id: id } });
		notFound = !data;
		item = data ?? null;
		etag = etagOf(response);
	}

	$effect(() => {
		if (id) load();
	});

	// Refresh while the server reads the files (text, title from the file).
	$effect(() => {
		if (!item?.processing) return;
		const timer = setInterval(load, 2000);
		return () => clearInterval(timer);
	});

	/** Run an action; show its error or reload the item. */
	async function act(action: () => Promise<{ error?: unknown; response?: Response }>) {
		error = '';
		const { error: failure, response } = await action();
		if (failure !== undefined && response && !response.ok) {
			error = errorMessage(failure);
		}
		await load();
	}

	async function saveTitle(event: SubmitEvent) {
		event.preventDefault();
		if (!item) return;
		const { error: failure, response } = await setOverrides({
			path: { item_id: id },
			body: { ...item.overrides, title: titleDraft },
			headers: { 'if-match': etag }
		});
		if (response?.status === 412) {
			error = 'Someone changed this item in the meantime. Here is the current version.';
		} else if (failure) {
			error = errorMessage(failure);
		} else {
			editing = false;
		}
		await load();
	}

	async function submitVersion(event: SubmitEvent) {
		event.preventDefault();
		const body = versionDoi.trim()
			? { doi: versionDoi.trim(), kind: versionKind, label: versionLabel || null }
			: {
					metadata: { title: versionTitle || item?.title },
					kind: versionKind,
					label: versionLabel || null
				};
		await act(() => addVersion({ path: { item_id: id }, body }));
		if (!error) {
			addingVersion = false;
			versionDoi = versionTitle = versionLabel = '';
		}
	}

	async function uploadFiles(versionId: string, files: FileList | null) {
		for (const file of files ?? []) {
			await act(() =>
				uploadToVersion({
					path: { version_id: versionId },
					body: { upload: file, role: uploadRole }
				})
			);
		}
	}

	async function moveToTrash() {
		await trashItem({ path: { item_id: id } });
		await goto(resolve('/'));
	}

	function size(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`;
		return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
	}

	const SOURCE: Record<string, string> = {
		lookup: 'from registry',
		manual: 'entered by hand',
		file: 'from the file',
		import: 'imported',
		sync: 'synced'
	};

	const TEXT_STATUS: Record<string, string> = {
		pending: 'Reading text…',
		done: 'Searchable',
		no_text: 'No text (scan?)',
		unsupported: 'Not searchable',
		failed: 'Text extraction failed'
	};
</script>

{#if notFound}
	<p>This item does not exist. <a href={resolve('/')}>Back to the library</a></p>
{:else if item}
	{#if item.deleted_at}
		<div class="card row trashed">
			<span>This item is in the trash.</span>
			<button onclick={() => act(() => restoreItem({ path: { item_id: id } }))}>Restore</button>
		</div>
	{/if}

	<header>
		{#if editing}
			<form class="row" onsubmit={saveTitle}>
				<input bind:value={titleDraft} aria-label="Title" required />
				<button class="primary">Save</button>
				<button type="button" onclick={() => (editing = false)}>Cancel</button>
			</form>
		{:else}
			<div class="title">
				<h1>{item.title}</h1>
				{#if !item.deleted_at && (writable || viewed)}
					<MenuButton label="Item actions">
						{#if viewed}
							<button role="menuitem" onclick={() => (showDetails = !showDetails)}>
								{showDetails ? 'Hide details' : 'Details and files'}
							</button>
						{/if}
						{#if writable}
							<button
								role="menuitem"
								onclick={() => {
									titleDraft = item?.title ?? '';
									editing = true;
								}}>Edit title</button
							>
							<button role="menuitem" class="danger" onclick={moveToTrash}>Move to trash</button>
						{/if}
					</MenuButton>
				{/if}
			</div>
		{/if}
		<p class="muted">
			{item.authors
				.map(fullName)
				.join(', ')}{#if item.year}{' '}({item.year}){/if}{#if item.container_title}.
				<em>{item.container_title}</em>{/if}
		</p>

		<ItemOrganize {item} onchange={load} />
		{#if error}<p class="error">{error}</p>{/if}
	</header>

	{#if showDetails || !viewed}
		<section>
			<div class="row">
				<span class="badge">{item.type}</span>
				{#each item.identifiers as identifier (identifier.scheme + identifier.value)}
					{#if identifier.scheme === 'doi'}
						<a
							class="badge"
							href="https://doi.org/{identifier.value}"
							target="_blank"
							rel="noreferrer"
						>
							DOI {identifier.value}
						</a>
					{:else}
						<span class="badge">{identifier.scheme} {identifier.value}</span>
					{/if}
				{/each}
			</div>
			<div class="row heading">
				<h2>Versions</h2>
				{#if !item.deleted_at && writable}
					<button onclick={() => (addingVersion = !addingVersion)}>
						{addingVersion ? 'Close' : 'Add version'}
					</button>
				{/if}
			</div>

			{#if addingVersion}
				<form class="card version-form" onsubmit={submitVersion}>
					<label
						>DOI <input
							bind:value={versionDoi}
							placeholder="Leave empty to enter details by hand"
						/></label
					>
					{#if !versionDoi.trim()}
						<label>Title <input bind:value={versionTitle} placeholder={item.title} /></label>
					{/if}
					<div class="row">
						<label
							>Kind
							<select bind:value={versionKind}>
								{#each VERSION_KINDS as kind (kind)}<option value={kind}>{kind}</option>{/each}
							</select>
						</label>
						<label>Label <input bind:value={versionLabel} placeholder="e.g. WS 2026/27" /></label>
					</div>
					<div><button class="primary">Add version</button></div>
				</form>
			{/if}

			{#each item.versions as version (version.id)}
				<article class="card">
					<div class="row">
						<strong>{version.kind}</strong>
						{#if version.label}<span>{version.label}</span>{/if}
						{#if version.id === item.preferred_version_id}
							<span class="badge">cited{version.pinned ? ' (pinned)' : ''}</span>
						{:else if !item.deleted_at && writable}
							<button onclick={() => act(() => pinVersion({ path: { version_id: version.id } }))}>
								Cite this version
							</button>
						{/if}
						<span class="muted">{SOURCE[version.metadata_source]}</span>
					</div>
					{#if version.identifiers.length}
						<div class="row">
							{#each version.identifiers as identifier (identifier.scheme + identifier.value)}
								<span class="badge">{identifier.scheme} {identifier.value}</span>
							{/each}
						</div>
					{/if}

					<ul class="files">
						{#each version.files as file (file.id)}
							<li class="row" class:deleted={file.deleted_at}>
								<a href="/api/files/{file.id}/content" target="_blank" rel="noreferrer"
									>{file.filename}</a
								>
								<span class="badge">{file.role}</span>
								<span class="muted">{size(file.size)} · {TEXT_STATUS[file.text_status]}</span>
								{#if file.deleted_at}
									<button onclick={() => act(() => restoreFile({ path: { file_id: file.id } }))}
										>Restore</button
									>
								{:else if !item.deleted_at && writable}
									<button
										class="danger"
										onclick={() => act(() => trashFile({ path: { file_id: file.id } }))}
									>
										Remove
									</button>
								{/if}
							</li>
						{:else}
							<li class="muted">No files.</li>
						{/each}
					</ul>

					{#if !item.deleted_at && writable}
						<div class="row">
							<select bind:value={uploadRole} aria-label="Role of the uploaded file">
								{#each FILE_ROLES as role (role)}<option value={role}>{role}</option>{/each}
							</select>
							<label class="upload">
								<input
									type="file"
									multiple
									onchange={(event) => uploadFiles(version.id, event.currentTarget.files)}
								/>
								<span>Upload files</span>
							</label>
						</div>
					{/if}
				</article>
			{/each}
		</section>
	{/if}

	{#if pdfFile}
		<PdfViewer url="/api/files/{pdfFile.id}/content" {startPage} />
	{:else if textFile}
		<TextViewer
			url="/api/files/{textFile.id}/content"
			mediaType={textFile.media_type}
			filename={textFile.filename}
		/>
	{/if}
{/if}

<style>
	header {
		margin-bottom: 16px;
	}
	.title {
		display: flex;
		align-items: flex-start;
		gap: 8px;
	}
	h1 {
		flex: 1;
		min-width: 0;
		margin: 0 0 4px;
		font-size: 1.5em;
		overflow-wrap: anywhere;
	}
	@media (max-width: 720px) {
		header {
			margin-bottom: 12px;
		}
		h1 {
			font-size: 1.2em;
		}
	}
	header p {
		margin: 0;
	}
	header form input {
		flex: 1;
		min-width: 200px;
		font-size: 1.4em;
	}
	.trashed {
		justify-content: space-between;
		margin-bottom: 16px;
	}
	.heading {
		justify-content: space-between;
	}
	section {
		display: grid;
		gap: 12px;
		margin-bottom: 24px;
	}
	article {
		display: grid;
		gap: 10px;
	}
	.files {
		margin: 0;
		padding: 0;
		display: grid;
		gap: 6px;
	}
	.files li {
		list-style: none;
	}
	.files a {
		word-break: break-all;
	}
	.deleted a {
		text-decoration: line-through;
	}
	.version-form {
		display: grid;
		gap: 10px;
	}
	.version-form label {
		display: grid;
		gap: 4px;
	}
	select {
		width: auto;
	}
	.upload input {
		position: absolute;
		opacity: 0;
		width: 1px;
	}
	.upload span {
		display: inline-block;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 7px 14px;
		cursor: pointer;
		background: var(--surface);
	}
	.upload:focus-within span {
		outline: 2px solid var(--accent);
	}
</style>
