<script lang="ts">
	import { listAuthors, listJournals } from '#lib/api/client.ts';
	import type { AuthorRow, JournalOut, Rules } from '#lib/api/generated/types.gen.ts';
	import { authorName, rememberAuthor } from '#lib/authorNames.svelte.ts';
	import DateInput from '#lib/DateInput.svelte';
	import { TYPE_NAMES } from '#lib/format.ts';
	import { libraryById, libraryName, organize } from '#lib/organize.svelte.ts';
	import { personName } from '#lib/names.svelte.ts';

	/** The rules of a smart collection owned by ``library``: papers that
	 * match all rules given. */
	let { rules = $bindable(), library }: { rules: Rules; library: string } = $props();

	const uid = $props.id();
	const group = $derived(libraryById(library)?.kind === 'group');
	// A group's smart collection holds only the group's papers, so only its
	// tags matter; one's own may use any tag one can see.
	const tags = $derived(
		organize.tags
			.filter((t) => !group || t.library_id === library)
			.toSorted((a, b) => a.name.localeCompare(b.name))
	);
	const types = Object.entries(TYPE_NAMES).filter(([type]) => type !== 'note');

	type TagRule = 'tags_all' | 'tags_any' | 'tags_none';
	/** How an added tag counts; its chip says so ("or", "not"). */
	const TAG_RULES: [TagRule, string][] = [
		['tags_all', 'has'],
		['tags_any', 'has any of'],
		['tags_none', 'has not']
	];
	let tagRule = $state<TagRule>('tags_all');
	const usedTags = $derived(
		new Set([...(rules.tags_all ?? []), ...(rules.tags_any ?? []), ...(rules.tags_none ?? [])])
	);

	function tagLabel(id: string): string {
		const tag = organize.tags.find((t) => t.id === id);
		if (!tag) return '?';
		// Tags of the same name in several libraries: say whose.
		const twins = organize.tags.filter((t) => t.name === tag.name).length > 1;
		const name = twins ? `${tag.name} (${libraryName(tag.library_id)})` : tag.name;
		// Only on papers from their details: a keyword.
		return !tag.sources?.manual && tag.sources?.automatic ? `${name} (keyword)` : name;
	}

	function addTag(rule: TagRule, id: string) {
		if (id && !(rules[rule] ?? []).includes(id)) rules[rule] = [...(rules[rule] ?? []), id];
	}
	function removeTag(rule: TagRule, id: string) {
		rules[rule] = (rules[rule] ?? []).filter((t) => t !== id);
	}
	function toggle(list: 'types' | 'owners', value: string) {
		const current = rules[list] ?? [];
		rules[list] = current.includes(value)
			? current.filter((v) => v !== value)
			: [...current, value];
	}
	// Older rules give years: shown (and saved) as their first and last day.
	$effect.pre(() => {
		if (rules.year_from != null && !rules.published_from)
			rules.published_from = `${String(rules.year_from).padStart(4, '0')}-01-01`;
		if (rules.year_to != null && !rules.published_to)
			rules.published_to = `${String(rules.year_to).padStart(4, '0')}-12-31`;
		if (rules.year_from != null || rules.year_to != null) {
			rules.year_from = null;
			rules.year_to = null;
		}
	});

	// Authors, found by name.
	let authorSearch = $state('');
	let authorsFound = $state<AuthorRow[]>([]);
	$effect(() => {
		const words = authorSearch.trim();
		if (words.length < 2) {
			authorsFound = [];
			return;
		}
		const timer = setTimeout(async () => {
			const { data } = await listAuthors({ query: { q: words, limit: 6 } });
			if (words === authorSearch.trim()) {
				authorsFound = (data ?? []).filter((a) => !(rules.authors ?? []).includes(a.id));
			}
		}, 250);
		return () => clearTimeout(timer);
	});
	function addAuthor(author: AuthorRow) {
		rememberAuthor(author.id, personName(author));
		rules.authors = [...(rules.authors ?? []), author.id];
		authorSearch = '';
		authorsFound = [];
	}

	// Journals and venues of the library, found by words in their names.
	let journalSearch = $state('');
	let journalsFound = $state<JournalOut[]>([]);
	$effect(() => {
		const words = journalSearch.trim();
		if (!words) {
			journalsFound = [];
			return;
		}
		const timer = setTimeout(async () => {
			const { data } = await listJournals({ query: { q: words, limit: 6 } });
			if (words === journalSearch.trim()) {
				journalsFound = (data ?? []).filter((j) => !(rules.journals ?? []).includes(j.name));
			}
		}, 200);
		return () => clearTimeout(timer);
	});
	function addJournal(name: string) {
		rules.journals = [...(rules.journals ?? []), name];
		journalSearch = '';
		journalsFound = [];
	}

	/** Empty fields: no rule. */
	function number(value: string): number | null {
		const parsed = Number.parseInt(value, 10);
		return Number.isFinite(parsed) ? parsed : null;
	}
