<script lang="ts">
	import Title from '#lib/Title.svelte';
	import { plainTitle } from '#lib/title.svelte.ts';
	import { resolve } from '$app/paths';
	import {
		addVersion,
		errorMessage,
		listItems,
		downloadAgain,
		readFileAgain,
		unreadableFiles,
		type Item
	} from '#lib/api/client.ts';
	import type { UnreadableFile } from '#lib/api/generated/types.gen.ts';
	import { readingProblem } from '#lib/format.ts';
	import ItemRow from '#lib/ItemRow.svelte';

	/** Papers whose details were only guessed from their file: no DOI or
	 * arXiv ID found in it. A DOI looks the details up. */
	let items = $state<Item[] | null>(null);
	let total = $state(0);
	let entered = $state<Record<string, string>>({});
	let errors = $state<Record<string, string>>({});
	let busy = $state<string | null>(null);
	let fixed = $state(0);

	async function load() {
		const { data, response } = await listItems({ query: { unsorted: true, limit: 200 } });
		items = data ?? [];
		total = Number(response?.headers.get('X-Total-Count') ?? items.length);
	}

	$effect(() => {
		load();
		loadUnreadable();
	});

	// Files whose text could not be read.
	let unreadable = $state<UnreadableFile[]>([]);
	let retried = $state<Record<string, boolean>>({});
	async function loadUnreadable() {
		const { data } = await unreadableFiles();
		unreadable = data ?? [];
	}
	let downloading = $state<string | null>(null);
	let problems = $state<Record<string, string>>({});
	async function download(file: UnreadableFile) {
		downloading = file.file_id;
		problems[file.file_id] = '';
		const { error } = await downloadAgain({ path: { file_id: file.file_id } });
		downloading = null;
		if (error) {
			problems[file.file_id] = errorMessage(error);
			return;
		}
		retried[file.file_id] = true;
	}
	async function readAgain(file: UnreadableFile) {
		const { error } = await readFileAgain({ path: { file_id: file.file_id } });
		if (!error) retried[file.file_id] = true;
	}

	/** A DOI, a doi.org link, or an arXiv ID (as its DOI). */
	function asDoi(text: string): string {
		const value = text.trim();
		const arxiv = value.match(/^(?:arxiv:\s*)?(\d{4}\.\d{4,5})(v\d+)?$/i);
		return arxiv ? `10.48550/arXiv.${arxiv[1]}` : value;
	}

	async function lookUp(event: SubmitEvent, item: Item) {
		event.preventDefault();
		const doi = asDoi(entered[item.id] ?? '');
		if (!doi) return;
		busy = item.id;
		errors[item.id] = '';
		const { error } = await addVersion({ path: { item_id: item.id }, body: { doi } });
		busy = null;
		if (error) {
			errors[item.id] = errorMessage(error);
			return;
		}
		fixed += 1;
		await load();
	}
</script>

<svelte:head><title>Unsorted · paperus</title></svelte:head>

<header class="head">
	<h1>Unsorted</h1>
	<p class="muted">
		Papers whose details could not be found: their files had no DOI or arXiv ID, so the title is
		only a guess. Enter the DOI or arXiv ID to look the details up, or open a paper to type them in.
	</p>
</header>

{#if fixed}<p class="saved" role="status">
		{fixed}
		{fixed === 1 ? 'paper' : 'papers'} sorted.
	</p>{/if}

{#if unreadable.length}
	<section class="unreadable">
		<h2>Files that could not be read</h2>
		<p class="muted">
			Their text is missing, so they are not found by search and AI assistants cannot read them.
			Read one again after a fix in paperus, or open the paper to replace or remove the file.
		</p>
		<ul>
			{#each unreadable as file (file.file_id)}
				<li>
					<div class="what">
						<a href={resolve('/items/[id]', { id: file.item_id })}
							><Title text={file.item_title} /></a
						>
						<span class="muted">{file.filename}</span>
						<span>{readingProblem(file.error)}</span>
						{#if file.error}<small class="muted" title={file.error}>{file.error}</small>{/if}
						{#if problems[file.file_id]}<small class="error">{problems[file.file_id]}</small>{/if}
					</div>
					<div class="actions">
						<a href="/api/files/{file.file_id}/content" target="_blank" rel="noopener">Open file</a>
						{#if file.writable && !retried[file.file_id]}
							{#if file.can_download}
								<button
									class="primary"
									onclick={() => download(file)}
									disabled={downloading === file.file_id}
									title="A fresh open-access copy (arXiv, or by DOI via Unpaywall) replaces the damaged file"
								>
									{downloading === file.file_id ? 'Downloading…' : 'Download again'}
								</button>
							{:else}
								<a class="button" href={resolve('/items/[id]', { id: file.item_id })}
									>Upload a good copy</a
								>
							{/if}
							<button onclick={() => readAgain(file)}>Read again</button>
						{:else if retried[file.file_id]}
							<span class="muted">Reading…</span>
						{/if}
					</div>
				</li>
			{/each}
		</ul>
	</section>
	<h2>Papers without details</h2>
{/if}

{#if items === null}
	<p class="muted">Loading…</p>
{:else if items.length === 0}
	<p class="muted">Nothing to sort: every paper has its details.</p>
{:else}
	{#if total > items.length}<p class="muted">The first {items.length} of {total}.</p>{/if}
	<ul>
		{#each items as item (item.id)}
			<ItemRow {item}>
				{#snippet actions()}
					<form onsubmit={(event) => lookUp(event, item)}>
						<input
							bind:value={entered[item.id]}
							placeholder="DOI or arXiv ID, e.g. 10.1038/… or 2611.04768"
							aria-label="DOI or arXiv ID of {plainTitle(item.title)}"
						/>
						<button disabled={busy === item.id || !entered[item.id]?.trim()}>
							{busy === item.id ? 'Looking up…' : 'Look up'}
						</button>
					</form>
					{#if errors[item.id]}<p class="error">{errors[item.id]}</p>{/if}
				{/snippet}
			</ItemRow>
		{/each}
	</ul>
{/if}

<style>
	.head {
		margin-bottom: 12px;
	}
	h1 {
		margin: 0 0 6px;
	}
	.head p {
		max-width: 70ch;
		margin: 0;
	}
	ul {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	form {
		display: flex;
		gap: 8px;
		max-width: 560px;
	}
	form input {
		flex: 1;
		min-width: 0;
	}
	.error {
		margin: 6px 0 0;
	}
	.saved {
		color: var(--success);
	}
	h2 {
		margin: 20px 0 6px;
		font-size: var(--step-1);
	}
	.unreadable p {
		max-width: 70ch;
		margin: 0 0 10px;
	}
	.unreadable li {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: 8px 16px;
		padding: 10px 12px;
		border-left: 3px solid var(--danger);
		border-radius: 0 8px 8px 0;
		background: var(--rail);
		margin-bottom: 8px;
	}
	.what {
		display: grid;
		gap: 2px;
		min-width: 0;
		flex: 1 1 380px;
	}
	.what a {
		font-family: var(--serif);
		font-weight: 600;
	}
	.what small {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px;
	}
	.button {
		display: inline-flex;
		align-items: center;
		padding: 7px 14px;
		border: 1px solid var(--rule);
		border-radius: 999px;
		background: var(--surface);
		color: var(--ink);
		font-weight: 600;
		text-decoration: none;
	}
</style>
