<script lang="ts">
	import {
		downloadAllOpenAccess,
		downloadOpenAccess,
		errorMessage,
		missingPapers,
		setFileWanted,
		uploadToItem,
		uploadToVersion
	} from '#lib/api/client.ts';
	import type { MissingPaper } from '#lib/api/generated/types.gen.ts';
	import { ago } from '#lib/format.ts';
	import ItemRow from '#lib/ItemRow.svelte';
	import { packUp } from '#lib/transitions.ts';
	import { libraryById, loadOrganize } from '#lib/organize.svelte.ts';
	import { plainTitle } from '#lib/title.svelte.ts';
	import { notify } from '#lib/toasts.svelte.ts';

	/** Papers missing a file: none at all, or only their preprint's while
	 * the published version has none. An open-access copy the server
	 * downloads, the publisher's through one's own access (the browser
	 * extension), or an upload. Papers that need no (further) file can be
	 * set aside. */
	type Section = 'file' | 'journal';
	type List = { papers: MissingPaper[]; total: number } | null;

	let lists = $state<Record<Section, List>>({ file: null, journal: null });
	let hidden = $state<List>(null);
	let hiddenCount = $state(0);
	let showHidden = $state(false);
	let busy = $state<string | null>(null);

	// The paperus browser extension, if installed and connected here: it
	// marks the page, and gets PDFs at the publishers with one's own access.
	let extension = $state(false);
	let fetching = $state<{ done: number; total: number } | null>(null);
	$effect(() => {
		// Set by the extension's page script, possibly after this ran.
		const root = document.documentElement;
		const check = () =>
			(extension = (root.dataset.paperusExtensionFeatures ?? '').split(' ').includes('get-pdfs'));
		check();
		const marked = new MutationObserver(check);
		marked.observe(root, {
			attributes: true,
			attributeFilter: ['data-paperus-extension-features']
		});
		const listen = (event: MessageEvent) => {
			if (event.source !== window || event.origin !== location.origin) return;
			const data = event.data;
			if (data?.type === 'paperus:getPdfsProgress') {
				fetching = { done: data.done, total: data.total };
				// Each paper as it is done: saved ones are packed up at once.
				if (typeof data.item_id === 'string') {
					if (data.ok) markSaved(data.item_id);
					else if (data.reason) problems[data.item_id] = data.reason;
				}
			} else if (data?.type === 'paperus:getPdfsDone') {
				fetching = null;
				finished(data);
			}
		};
		window.addEventListener('message', listen);
		return () => {
			marked.disconnect();
			window.removeEventListener('message', listen);
		};
	});

	type Cause = 'robot-check' | 'access' | 'no-pdf' | 'error';
	const CAUSES: Record<Cause, [string, string]> = {
		access: ['needs access you do not have', 'need access you do not have'],
		'robot-check': ['was stopped by a robot check', 'were stopped by a robot check'],
		'no-pdf': ['had no PDF at the publisher', 'had no PDF at the publisher'],
		error: ['failed otherwise', 'failed otherwise']
	};

	function finished(result: {
		total: number;
		saved: number;
		failed: { item_id: string; reason: string; cause?: Cause }[];
	}) {
		for (const { item_id, reason } of result.failed) problems[item_id] = reason;
		const counts = new Map<Cause, number>();
		for (const { cause } of result.failed) {
			counts.set(cause ?? 'error', (counts.get(cause ?? 'error') ?? 0) + 1);
		}
		const why = [...counts].map(([cause, n]) => `${n} ${CAUSES[cause][n === 1 ? 0 : 1]}`);
		notify({
			kind: result.saved ? 'success' : 'info',
			title: `${result.saved} of ${result.total} ${result.total === 1 ? 'PDF' : 'PDFs'} saved`,
			text: why.length
				? `${why.join(', ')}. The reason is shown with each paper.`
				: 'All saved with the browser extension.'
		});
		// Once the last rows are packed up: the lists as the server has them.
		setTimeout(() => {
			load('file');
			load('journal');
		}, SHOWN_SAVED_MS + 900);
	}

	/** Ask the extension to get these papers' PDFs at their publishers. */
	function getWithExtension(papers: MissingPaper[], section: Section) {
		const wanted = papers
			.filter((p) => writable(p) && publisherLink(p))
			.map((p) => ({
				item_id: p.item.id,
				version_id: section === 'journal' ? p.version_id : null,
				title: plainTitle(p.item.title),
				url: publisherLink(p)!
			}));
		if (!wanted.length) return;
		for (const p of wanted) problems[p.item_id] = '';
		fetching = { done: 0, total: wanted.length };
		window.postMessage({ type: 'paperus:get-pdfs', papers: wanted }, location.origin);
	}
	let problems = $state<Record<string, string>>({});
	let got = $state(0);

	async function load(section: Section) {
		const { data } = await missingPapers({ query: { section } });
		lists[section] = { papers: data?.papers ?? [], total: data?.total ?? 0 };
		hiddenCount = data?.hidden ?? 0;
	}
	async function loadHidden() {
		const { data } = await missingPapers({ query: { hidden: true } });
		hidden = { papers: data?.papers ?? [], total: data?.total ?? 0 };
	}

	$effect(() => {
		load('file');
		load('journal');
		loadOrganize();
	});
	$effect(() => {
		if (showHidden) loadHidden();
	});

	const writable = (paper: MissingPaper) => libraryById(paper.item.library_id)?.writable ?? false;
	function untried(section: Section): number {
		return (lists[section]?.papers ?? []).filter((p) => p.open_access && writable(p) && !p.tried_at)
			.length;
	}

	/** Where to read the paper with one's own access: the publisher's DOI,
	 * else arXiv, else its address. */
	function publisherLink(paper: MissingPaper): string | null {
		const doi = paper.item.identifiers.find(
			(i) => i.scheme === 'doi' && !i.value.startsWith('10.48550/')
		);
		if (doi) return `https://doi.org/${doi.value}`;
		const arxiv = paper.item.identifiers.find((i) => i.scheme === 'arxiv');
		if (arxiv) return `https://arxiv.org/abs/${arxiv.value}`;
		return paper.item.identifiers.find((i) => i.scheme === 'url')?.value ?? null;
	}

	function settled(paper: MissingPaper) {
		gone(paper.item.id);
	}

	function gone(itemId: string) {
		for (const list of [lists.file, lists.journal, hidden]) {
			if (!list) continue;
			const before = list.papers.length;
			list.papers = list.papers.filter((p) => p.item.id !== itemId);
			list.total -= before - list.papers.length;
		}
	}

	// A paper just given its PDF: shown as saved for a moment, then packed
	// up and gone from the list.
	const SHOWN_SAVED_MS = 900;
	let saved = $state<Record<string, boolean>>({});
	function markSaved(itemId: string, then?: () => void) {
		if (saved[itemId]) return;
		saved[itemId] = true;
		got += 1;
		setTimeout(() => {
			gone(itemId);
			delete saved[itemId];
			then?.();
		}, SHOWN_SAVED_MS);
	}

	async function download(paper: MissingPaper, section: Section) {
		busy = paper.item.id;
		problems[paper.item.id] = '';
		const { data, error } = await downloadOpenAccess({
			path: { item_id: paper.item.id },
			query: { section }
		});
		busy = null;
		if (error || !data) {
			problems[paper.item.id] = errorMessage(error);
			paper.tried_at = new Date().toISOString();
			return;
		}
		// A paper's arXiv version may then leave only its journal's file missing.
		markSaved(paper.item.id, () => {
			if (section === 'file') load('journal');
		});
	}

	async function upload(paper: MissingPaper, section: Section, files: FileList | null) {
		const file = files?.[0];
		if (!file) return;
		busy = paper.item.id;
		problems[paper.item.id] = '';
		const { error } =
			section === 'journal' && paper.version_id
				? await uploadToVersion({
						path: { version_id: paper.version_id },
						body: { upload: file }
					})
				: await uploadToItem({ path: { item_id: paper.item.id }, body: { upload: file } });
		busy = null;
		if (error) {
			problems[paper.item.id] = errorMessage(error);
			return;
		}
		markSaved(paper.item.id);
	}

	async function wanted(paper: MissingPaper, want: boolean) {
		const { error } = await setFileWanted({
			path: { item_id: paper.item.id },
			body: { wanted: want }
		});
		if (error) {
			problems[paper.item.id] = errorMessage(error);
			return;
		}
		settled(paper);
		hiddenCount += want ? -1 : 1;
		if (want) {
			load('file');
			load('journal');
		}
	}

	async function tryAll(section: Section) {
		const { data } = await downloadAllOpenAccess({ query: { section } });
		const queued = data?.papers ?? 0;
		notify({
			kind: 'info',
			title: queued ? 'Downloading' : 'Nothing to try',
			text: queued
				? `Looking for open-access copies of ${queued} ${queued === 1 ? 'paper' : 'papers'} in the background.`
				: 'Every paper was tried in the last day, or none can be looked up.'
		});
	}
