<script lang="ts">
	import { authorHref } from '#lib/authorLinks.ts';
	import { plainTitle } from '#lib/title.svelte.ts';
	import Title from '#lib/Title.svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import {
		addVersion,
		archiveItem,
		errorMessage,
		etagOf,
		FILE_ROLES,
		getItem,
		getReading,
		markViewed,
		downloadAgain,
		passageText,
		readFileAgain,
		pinVersion,
		restoreFile,
		restoreItem,
		setOverrides,
		setReading,
		trashFile,
		trashItem,
		unarchiveItem,
		uploadToVersion,
		VERSION_KINDS,
		type FileRole,
		type ItemDetail,
		type VersionKind
	} from '#lib/api/client.ts';
	import type { Reading } from '#lib/api/generated/types.gen.ts';
	import { notify } from '#lib/toasts.svelte.ts';
	import MenuButton from '#lib/MenuButton.svelte';
	import StarButton from '#lib/StarButton.svelte';
	import ItemEditDialog from '#lib/ItemEditDialog.svelte';
	import ItemOrganize from '#lib/ItemOrganize.svelte';
	import ItemNotes from '#lib/ItemNotes.svelte';
	import SimilarPapers from '#lib/SimilarPapers.svelte';
	import PaperReferences from '#lib/PaperReferences.svelte';
	import MergeDialog from '#lib/MergeDialog.svelte';
	import ShareDialog from '#lib/ShareDialog.svelte';
	import SharedIcon from '#lib/SharedIcon.svelte';
	import PdfViewer from '#lib/PdfViewer.svelte';
	import TextViewer from '#lib/TextViewer.svelte';
	import { isShared, libraryById } from '#lib/organize.svelte.ts';
	import { ago, readingProblem } from '#lib/format.ts';
	import { session } from '#lib/session.svelte.ts';
	import Avatar from '#lib/Avatar.svelte';
	import { copyCitations, downloadCitations } from '#lib/citations.ts';
	import { nameSeparator, shownName, writtenName } from '#lib/names.svelte.ts';

	const id = $derived(page.params.id ?? '');
	// Search results link to the page with the matching passage.
	const startPage = $derived(Number(page.url.searchParams.get('page')) || 1);
	/** A passage to mark, from a search result (?file=…&passage=…). */
	let highlight = $state<{ page: number; text: string } | null>(null);
	$effect(() => {
		const file = page.url.searchParams.get('file');
		const position = Number(page.url.searchParams.get('passage'));
		highlight = null;
		if (!file || !Number.isInteger(position) || page.url.searchParams.get('passage') === null)
			return;
		passageText({ path: { file_id: file, position } }).then(({ data }) => {
			if (data?.page && page.url.searchParams.get('file') === file)
				highlight = { page: data.page, text: data.text };
		});
	});

	let item = $state<ItemDetail | null>(null);
	let etag = $state<string | undefined>();
	let notFound = $state(false);
	let error = $state('');

	let editDialog = $state<ItemEditDialog>();

	let copied = $state(false);
	async function copyBibtex() {
		if (await copyCitations({ items: [id] })) {
			copied = true;
			setTimeout(() => (copied = false), 2000);
		}
	}
	let mergeDialog = $state<MergeDialog>();
	let shareDialog = $state<ShareDialog>();

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
	/** Without a PDF or text: a saved web page, shown in a frame that runs
	 * no scripts and loads nothing from elsewhere (the server says so too). */
	const webFile = $derived.by(() => {
		if (!item || pdfFile || textFile) return null;
		const pages = item.versions
			.flatMap((v) => v.files)
			.filter((f) => !f.deleted_at && WEB_PAGES.includes(f.media_type));
		return pages.find((f) => f.role === 'main') ?? pages[0] ?? null;
	});
	/** Without a PDF or text: an image (a photographed note, a scan). */
	const SHOWN_IMAGES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];
	const imageFile = $derived.by(() => {
		if (!item || pdfFile || textFile || webFile) return null;
		const images = item.versions
			.flatMap((v) => v.files)
			.filter((f) => !f.deleted_at && f.media_type.startsWith('image/'));
		return images.find((f) => f.role === 'main') ?? images[0] ?? null;
	});
	const viewed = $derived(pdfFile ?? textFile ?? webFile ?? imageFile);
	// Readers of a group see its papers but change nothing of them.
	const writable = $derived(libraryById(item?.library_id)?.writable ?? false);

	/** Saved web pages (Zotero's snapshots): shown as pages, not as text. */
	const WEB_PAGES = ['text/html', 'application/xhtml+xml'];

	function isText(mediaType: string, filename: string): boolean {
		if (WEB_PAGES.includes(mediaType)) return false;
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

	// For the person's recent papers.
	$effect(() => {
		if (id) markViewed({ path: { item_id: id } });
	});

	// Where the person stopped reading (in either view, on any device): the
	// PDF opens there, unless a link names a page.
	let reading = $state<Reading | null | undefined>(undefined);
	$effect(() => {
		const item_id = id;
		reading = undefined;
		if (item_id)
			getReading({ path: { item_id } }).then(({ data }) => {
				if (item_id === id) reading = data ?? null;
			});
	});
	const resume = $derived(
		!page.url.searchParams.has('page') && reading && pdfFile && reading.file_id === pdfFile.id
			? reading
			: null
	);
	// Said once, with the way back to the start.
	let told = '';
	$effect(() => {
		if (!resume || told === id || (resume.page === 1 && resume.top < 200)) return;
		told = id;
		notify({
			kind: 'info',
			title: 'Where you left off',
			text: `Page ${resume.page}.`,
			link: { href: `${resolve('/items/[id]', { id })}?page=1`, label: 'From the start' }
		});
	});

	function saveReading(
		place: { page: number; top: number; left: number | null },
		leaving: boolean
	) {
		const file = pdfFile;
		if (!file || !id) return;
		const body = { file_id: file.id, ...place };
		if (leaving)
			// Also while the page goes away.
			fetch(`/api/items/${id}/reading`, {
				method: 'PUT',
				keepalive: true,
				credentials: 'same-origin',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body)
			}).catch(() => {});
		else setReading({ path: { item_id: id }, body });
	}

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
		no_text: 'No text',
		unsupported: 'Not searchable',
		failed: 'Text extraction failed'
	};

	/** Searchable or not, and what happens with scanned pages (OCR). */
	function readingStatus(file: { text_status: string; ocr_status?: string | null }): string {
		const text = TEXT_STATUS[file.text_status];
		const allScanned = file.text_status === 'no_text';
		switch (file.ocr_status) {
			case 'pending':
				return allScanned ? 'Scan: reading its text…' : `${text}; reading the scanned pages…`;
			case 'done':
				return allScanned ? text : `${text} (scanned pages read by OCR)`;
			case 'skipped':
				return allScanned
					? 'Scan, not read (OCR is off)'
					: `${text}; scanned pages not read (OCR is off)`;
			case 'failed':
				return `${text}; reading the scanned pages failed`;
			default:
				return text;
		}
	}
