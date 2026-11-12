<script lang="ts">
	import {
		errorMessage,
		listAuthors,
		setOverrides,
		setOwner,
		type ItemDetail
	} from '#lib/api/client.ts';
	import type { AuthorRow } from '#lib/api/generated/types.gen.ts';
	import { TYPE_NAMES } from '#lib/format.ts';
	import { personName } from '#lib/names.svelte.ts';
	import { isShared, libraryName, writableLibraries } from '#lib/organize.svelte.ts';

	/** Edit a paper: its details for citing (kept as edits over the details
	 * its versions bring, field by field) and its owner. */
	let { item, etag, onsaved }: { item: ItemDetail; etag: string | undefined; onsaved: () => void } =
		$props();

	type Person = Record<string, unknown>;
	/** An author as edited: "Family, Given" (or a name as it stands), and
	 * the details' entry while the text is unchanged (its ORCID iD and more). */
	type Row = {
		key: number;
		text: string;
		person?: Person;
		/** An author of the library's picked: their name and ORCID iD. */
		picked?: string;
		orcid?: string | null;
	};
	type Field = 'title' | 'author' | 'issued' | 'container-title' | 'type' | 'abstract';

	let dialog = $state<HTMLDialogElement>();
	let title = $state('');
	let rows = $state<Row[]>([]);
	let year = $state('');
	let venue = $state('');
	let type = $state('');
	let abstract = $state('');
	let owner = $state('');
	let error = $state('');
	let saving = $state(false);
	// Fields set back to the details' own value: their edits go on saving.
	let restored = $state<Partial<Record<Field, boolean>>>({});
	let initial: Record<Field, string> = {
		title: '',
		author: '',
		issued: '',
		'container-title': '',
		type: '',
		abstract: ''
	};
	let nextKey = 0;

	const owners = $derived(writableLibraries());
	const leavingGroup = $derived(owner !== item.library_id && isShared(item.library_id));
	// What the paper's details say without the edits: its preferred version's.
	const original = $derived(
		(item.versions.find((v) => v.id === item.preferred_version_id)?.csl ?? {}) as Record<
			string,
			unknown
		>
	);
	const types = $derived([
		...Object.entries(TYPE_NAMES).filter(([value]) => value !== 'note'),
		...(type && !(type in TYPE_NAMES) ? [[type, typeName(type)]] : [])
	]);

	function typeName(value: string): string {
		return value.replace(/-/g, ' ').replace(/^./, (c) => c.toUpperCase());
	}

	function nameOf(person: Person): string {
		const family = String(person.family ?? '').trim();
		const given = String(person.given ?? '').trim();
		if (family) return given ? `${family}, ${given}` : family;
		return String(person.literal ?? '').trim();
	}

	function rowsOf(csl: Record<string, unknown>): Row[] {
		const people = Array.isArray(csl.author) ? (csl.author as Person[]) : [];
		return people
			.filter((p) => p && typeof p === 'object' && nameOf(p))
			.map((person) => ({ key: nextKey++, text: nameOf(person), person }));
	}

	function yearOf(csl: Record<string, unknown>): string {
		for (const key of ['issued', 'published-print', 'published-online']) {
			const parts = (csl[key] as { 'date-parts'?: unknown[][] } | undefined)?.['date-parts'];
			const value = Number(parts?.[0]?.[0]);
			if (Number.isInteger(value) && value > 0) return String(value);
		}
		return '';
	}

	function venueOf(csl: Record<string, unknown>): string {
		const value = csl['container-title'];
		return String((Array.isArray(value) ? value[0] : value) ?? '');
	}

	/** An abstract as text: markup out, paragraphs between blank lines. */
	function plain(markup: unknown): string {
		if (!markup) return '';
		const text = String(markup)
			.replace(/<\/(?:jats:)?p>/g, '\n\n')
			.replace(/<[^>]+>/g, '');
		const parsed = new DOMParser().parseFromString(text, 'text/html').body.textContent ?? '';
		return parsed
			.split(/\n\s*\n/)
			.map((p) => p.replace(/\s+/g, ' ').trim())
			.filter(Boolean)
			.join('\n\n');
	}

	function authorsText(list: Row[]): string {
		return list
			.map((r) => r.text.trim())
			.filter(Boolean)
			.join('\n');
	}

	/** The fields' values now, as text. */
	function current(): Record<Field, string> {
		return {
			title: title.trim(),
			author: authorsText(rows),
			issued: year.trim(),
			'container-title': venue.trim(),
			type,
			abstract: abstract.trim()
		};
	}

	/** The details' own values, as text (what "Restore original" shows). */
	function originals(): Record<Field, string> {
		return {
			title: String(
				(Array.isArray(original.title) ? original.title[0] : original.title) ?? ''
			).trim(),
			author: authorsText(rowsOf(original)),
			issued: yearOf(original),
			'container-title': venueOf(original),
			type: String(original.type ?? ''),
			abstract: plain(original.abstract)
		};
	}

	export function open() {
		title = item.title;
		rows = rowsOf(item.csl);
		year = item.year ? String(item.year) : '';
		venue = item.container_title ?? '';
		type = item.type;
		abstract = item.abstract ?? '';
		owner = item.library_id;
		restored = {};
		initial = current();
		error = '';
		dialog?.showModal();
	}

	function restore(field: Field) {
		const csl = original;
		if (field === 'title') title = originals().title || item.title;
		if (field === 'author') rows = rowsOf(csl);
		if (field === 'issued') year = yearOf(csl);
		if (field === 'container-title') venue = venueOf(csl);
		if (field === 'type') type = TYPE_NAMES[String(csl.type)] ? String(csl.type) : type;
		if (field === 'abstract') abstract = plain(csl.abstract);
		restored[field] = true;
	}

	function edited(field: Field) {
		restored[field] = false;
	}

	/** The field as CSL-JSON; null hides it. */
	function cslValue(field: Field, text: string): unknown {
		if (!text) return null;
		if (field === 'issued') return { 'date-parts': [[Number(text)]] };
		if (field !== 'author') return text;
		return rows
			.filter((r) => r.text.trim())
			.map((row): Person => {
				const text = row.text.trim();
				if (row.person && nameOf(row.person) === text) return row.person;
				const comma = text.indexOf(',');
				const person: Person =
					comma < 0
						? { literal: text }
						: {
								family: text.slice(0, comma).trim(),
								...(text.slice(comma + 1).trim() && { given: text.slice(comma + 1).trim() })
							};
				if (row.orcid && text === row.picked) person.ORCID = `https://orcid.org/${row.orcid}`;
				return person;
			});
	}

	/** The edits after this dialog: restored fields lose theirs, changed
	 * ones get one (none where they now match the details' own value). */
	function overrides(): Record<string, unknown> {
		const result: Record<string, unknown> = { ...item.overrides };
		const now = current();
		const before = originals();
		for (const field of Object.keys(now) as Field[]) {
			if (restored[field]) {
				delete result[field];
			} else if (now[field] !== initial[field]) {
				if (now[field] === before[field]) delete result[field];
				else result[field] = cslValue(field, now[field]);
			}
		}
		return result;
	}

	const changed = (a: Record<string, unknown>, b: Record<string, unknown>) =>
		JSON.stringify(a) !== JSON.stringify(b);

	async function save(event: SubmitEvent) {
		event.preventDefault();
		if (year.trim() && !/^\d{1,4}$/.test(year.trim())) {
			error = 'The year is a number, like 2025.';
			return;
		}
		saving = true;
		error = '';
		const edits = overrides();
		if (changed(edits, item.overrides)) {
			const { error: failure, response } = await setOverrides({
				path: { item_id: item.id },
				body: edits,
				headers: { 'if-match': etag }
			});
			if (response?.status === 412) {
				error = 'Someone changed this paper in the meantime; close and try again.';
			} else if (failure) {
				error = errorMessage(failure);
			}
		}
		if (!error && owner !== item.library_id) {
			const { error: failure } = await setOwner({
				path: { item_id: item.id },
				body: { library_id: owner }
			});
			if (failure) error = errorMessage(failure);
		}
		saving = false;
		if (error) return;
		dialog?.close();
		onsaved();
	}

	// Authors: suggestions from the library's, for the row being typed in.
	let typing = $state<number | null>(null);
	let found = $state<AuthorRow[]>([]);
	$effect(() => {
		const row = rows.find((r) => r.key === typing);
		const words = row?.text.trim() ?? '';
		if (
			words.length < 2 ||
			words === row?.picked ||
			(row?.person && nameOf(row.person) === words)
		) {
			found = [];
			return;
		}
		const timer = setTimeout(async () => {
			const { data } = await listAuthors({ query: { q: words, limit: 6 } });
			if (row && words === row.text.trim()) {
				found = (data ?? []).filter((a) => a.written !== words);
			}
		}, 250);
		return () => clearTimeout(timer);
	});

	function pick(row: Row, author: AuthorRow) {
		row.text = row.picked = author.written;
		row.person = undefined;
		row.orcid = author.orcid;
		found = [];
		edited('author');
		document.getElementById(`author-${row.key}`)?.focus();
	}

	function addRow() {
		const row = { key: nextKey++, text: '' };
		rows.push(row);
		edited('author');
		requestAnimationFrame(() => document.getElementById(`author-${row.key}`)?.focus());
	}

	function move(index: number, by: number) {
		const [row] = rows.splice(index, 1);
		rows.splice(index + by, 0, row);
		edited('author');
	}

	function remove(index: number) {
		rows.splice(index, 1);
		edited('author');
	}

	function suggestionKeys(event: KeyboardEvent) {
		if (event.key === 'ArrowDown' && found.length) {
			event.preventDefault();
			(event.currentTarget as HTMLElement)
				.closest('li')
				?.querySelector<HTMLButtonElement>('.suggestions button')
				?.focus();
		}
	}
