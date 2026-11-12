<script lang="ts">
	import Title from '#lib/Title.svelte';
	import { plainTitle } from '#lib/title.svelte.ts';
	import { beforeNavigate, goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { untrack } from 'svelte';
	import {
		changeNote,
		errorMessage,
		linkItem,
		listItems,
		noteHistory,
		readNote,
		restoreNote,
		setNoteOwner,
		trashNote,
		unlinkItem,
		type Item
	} from '#lib/api/client.ts';
	import type { NoteDetail, RevisionOut } from '#lib/api/generated/types.gen.ts';
	import { copyText } from '#lib/clipboard.ts';
	import { formatDateTime } from '#lib/dates.svelte.ts';
	import { ago, shortAuthors } from '#lib/format.ts';
	import Markdown from '#lib/Markdown.svelte';
	import MenuButton from '#lib/MenuButton.svelte';
	import SharedIcon from '#lib/SharedIcon.svelte';
	import {
		isShared,
		libraryById,
		libraryName,
		loadOrganize,
		writableLibraries
	} from '#lib/organize.svelte.ts';

	/** One note's page: reading, writing with autosave, its papers and owner.
	 * Rendered anew for each note ({#key id} in the route), so nothing of one
	 * note can end up in another. */
	let { id, write = false }: { id: string; write?: boolean } = $props();

	// Saved this long after the last keystroke; failed saves retried after.
	const PAUSE = 1200;
	const RETRY = 5000;

	let note = $state<NoteDetail | null>(null);
	let etag = '';
	let notFound = $state(false);
	let text = $state('');
	let writing = $state(false);
	let status = $state<'saved' | 'saving' | 'unsaved' | 'conflict' | 'error'>('saved');
	let problem = $state('');
	/** The person's text when it could not be saved over someone else's. */
	let unsaved = $state('');
	let timer: ReturnType<typeof setTimeout> | undefined;

	const writable = $derived(
		!!note && !note.deleted_at && (libraryById(note.library_id)?.writable ?? false)
	);

	async function load() {
		const { data, response } = await readNote({ path: { note_id: id } });
		if (!data) {
			notFound = true;
			return;
		}
		note = data;
		etag = response?.headers.get('ETag') ?? '';
		text = data.text;
		status = 'saved';
	}

	$effect(() => {
		untrack(async () => {
			// Rights come with the owners: both before deciding how to open.
			await Promise.all([loadOrganize(), load()]);
			// A new note (or ?write) opens for writing.
			writing = writable && (!note?.text || write);
		});
	});

	function edited() {
		status = 'unsaved';
		clearTimeout(timer);
		timer = setTimeout(save, PAUSE);
	}

	// One save at a time: a save asked for while one runs follows it, with
	// the version (ETag) the first one got back.
	let saving: Promise<void> | null = null;
	let again = false;

	async function save(): Promise<void> {
		clearTimeout(timer);
		if (saving) {
			again = true;
			return saving;
		}
		if (!note || status === 'saved' || status === 'conflict') return;
		saving = send(note.id);
		try {
			await saving;
		} finally {
			saving = null;
		}
		if (again || status === 'unsaved') {
			again = false;
			if (status === 'unsaved') await save();
		}
	}

	async function send(noteId: string) {
		const sent = text;
		status = 'saving';
		const { data, error, response } = await changeNote({
			path: { note_id: noteId },
			body: { text: sent },
			headers: { 'If-Match': etag }
		});
		if (response?.status === 412) {
			status = 'conflict';
			return;
		}
		if (!data) {
			status = 'error';
			problem = errorMessage(error);
			timer = setTimeout(save, RETRY);
			return;
		}
		note = data;
		etag = response?.headers.get('ETag') ?? etag;
		// Typed on while saving: that is saved next.
		status = text === sent ? 'saved' : 'unsaved';
	}

	/** Someone else saved meanwhile: keep this text over theirs, or take
	 * theirs; this text stays at hand (below, and copied if possible). */
	async function resolveConflict(keepMine: boolean) {
		const mine = text;
		await load();
		if (keepMine) {
			text = mine;
			status = 'unsaved';
			await save();
			return;
		}
		unsaved = mine;
		problem = (await copyText(mine))
			? 'Your text is below and was copied to the clipboard.'
			: 'Your text is below.';
	}

	// Leaving: save what is not saved yet; warn when it cannot be (a
	// conflict or a failed save).
	const dirty = () => status !== 'saved';
	beforeNavigate((navigation) => {
		if (status === 'conflict' || status === 'error') {
			if (!confirm('Your latest text is not saved. Leave anyway?')) navigation.cancel();
			return;
		}
		if (dirty()) save();
	});
	$effect(() => {
		const leave = (event: BeforeUnloadEvent) => {
			if (!dirty()) return;
			save();
			event.preventDefault();
		};
		addEventListener('beforeunload', leave);
		return () => {
			removeEventListener('beforeunload', leave);
			clearTimeout(timer);
			if (status === 'unsaved') save();
		};
	});

	// The text area grows with the text, so the page scrolls, not the box.
	let area = $state<HTMLTextAreaElement>();
	$effect(() => {
		void text;
		if (!area) return;
		area.style.height = 'auto';
		area.style.height = `${area.scrollHeight + 2}px`;
	});
	$effect(() => {
		area?.focus();
	});

	/** The Markdown file, with what was just typed saved first. */
	async function download() {
		if (!note) return;
		await save();
		const link = document.createElement('a');
		link.href = `/api/notes/${note.id}/markdown`;
		link.download = '';
		link.click();
	}

	async function chooseOwner(select: HTMLSelectElement) {
		if (!note) return;
		await save();
		const { data, error, response } = await setNoteOwner({
			path: { note_id: note.id },
			body: { library_id: select.value }
		});
		if (!data) {
			problem = errorMessage(error);
			select.value = note.library_id; // back to the owner it still has
			return;
		}
		note = data;
		etag = response?.headers.get('ETag') ?? etag;
	}

	async function moveToTrash() {
		if (!note) return;
		await save();
		await trashNote({ path: { note_id: note.id } });
		await goto(resolve('/notes'));
	}

	async function restore() {
		if (!note) return;
		const { data, response } = await restoreNote({ path: { note_id: note.id } });
		if (data) {
			note = data;
			etag = response?.headers.get('ETag') ?? etag;
		}
	}

	// Papers the note is about.
	let picker = $state<HTMLDialogElement>();
	let words = $state('');
	let found = $state<Item[]>([]);
	let latest = 0;

	async function findPapers() {
		const request = ++latest;
		const { data } = await listItems({ query: { limit: 20, title: words.trim() || undefined } });
		if (request === latest && data) found = data;
	}

	function openPicker() {
		words = '';
		findPapers();
		picker?.showModal();
	}

	async function link(item: Item) {
		if (!note) return;
		const { data, response } = await linkItem({
			path: { note_id: note.id, item_id: item.id },
			body: {}
		});
		if (data) {
			note = data;
			etag = response?.headers.get('ETag') ?? etag;
		}
		picker?.close();
	}

	async function unlink(itemId: string) {
		if (!note) return;
		const { data, response } = await unlinkItem({
			path: { note_id: note.id, item_id: itemId }
		});
		if (data) {
			note = data;
			etag = response?.headers.get('ETag') ?? etag;
		}
	}

	// Earlier texts.
	let historyDialog = $state<HTMLDialogElement>();
	let revisions = $state<RevisionOut[]>([]);
	let shown = $state<RevisionOut | null>(null);

	async function openHistory() {
		if (!note) return;
		await save();
		const { data } = await noteHistory({ path: { note_id: note.id } });
		revisions = data ?? [];
		shown = revisions[0] ?? null;
		historyDialog?.showModal();
	}

	async function bringBack(revision: RevisionOut) {
		text = revision.text;
		status = 'unsaved';
		historyDialog?.close();
		await save();
	}
</script>

<svelte:head><title>{note?.title || 'Note'} · paperus</title></svelte:head>

{#if notFound}
	<p class="muted">This note does not exist, or you cannot see it.</p>
{:else if note}
	<div class="bar">
		<a class="back" href={resolve('/notes')}>Notes</a>
		<div class="tools">
			{#if writable}
				<span class="status" class:problem={status === 'error'} aria-live="polite">
					{status === 'saving'
						? 'Saving…'
						: status === 'unsaved'
							? 'Not saved yet'
							: status === 'error'
								? `Not saved: ${problem}`
								: status === 'saved' && note.changed_by
									? `Saved, ${ago(note.changed_at)}`
									: ''}
				</span>
				<div class="switch" role="group" aria-label="View">
					<button aria-pressed={writing} onclick={() => (writing = true)}>Write</button>
					<button
						aria-pressed={!writing}
						onclick={() => {
							writing = false;
							save();
						}}>Read</button
					>
				</div>
			{/if}
			{#if isShared(note.library_id)}<SharedIcon owner={note.library_id} />{/if}
			<MenuButton label="Note actions">
				<button role="menuitem" onclick={download}>Download Markdown</button>
				<button role="menuitem" onclick={openHistory}>Earlier versions</button>
				{#if writable}
					<hr />
					<button role="menuitem" class="danger" onclick={moveToTrash}>Move to trash</button>
				{/if}
			</MenuButton>
		</div>
	</div>

	{#if note.deleted_at}
		<p class="banner">
			This note is in the trash.
			{#if libraryById(note.library_id)?.writable}<button onclick={restore}>Restore</button>{/if}
		</p>
	{/if}
	{#if status === 'conflict'}
		<div class="banner" role="alert">
			<p>Someone else saved this note while you were writing.</p>
			<button onclick={() => resolveConflict(false)}>Show their version</button>
			<button onclick={() => resolveConflict(true)}>Keep mine</button>
		</div>
	{:else if problem && status !== 'error'}
		<p class="muted">{problem}</p>
	{/if}
	{#if unsaved}
		<details class="mine" open>
			<summary>Your text, not saved</summary>
			<textarea readonly aria-label="Your text, not saved" value={unsaved}></textarea>
			<button onclick={() => (unsaved = '')}>Done with it</button>
		</details>
	{/if}

	<div class="about">
		{#each note.items as paper (paper.item_id)}
			<span class="paper">
				<a
					href="{resolve('/items/[id]', { id: paper.item_id })}{paper.page
						? `?page=${paper.page}`
						: ''}"><Title text={paper.title} />{paper.page ? `, page ${paper.page}` : ''}</a
				>
				{#if writable}<button
						class="remove"
						aria-label="Not about {plainTitle(paper.title)}"
						title="Not about this paper"
						onclick={() => unlink(paper.item_id)}>×</button
					>{/if}
			</span>
		{/each}
		{#if writable}
			<button class="add" onclick={openPicker}
				>{note.items.length ? '+ Paper' : '+ About a paper'}</button
			>
			{#if writableLibraries().length > 1}
				<label class="owner"
					>Owner
					<select value={note.library_id} onchange={(event) => chooseOwner(event.currentTarget)}>
						{#each writableLibraries() as library (library.id)}
							<option value={library.id}>{libraryName(library.id)}</option>
						{/each}
					</select>
				</label>
			{/if}
		{/if}
	</div>

	{#if writing && writable}
		<textarea
			bind:this={area}
			bind:value={text}
			oninput={edited}
			onblur={() => save()}
			placeholder="# Title&#10;&#10;Write in Markdown: **bold**, *italic*, - lists, $formulas$…"
			aria-label="Note text"
			spellcheck="true"></textarea>
	{:else if text.trim()}
		<article class="sheet"><Markdown {text} /></article>
	{:else}
		<p class="muted">This note is empty.</p>
	{/if}

	<dialog bind:this={picker} aria-labelledby="picker-title">
		<h2 id="picker-title">About which paper?</h2>
		<input
			type="search"
			bind:value={words}
			oninput={findPapers}
			placeholder="Words from the title"
			aria-label="Search by title"
		/>
		<ul class="found">
			{#each found.filter((item) => !note?.items.some((p) => p.item_id === item.id)) as item (item.id)}
				<li>
					<button onclick={() => link(item)}>
						<strong><Title text={item.title} /></strong>
						<small>{shortAuthors(item.authors)}{item.year ? ` (${item.year})` : ''}</small>
					</button>
				</li>
			{:else}
				<li class="muted">No paper with these words in its title.</li>
			{/each}
		</ul>
		<div class="buttons"><button onclick={() => picker?.close()}>Cancel</button></div>
	</dialog>

	<dialog bind:this={historyDialog} class="history" aria-labelledby="history-title">
		<h2 id="history-title">Earlier versions</h2>
		{#if revisions.length === 0}
			<p class="muted">
				No earlier versions yet. Changes by the same person within ten minutes count as one.
			</p>
		{:else}
			<div class="versions">
				<ul>
					{#each revisions as revision (revision.id)}
						<li>
							<button aria-pressed={shown?.id === revision.id} onclick={() => (shown = revision)}>
								{revision.written_by ?? 'Someone'}<small
									>{formatDateTime(revision.written_at)}</small
								>
							</button>
						</li>
					{/each}
				</ul>
				{#if shown}<pre>{shown.text}</pre>{/if}
			</div>
		{/if}
		<div class="buttons">
			<button onclick={() => historyDialog?.close()}>Close</button>
			{#if shown && writable}
				<button class="primary" onclick={() => shown && bringBack(shown)}
					>Bring this version back</button
				>
			{/if}
		</div>
	</dialog>
{/if}

<style>
	.bar {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: center;
		gap: 12px;
		margin-bottom: 10px;
	}
	.back {
		color: var(--muted);
	}
	.tools {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		min-width: 0;
		align-items: center;
		gap: 10px;
	}
	.status {
		min-width: 0;
		max-width: 40ch;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.status.problem {
		color: var(--danger);
	}
	.switch {
		display: inline-flex;
		padding: 3px;
		border-radius: 999px;
		background: var(--rail);
	}
	.switch button {
		padding: 4px 12px;
		border: none;
		border-radius: 999px;
		background: none;
		color: var(--muted);
		font-size: var(--step--1);
		font-weight: 600;
	}
	.switch button[aria-pressed='true'] {
		background: var(--surface);
		color: var(--ink);
		box-shadow: 0 1px 2px rgb(27 36 64 / 0.12);
	}
	.banner {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px 12px;
		margin: 0 0 12px;
		padding: 10px 14px;
		border-radius: 8px;
		background: color-mix(in srgb, var(--highlighter) 18%, var(--surface));
	}
	.mine {
		display: grid;
		gap: 8px;
		margin: 0 0 12px;
	}
	.mine textarea {
		min-height: 12em;
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
		font-size: 0.9rem;
	}
	.mine button {
		justify-self: start;
	}
	.banner p {
		margin: 0;
	}
	.about {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px 8px;
		margin-bottom: 14px;
		font-size: var(--step--1);
	}
	.paper {
		display: inline-flex;
		align-items: center;
		max-width: 100%;
		padding: 2px 4px 2px 10px;
		border: 1px solid var(--rule);
		border-radius: 999px;
	}
	.paper a {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--ink);
	}
	.remove {
		padding: 0 6px;
		border: none;
		background: none;
		color: var(--muted);
	}
	.add {
		padding: 2px 10px;
		border: 1px dashed var(--rule);
		border-radius: 999px;
		background: none;
		color: var(--royal);
	}
	.owner {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		margin-left: auto;
		color: var(--muted);
	}
	.owner select {
		width: auto;
	}
	textarea {
		display: block;
		width: 100%;
		max-width: 80ch;
		min-height: 60vh;
		padding: 18px 20px;
		border: 1px solid var(--rule);
		border-radius: 8px;
		background: var(--surface);
		color: var(--ink);
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
		font-size: 0.95rem;
		line-height: 1.65;
		resize: none;
		overflow: hidden;
	}
	.sheet {
		max-width: 76ch;
		font-family: var(--serif);
		line-height: 1.7;
		overflow-wrap: anywhere;
	}
	dialog {
		width: min(620px, calc(100vw - 32px));
		max-height: min(760px, calc(100dvh - 32px));
		padding: 20px 22px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	dialog.history {
		width: min(900px, calc(100vw - 32px));
	}
	dialog::backdrop {
		background: rgb(10 14 30 / 0.4);
	}
	dialog h2 {
		margin: 0 0 12px;
		font-size: var(--step-2);
	}
	.found {
		margin: 10px 0;
		padding: 0;
		list-style: none;
		max-height: 50vh;
		overflow-y: auto;
	}
	.found button {
		display: grid;
		width: 100%;
		padding: 8px 10px;
		border: none;
		border-radius: 8px;
		background: none;
		text-align: left;
		color: var(--ink);
	}
	.found button:hover {
		background: var(--rail);
	}
	.found small {
		color: var(--muted);
	}
	.versions {
		display: grid;
		grid-template-columns: minmax(160px, 220px) 1fr;
		gap: 14px;
		min-height: 0;
	}
	@media (max-width: 640px) {
		.versions {
			grid-template-columns: 1fr;
		}
	}
	.versions ul {
		margin: 0;
		padding: 0;
		list-style: none;
		max-height: 55vh;
		overflow-y: auto;
	}
	.versions li button {
		display: grid;
		width: 100%;
		padding: 6px 10px;
		border: none;
		border-radius: 8px;
		background: none;
		text-align: left;
		color: var(--ink);
	}
	.versions li button[aria-pressed='true'] {
		background: var(--rail);
	}
	.versions small {
		color: var(--muted);
	}
	.versions pre {
		margin: 0;
		max-height: 55vh;
		overflow: auto;
		padding: 12px 14px;
		border-radius: 8px;
		background: var(--rail);
		white-space: pre-wrap;
		font-size: 0.86em;
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 12px;
	}
</style>