</script>

<fieldset class="rules">
	<legend>Papers that match all of these (leave out what does not matter)</legend>

	<div class="row">
		<span class="name" id="{uid}-tags">Tags</span>
		<div class="chips">
			{#each TAG_RULES as [rule, how] (rule)}
				{#each rules[rule] ?? [] as id (id)}
					<span class="chip" class:not={rule === 'tags_none'}
						>{#if rule !== 'tags_all'}<span class="how">{rule === 'tags_any' ? 'or' : 'not'}</span
							>{/if}{tagLabel(id)}<button
							type="button"
							aria-label="Remove {tagLabel(id)} ({how})"
							onclick={() => removeTag(rule, id)}>×</button
						></span
					>
				{/each}
			{/each}
			<select aria-label="How the next tag counts" bind:value={tagRule} class="how-select">
				{#each TAG_RULES as [rule, how] (rule)}<option value={rule}>{how}</option>{/each}
			</select>
			<select
				aria-label="Add a tag"
				value=""
				onchange={(event) => {
					addTag(tagRule, event.currentTarget.value);
					event.currentTarget.value = '';
				}}
			>
				<option value="">Add a tag…</option>
				{#each tags.filter((t) => !usedTags.has(t.id)) as tag (tag.id)}
					<option value={tag.id}>{tagLabel(tag.id)}</option>
				{/each}
			</select>
		</div>
	</div>

	<div class="row">
		<span class="name">Authors</span>
		<div class="chips">
			{#each rules.authors ?? [] as id (id)}
				<span class="chip"
					>{authorName(id)}<button
						type="button"
						aria-label="Remove {authorName(id)}"
						onclick={() => (rules.authors = (rules.authors ?? []).filter((a) => a !== id))}
						>×</button
					></span
				>
			{/each}
			<input
				type="search"
				class="search"
				bind:value={authorSearch}
				placeholder="Add an author…"
				aria-label="Authors: find an author"
				autocomplete="off"
			/>
		</div>
		{#if authorsFound.length}
			<div class="chips found">
				{#each authorsFound as author (author.id)}
					<button type="button" class="pick" onclick={() => addAuthor(author)}
						>{personName(author)} <span class="muted">{author.papers}</span></button
					>
				{/each}
			</div>
		{/if}
	</div>

	<div class="row">
		<span class="name">Journal</span>
		<div class="chips">
			{#each rules.journals ?? [] as name (name)}
				<span class="chip"
					>{name}<button
						type="button"
						aria-label="Remove {name}"
						onclick={() => (rules.journals = (rules.journals ?? []).filter((j) => j !== name))}
						>×</button
					></span
				>
			{/each}
			<input
				type="search"
				class="search"
				bind:value={journalSearch}
				placeholder="Add a journal…"
				aria-label="Journal: find a journal"
				autocomplete="off"
			/>
		</div>
		{#if journalsFound.length}
			<div class="chips found">
				{#each journalsFound as journal (journal.name)}
					<button type="button" class="pick" onclick={() => addJournal(journal.name)}
						>{journal.name} <span class="muted">{journal.papers}</span></button
					>
				{/each}
			</div>
		{/if}
	</div>

	<div class="row">
		<span class="name">Type</span>
		<div class="chips">
			{#each rules.types ?? [] as type (type)}
				<span class="chip"
					>{TYPE_NAMES[type] ?? type}<button
						type="button"
						aria-label="Remove {TYPE_NAMES[type] ?? type}"
						onclick={() => toggle('types', type)}>×</button
					></span
				>
			{/each}
			<select
				aria-label="Add a type"
				value=""
				onchange={(event) => {
					if (event.currentTarget.value) toggle('types', event.currentTarget.value);
					event.currentTarget.value = '';
				}}
			>
				<option value="">Add a type…</option>
				{#each types.filter(([type]) => !(rules.types ?? []).includes(type)) as [type, name] (type)}
					<option value={type}>{name}</option>
				{/each}
			</select>
		</div>
	</div>

	<div class="row">
		<span class="name">Published</span>
		<div class="dates">
			<span class="date"
				><label for="{uid}-from">from</label>
				<DateInput
					id="{uid}-from"
					bind:value={rules.published_from}
					max={rules.published_to}
				/></span
			>
			<span class="date"
				><label for="{uid}-to">to</label>
				<DateInput id="{uid}-to" bind:value={rules.published_to} min={rules.published_from} /></span
			>
		</div>
	</div>

	{#if !group && organize.libraries.length > 1}
		<div class="row">
			<span class="name" id="{uid}-owners">Owned by</span>
			<div class="chips" role="group" aria-labelledby="{uid}-owners">
				{#each organize.libraries as owner (owner.id)}
					<button
						type="button"
						class="toggle"
						aria-pressed={(rules.owners ?? []).includes(owner.id)}
						onclick={() => toggle('owners', owner.id)}>{libraryName(owner.id)}</button
					>
				{/each}
				{#if !(rules.owners ?? []).length}<span class="muted small">all</span>{/if}
			</div>
		</div>
	{/if}

	<div class="row">
		<span class="name">Added</span>
		<label class="days"
			>in the last <input
				type="number"
				inputmode="numeric"
				min="1"
				max="36500"
				placeholder="any"
				value={rules.added_days ?? ''}
				oninput={(event) => (rules.added_days = number(event.currentTarget.value))}
			/> days</label
		>
	</div>
</fieldset>

<style>
	.rules {
		display: grid;
		gap: 12px;
		/* A fieldset is otherwise as wide as its longest line (phones). */
		min-width: 0;
		margin: 0;
		padding: 12px 14px;
		border: 1px solid var(--rule);
		border-radius: 8px;
	}
	legend {
		padding: 0 4px;
		font-size: var(--step--1);
		color: var(--muted);
	}
	/* One line per rule: its name beside it; above it on a phone. */
	.row {
		display: grid;
		grid-template-columns: 7rem minmax(0, 1fr);
		align-items: center;
		gap: 4px 12px;
	}
	.found {
		grid-column: 2;
	}
	.name {
		font-weight: 600;
	}
	@media (max-width: 560px) {
		.row {
			grid-template-columns: minmax(0, 1fr);
		}
		.found {
			grid-column: 1;
		}
	}
	.how {
		margin-right: 4px;
		font-size: 0.85em;
		opacity: 0.75;
	}
	/* Without the tag: grey, its "not" in front. */
	.chip.not {
		background: var(--rail);
		color: var(--ink);
	}
	.chips .how-select {
		min-width: 0;
	}
	.toggle {
		padding: 2px 12px;
		border-radius: 999px;
	}
	.toggle[aria-pressed='true'] {
		border-color: var(--royal);
		background: var(--tag-blue-bg);
		color: var(--tag-blue-ink);
	}
	.small {
		font-size: var(--step--1);
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px 10px;
	}
	.search {
		flex: 1 1 12rem;
		max-width: 20rem;
	}
	.pick {
		padding: 2px 10px;
		border-radius: 14px;
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		padding: 2px 4px 2px 10px;
		border-radius: 999px;
		background: var(--tag-blue-bg);
		color: var(--tag-blue-ink);
		font-size: var(--step--1);
	}
	.chip button {
		width: 22px;
		height: 22px;
		padding: 0;
		border: none;
		border-radius: 50%;
		background: none;
		color: inherit;
		line-height: 1;
	}
	.chip button:hover {
		background: rgb(0 0 0 / 0.08);
	}
	.chips select {
		width: auto;
		min-width: 9rem;
		/* Long tag names would widen the dialog past a phone's screen. */
		max-width: 100%;
	}
	.dates,
	.days {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		font-weight: 400;
	}
	.dates .date {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.dates :global(input.native) {
		width: auto;
		max-width: 11rem;
	}
	input[type='number'] {
		width: 6.5rem;
	}
</style>