</script>

{#snippet restoreButton(field: Field, name: string, shown: string)}
	{#if field in item.overrides && !restored[field]}
		<button
			type="button"
			class="restore"
			aria-label="Restore original {name}"
			title={shown ? `From the paper's details: ${shown}` : 'The details have none'}
			onclick={() => restore(field)}>Restore original</button
		>
	{/if}
{/snippet}

<dialog bind:this={dialog} aria-labelledby="item-edit-title">
	<form onsubmit={save}>
		<h2 id="item-edit-title">Edit</h2>
		<p class="note">Your changes are kept when the paper's details are looked up again.</p>
		<div class="field">
			<label for="edit-title">Title</label>
			{@render restoreButton('title', 'title', originals().title)}
			<textarea id="edit-title" bind:value={title} oninput={() => edited('title')} rows="3" required
			></textarea>
		</div>

		<div class="field" role="group" aria-labelledby="edit-authors">
			<span id="edit-authors" class="label">Authors</span>
			{@render restoreButton(
				'author',
				'authors',
				authorsText(rowsOf(original)).replace(/\n/g, '; ')
			)}
			{#if rows.length}
				<ol>
					{#each rows as row, i (row.key)}
						<li
							onfocusout={(event) => {
								if (!event.currentTarget.contains(event.relatedTarget as Node)) typing = null;
							}}
						>
							<div class="author">
								<input
									id="author-{row.key}"
									bind:value={row.text}
									oninput={() => edited('author')}
									onfocus={() => (typing = row.key)}
									onkeydown={suggestionKeys}
									placeholder="Family, Given"
									aria-label="Author {i + 1}"
									autocomplete="off"
								/>
								<button
									type="button"
									class="icon"
									aria-label="Move author {i + 1} up"
									disabled={i === 0}
									onclick={() => move(i, -1)}>↑</button
								>
								<button
									type="button"
									class="icon"
									aria-label="Move author {i + 1} down"
									disabled={i === rows.length - 1}
									onclick={() => move(i, 1)}>↓</button
								>
								<button
									type="button"
									class="icon"
									aria-label="Remove author {i + 1}"
									onclick={() => remove(i)}>×</button
								>
							</div>
							{#if typing === row.key && found.length}
								<div class="suggestions" role="group" aria-label="Authors in the library">
									{#each found as author (author.id)}
										<button type="button" onclick={() => pick(row, author)}
											>{personName(author)}
											<span class="muted"
												>{author.papers} {author.papers === 1 ? 'paper' : 'papers'}</span
											></button
										>
									{/each}
								</div>
							{/if}
						</li>
					{/each}
				</ol>
			{/if}
			<div class="add"><button type="button" onclick={addRow}>Add author</button></div>
		</div>

		<div class="row">
			<div class="field year">
				<label for="edit-year">Year</label>
				<input
					id="edit-year"
					bind:value={year}
					oninput={() => edited('issued')}
					inputmode="numeric"
					autocomplete="off"
				/>
				{@render restoreButton('issued', 'year', yearOf(original))}
			</div>
			<div class="field">
				<label for="edit-type">Type</label>
				<select id="edit-type" bind:value={type} onchange={() => edited('type')}>
					{#each types as [value, label] (value)}<option {value}>{label}</option>{/each}
				</select>
				{@render restoreButton('type', 'type', TYPE_NAMES[String(original.type)] ?? '')}
			</div>
		</div>
		<div class="field">
			<label for="edit-venue">Journal or venue</label>
			{@render restoreButton('container-title', 'journal', venueOf(original))}
			<input id="edit-venue" bind:value={venue} oninput={() => edited('container-title')} />
		</div>
		<div class="field">
			<label for="edit-abstract">Abstract</label>
			{@render restoreButton('abstract', 'abstract', plain(original.abstract).slice(0, 200))}
			<textarea id="edit-abstract" bind:value={abstract} oninput={() => edited('abstract')} rows="5"
			></textarea>
		</div>

		{#if owners.length > 1 || owner !== owners[0]?.id}
			<label>
				Owner
				<select bind:value={owner}>
					{#if !owners.some((o) => o.id === item.library_id)}
						<option value={item.library_id}>{libraryName(item.library_id)}</option>
					{/if}
					{#each owners as option (option.id)}
						<option value={option.id}>{libraryName(option.id)}</option>
					{/each}
				</select>
			</label>
			<p class="note">
				{#if owner === item.library_id}
					{isShared(owner)
						? 'Shared: everyone in the group sees it.'
						: 'Private: only you see it, until you give it to a group.'}
				{:else if isShared(owner)}
					{libraryName(owner)} gets this paper; everyone in the group sees it.
				{:else}
					It becomes yours.
				{/if}
				{#if leavingGroup}
					{libraryName(item.library_id)} no longer sees it, and its collections let it go.
				{/if}
			</p>
		{/if}
		{#if error}<p class="error">{error}</p>{/if}
		<div class="buttons">
			<button type="button" onclick={() => dialog?.close()}>Cancel</button>
			<button class="primary" disabled={saving}>Save</button>
		</div>
	</form>
</dialog>

<style>
	dialog {
		width: min(600px, calc(100vw - 32px));
		max-height: calc(100dvh - 32px);
		padding: 22px 24px 24px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	dialog::backdrop {
		background: rgb(10 14 30 / 0.4);
	}
	form {
		display: grid;
		gap: 14px;
	}
	h2 {
		margin: 0;
		font-size: var(--step-2);
	}
	label,
	.label {
		font-weight: 600;
	}
	label {
		display: grid;
		gap: 6px;
	}
	.field {
		display: grid;
		grid-template-columns: 1fr auto;
		align-items: baseline;
		gap: 6px;
	}
	.field > :is(input, textarea, select, ol, .add) {
		grid-column: 1 / -1;
	}
	.year {
		max-width: 8em;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: 14px;
	}
	.row > .field:last-child {
		flex: 1;
	}
	.year > .restore {
		grid-column: 1 / -1;
		justify-self: start;
	}
	label :global(select) {
		font-weight: 400;
	}
	textarea {
		resize: vertical;
	}
	#edit-title {
		font-family: var(--serif);
	}
	ol {
		display: grid;
		gap: 6px;
		margin: 0;
		padding: 0;
		list-style: none;
		max-height: 18rem;
		overflow-y: auto;
	}
	.author {
		display: flex;
		gap: 4px;
	}
	.author input {
		flex: 1;
		min-width: 0;
	}
	.icon {
		min-width: 2.2em;
		padding-inline: 0.4em;
	}
	.suggestions {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-top: 4px;
	}
	.suggestions button {
		font-size: var(--step--1);
	}
	.restore {
		padding: 0;
		border: 0;
		background: none;
		color: var(--accent-text);
		font-size: var(--step--1);
		font-weight: 400;
		cursor: pointer;
	}
	.restore:hover {
		text-decoration: underline;
	}
	.muted {
		color: var(--muted);
	}
	.note {
		margin: -6px 0 0;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
	.error {
		margin: 0;
	}
</style>