</script>

{#snippet row(paper: MissingPaper, section: Section | null)}
	{@const link = publisherLink(paper)}
	<ItemRow item={paper.item} leave={packUp} done={!!saved[paper.item.id]}>
		{#snippet actions()}
			<div class="actions">
				{#if saved[paper.item.id]}
					<span class="done" role="status"><b aria-hidden="true">✓</b> PDF saved</span>
				{:else if section === null}
					{#if writable(paper)}
						<button onclick={() => wanted(paper, true)}>Needs a file after all</button>
					{/if}
				{:else}
					{#if paper.open_access && writable(paper)}
						<button
							class="primary"
							onclick={() => download(paper, section)}
							disabled={busy === paper.item.id}
						>
							{busy === paper.item.id ? 'Looking…' : 'Download open access'}
						</button>
					{/if}
					{#if link && extension && writable(paper)}
						<button
							onclick={() => getWithExtension([paper], section)}
							disabled={fetching !== null}
							title="The browser extension opens the paper at its publisher and saves its PDF, with your access"
							>Get with the extension</button
						>
					{/if}
					{#if link}
						<a class="button" href={link} target="_blank" rel="noopener">At the publisher</a>
					{/if}
					{#if writable(paper)}
						<label class="button upload"
							>Upload file<input
								type="file"
								aria-label="Upload a file for {plainTitle(paper.item.title)}"
								onchange={(event) => upload(paper, section, event.currentTarget.files)}
							/></label
						>
						<button class="quiet" onclick={() => wanted(paper, false)}
							>{section === 'journal' ? 'The preprint is enough' : 'No file needed'}</button
						>
					{/if}
				{/if}
			</div>
			{#if problems[paper.item.id]}
				<p class="error">{problems[paper.item.id]}</p>
			{:else if paper.tried_at && paper.error && section !== null}
				<p class="muted small" title={paper.error}>
					No open-access copy found {ago(paper.tried_at)}.
				</p>
			{/if}
		{/snippet}
	</ItemRow>
{/snippet}

{#snippet list(found: List, empty: string, section: Section | null)}
	{#if found === null}
		<p class="muted">Loading…</p>
	{:else if found.papers.length === 0}
		<p class="muted">{empty}</p>
	{:else}
		{#if found.total > found.papers.length}
			<p class="muted">The first {found.papers.length} of {found.total}.</p>
		{/if}
		<ul>
			{#each found.papers as paper (paper.item.id)}
				{@render row(paper, section)}
			{/each}
		</ul>
	{/if}
{/snippet}

<svelte:head><title>Missing · paperus</title></svelte:head>

<header class="head">
	<h1>Missing</h1>
	<p class="muted">
		Papers missing their PDF. paperus downloads open copies itself: the journal's own when it is
		open access, else the arXiv version (found by its DOI). Publishers often refuse such downloads
		even of open papers; then, and for papers behind a login, open the paper at the publisher and
		save its PDF with the paperus browser extension, or upload the file.
	</p>
</header>

{#if !extension}
	<aside class="extension">
		<strong>Get PDFs with your own access</strong>
		<p>
			Install the paperus browser extension (Firefox, Chrome) and connect it to this paperus. This
			page can then fetch the PDFs from the publishers for you, through your campus network or
			login, one paper or all at once. Until then, open a paper at the publisher and save its PDF by
			hand.
		</p>
		<a
			href="https://github.com/qcode-uni-a/paperus/tree/main/extension#readme"
			target="_blank"
			rel="noopener">How to install the extension</a
		>
	</aside>
{/if}

{#if fetching}
	<p class="fetching" role="status">
		Getting PDFs with the browser extension: {fetching.done} of {fetching.total}…
	</p>
{/if}

{#if got}<p class="saved" role="status">{got} {got === 1 ? 'file' : 'files'} added.</p>{/if}

{#if showHidden}
	<section>
		<h2>Needing no file</h2>
		<p class="muted">Set aside: web pages, books on the shelf, papers whose preprint is enough.</p>
		{@render list(hidden, 'No paper is set aside.', null)}
	</section>
{:else}
	<section>
		<div class="title">
			<h2>No file</h2>
			{#if lists.file?.total}<span class="count">{lists.file.total}</span>{/if}
			{#if untried('file') > 1}
				<button onclick={() => tryAll('file')}>Download all open-access copies</button>
			{/if}
			{#if extension && (lists.file?.papers.length ?? 0) > 1}
				<button
					onclick={() => getWithExtension(lists.file?.papers ?? [], 'file')}
					disabled={fetching !== null}>Get all with the extension</button
				>
			{/if}
		</div>
		{@render list(lists.file, 'Every paper has a file.', 'file')}
	</section>

	<section>
		<div class="title">
			<h2>Only the preprint</h2>
			{#if lists.journal?.total}<span class="count">{lists.journal.total}</span>{/if}
			{#if untried('journal') > 1}
				<button onclick={() => tryAll('journal')}>Download all open-access copies</button>
			{/if}
			{#if extension && (lists.journal?.papers.length ?? 0) > 1}
				<button
					onclick={() => getWithExtension(lists.journal?.papers ?? [], 'journal')}
					disabled={fetching !== null}>Get all with the extension</button
				>
			{/if}
		</div>
		<p class="muted">
			Published papers whose journal version has no file yet; their preprint's is there. Open access
			here means the journal's own copy.
		</p>
		{@render list(lists.journal, 'No published paper misses its journal version.', 'journal')}
	</section>
{/if}

{#if hiddenCount || showHidden}
	<p class="toggle">
		<button class="link" onclick={() => (showHidden = !showHidden)}>
			{showHidden
				? 'Back to the missing files'
				: `${hiddenCount} ${hiddenCount === 1 ? 'paper needs' : 'papers need'} no (further) file`}
		</button>
	</p>
{/if}

<style>
	.head {
		margin-bottom: 12px;
	}
	h1 {
		margin: 0 0 6px;
	}
	.head p,
	section > p {
		max-width: 70ch;
		margin: 0;
	}
	section {
		display: grid;
		gap: 8px;
		margin-bottom: 28px;
	}
	.title {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px 12px;
	}
	h2 {
		margin: 0;
		font-size: var(--step-1);
	}
	.count {
		padding: 0 8px;
		border-radius: 999px;
		background: var(--rail);
		color: var(--muted);
		font-size: var(--step--1);
	}
	ul {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
	}
	/* A link and a file picker that look like the buttons beside them. */
	.actions .button {
		display: inline-flex;
		align-items: center;
		padding: 7px 18px;
		border: 1px solid var(--rule);
		border-radius: 999px;
		background: var(--surface);
		color: var(--ink);
		font-weight: 550;
		text-decoration: none;
	}
	.actions .button:hover {
		border-color: var(--faint);
	}
	.upload {
		position: relative;
		cursor: pointer;
	}
	.upload input {
		position: absolute;
		inset: 0;
		opacity: 0;
		cursor: pointer;
	}
	.upload:focus-within {
		outline: 2px solid var(--focus);
		outline-offset: 2px;
	}
	.quiet {
		border-color: transparent;
		background: none;
		color: var(--muted);
	}
	.quiet:hover {
		color: var(--ink);
	}
	.small {
		margin: 4px 0 0;
		font-size: var(--step--1);
	}
	.error {
		margin: 4px 0 0;
	}
	.saved {
		color: var(--success);
	}
	/* The merge window's "stays" chip: a green outline and mark. */
	.done {
		display: inline-block;
		padding: 0 10px;
		border: 1.5px solid var(--success);
		border-radius: 999px;
		line-height: 1.8;
		font-weight: 600;
		animation: pop 0.25s ease-out both;
	}
	.done b {
		margin-right: 2px;
		color: var(--success);
	}
	@keyframes pop {
		from {
			transform: scale(0.85);
			opacity: 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.done {
			animation: none;
		}
	}
	.extension {
		display: grid;
		gap: 6px;
		justify-items: start;
		max-width: 70ch;
		margin: 0 0 20px;
		padding: 14px 16px;
		border-left: 4px solid var(--royal);
		border-radius: 0 10px 10px 0;
		background: var(--rail);
	}
	.extension p {
		margin: 0;
	}
	.fetching {
		color: var(--royal);
		font-weight: 600;
	}
	.toggle {
		margin: 0;
	}
	.link {
		padding: 0;
		border: none;
		background: none;
		color: var(--royal);
		text-decoration: underline;
		min-height: 0;
	}
</style>