</script>

{#if notFound}
	<p>This item does not exist. <a href={resolve('/')}>Back to the library</a></p>
{:else if item}
	{#if item.deleted_at}
		<div class="card row trashed">
			<span>This item is in the trash.</span>
			<button onclick={() => act(() => restoreItem({ path: { item_id: id } }))}>Restore</button>
		</div>
	{:else if item.archived_at}
		<div class="card row trashed">
			<span>This paper is in the archive: kept, but left out of lists and search.</span>
			{#if writable}
				<button onclick={() => act(() => unarchiveItem({ path: { item_id: id } }))}
					>Take out of the archive</button
				>
			{/if}
		</div>
	{/if}

	<header>
		<div class="title">
			<h1>
				<Title text={item.title} />{#if isShared(item.library_id)}<span class="shared-mark"
						><SharedIcon size={18} owner={item.library_id} /></span
					>{/if}
			</h1>
			{#if !item.deleted_at}
				<StarButton item={item.id} starred={item.favourite ?? false} />
				<MenuButton label="Item actions">
					{#if viewed}
						<button role="menuitem" onclick={() => (showDetails = !showDetails)}>
							{showDetails ? 'Hide details' : 'Details and files'}
						</button>
					{/if}
					<button role="menuitem" onclick={copyBibtex}>Copy BibTeX</button>
					<button role="menuitem" onclick={() => downloadCitations({ items: [id] }, 'bibtex')}
						>Download BibTeX</button
					>
					{#if writable}
						<hr />
						<button role="menuitem" onclick={() => shareDialog?.open()}>
							{isShared(item.library_id) ? 'Share with another group…' : 'Share with group…'}
						</button>
						<button role="menuitem" onclick={() => editDialog?.open()}>Edit</button>
						<button role="menuitem" onclick={() => mergeDialog?.open()}>Merge into…</button>
						{#if !item.archived_at}
							<button
								role="menuitem"
								title="Kept, but left out of lists and search"
								onclick={() => act(() => archiveItem({ path: { item_id: id } }))}>Archive</button
							>
						{/if}
						<button role="menuitem" class="danger" onclick={moveToTrash}>Move to trash</button>
					{/if}
				</MenuButton>
			{/if}
		</div>
		<p class="muted">
			{#each item.authors as author, i (i)}{i ? nameSeparator() : ''}<a
					class="person"
					href={authorHref(item, i)}
					title="Papers by {writtenName(author)} in the library">{writtenName(author)}</a
				>{/each}
		</p>
		{#if item.added_by && isShared(item.library_id)}
			<p class="added-by">
				<Avatar
					name={shownName(item.added_by)}
					url={item.added_by.avatar_url}
					size={20}
					tone="desk"
				/>
				Added by {item.added_by.id === session.user?.id ? 'you' : shownName(item.added_by)}, {ago(
					item.created_at
				)}
			</p>
		{/if}

		{#if copied}<p class="copied" role="status">BibTeX copied.</p>{/if}
		<ItemOrganize {item} onchange={load} />
		{#if !item.deleted_at}<ItemNotes item={item.id} />{/if}
		{#if item.abstract}
			<details class="abstract">
				<summary>Abstract</summary>
				{#each item.abstract.split('\n\n') as paragraph, i (i)}<p>{paragraph}</p>{/each}
			</details>
		{/if}
		{#if !item.deleted_at}<SimilarPapers item={item.id} /><PaperReferences item={item.id} />{/if}
		{#if writable}
			<ItemEditDialog bind:this={editDialog} {item} {etag} onsaved={load} />
			<MergeDialog bind:this={mergeDialog} {item} />
			<ShareDialog bind:this={shareDialog} {item} onshared={load} />
		{/if}
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
								<span class="muted">{size(file.size)} · {readingStatus(file)}</span>
								{#if file.text_status === 'failed' && !file.deleted_at}
									<span class="problem" title={file.text_error ?? ''}
										>{readingProblem(file.text_error)}</span
									>
									{#if writable}
										{#if item.identifiers.some((i) => i.scheme === 'arxiv' || i.scheme === 'doi')}
											<button
												onclick={() => act(() => downloadAgain({ path: { file_id: file.id } }))}
												title="A fresh open-access copy (arXiv, or by DOI via Unpaywall) replaces this file"
												>Download again</button
											>
										{/if}
										<button onclick={() => act(() => readFileAgain({ path: { file_id: file.id } }))}
											>Read again</button
										>
									{/if}
								{/if}
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
		<!-- A link to a page of it ("From the start") opens it there anew. -->
		{#if reading !== undefined}{#key page.url.searchParams.get('page')}
				<PdfViewer
					url="/api/files/{pdfFile.id}/content"
					fileId={pdfFile.id}
					itemId={item.id}
					title={plainTitle(item.title)}
					startPage={resume?.page ?? startPage}
					startTop={resume?.top ?? null}
					startLeft={resume?.left ?? null}
					onplace={saveReading}
					highlight={highlight && page.url.searchParams.get('file') === pdfFile.id
						? highlight
						: null}
				/>
			{/key}{/if}
	{:else if textFile}
		<TextViewer
			url="/api/files/{textFile.id}/content"
			mediaType={textFile.media_type}
			filename={textFile.filename}
		/>
	{:else if webFile}
		<figure class="web">
			<iframe
				title="Saved web page: {webFile.filename}"
				src="/api/files/{webFile.id}/content"
				sandbox=""
				referrerpolicy="no-referrer"
				loading="lazy"
			></iframe>
			<figcaption class="muted">
				A web page saved with the paper ({webFile.filename}), shown without its scripts and without
				loading anything from the web, so parts may be missing.
				<a href="/api/files/{webFile.id}/content" target="_blank" rel="noreferrer">Open it alone</a>
			</figcaption>
		</figure>
	{:else if imageFile}
		<figure class="image">
			{#if SHOWN_IMAGES.includes(imageFile.media_type)}
				<a href="/api/files/{imageFile.id}/content" target="_blank" rel="noreferrer"
					><img src="/api/files/{imageFile.id}/content" alt={plainTitle(item.title)} /></a
				>
			{:else}
				<p class="muted">
					Browsers cannot show this image ({imageFile.filename}).
					<a href="/api/files/{imageFile.id}/content" target="_blank" rel="noreferrer">Open it</a>
				</p>
			{/if}
		</figure>
	{/if}
{/if}

<style>
	.abstract {
		max-width: 75ch;
		margin: 10px 0 0;
	}
	.abstract summary {
		color: var(--muted);
		font-size: var(--step--1);
		cursor: pointer;
	}
	.abstract p {
		margin: 6px 0 0;
		line-height: 1.55;
	}
	.person {
		color: inherit;
		text-decoration: none;
	}
	.person:hover {
		color: var(--royal);
		text-decoration: underline;
	}
	.web {
		display: grid;
		gap: 8px;
		margin: 0;
	}
	.web iframe {
		width: 100%;
		height: min(80vh, 900px);
		border: 1px solid var(--rule);
		border-radius: 12px;
		/* The page brings its own colours (or none: then white like paper). */
		background: white;
	}
	.web figcaption {
		font-size: var(--step--1);
	}
	.image {
		margin: 0;
		padding: 12px;
		border-radius: 12px;
		background: var(--desk);
		text-align: center;
	}
	.image img {
		display: block;
		max-width: 100%;
		height: auto;
		margin: 0 auto;
		border-radius: 4px;
		box-shadow: var(--shadow);
	}
	.problem {
		flex-basis: 100%;
		color: var(--danger);
		font-size: var(--step--1);
	}
	.added-by {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: -4px 0 12px;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.copied {
		margin: 0 0 8px;
		color: var(--success);
		font-size: var(--step--1);
	}
	header {
		margin-bottom: 16px;
	}
	.shared-mark {
		display: inline-flex;
		margin-left: 10px;
		vertical-align: 0.05em;
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
