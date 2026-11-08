<script lang="ts">
	import { listAuthors } from '#lib/api/client.ts';
	import type { AuthorRow, Rules } from '#lib/api/generated/types.gen.ts';
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
	const TAG_RULES: [TagRule, string][] = [
		['tags_all', 'With all of these tags'],
		['tags_any', 'With any of these tags'],
		['tags_none', 'Without these tags']
	];

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

	/** Empty fields: no rule. */
	function number(value: string): number | null {
		const parsed = Number.parseInt(value, 10);
		return Number.isFinite(parsed) ? parsed : null;
	}
</script>

<fieldset class="rules">
	<legend>Papers that match all of these (leave out what does not matter)</legend>
	{#each TAG_RULES as [rule, label] (rule)}
		<div class="row">
			<span class="name">{label}</span>
			<div class="chips">
				{#each rules[rule] ?? [] as id (id)}
					<span class="chip"
						>{tagLabel(id)}<button
							type="button"
							aria-label="Remove {tagLabel(id)}"
							onclick={() => removeTag(rule, id)}>×</button
						></span
					>
				{/each}
				<select
					aria-label="{label}: add a tag"
					value=""
					onchange={(event) => {
						addTag(rule, event.currentTarget.value);
						event.currentTarget.value = '';
					}}
				>
					<option value="">Add a tag…</option>
					{#each tags.filter((t) => !(rules[rule] ?? []).includes(t.id)) as tag (tag.id)}
						<option value={tag.id}>{tagLabel(tag.id)}</option>
					{/each}
				</select>
			</div>
		</div>
	{/each}

	<div class="row">
		<span class="name">By these authors</span>
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
				class="author-search"
				bind:value={authorSearch}
				placeholder="Add an author…"
				aria-label="By these authors: find an author"
				autocomplete="off"
			/>
		</div>
		{#if authorsFound.length}
			<div class="chips">
				{#each authorsFound as author (author.id)}
					<button type="button" class="pick" onclick={() => addAuthor(author)}
						>{personName(author)} <span class="muted">{author.papers}</span></button
					>
				{/each}
			</div>
		{/if}
	</div>

	<div class="row">
		<span class="name">Of these types</span>
		<div class="chips">
			{#each types as [type, name] (type)}
				<label class="check"
					><input
						type="checkbox"
						checked={(rules.types ?? []).includes(type)}
						onchange={() => toggle('types', type)}
					/>{name}</label
				>
			{/each}
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
			<span class="name">Owned by</span>
			<div class="chips">
				{#each organize.libraries as owner (owner.id)}
					<label class="check"
						><input
							type="checkbox"
							checked={(rules.owners ?? []).includes(owner.id)}
							onchange={() => toggle('owners', owner.id)}
						/>{libraryName(owner.id)}</label
					>
				{/each}
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
	.row {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 6px;
	}
	.name {
		font-weight: 600;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px 10px;
	}
	.author-search {
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
	.check {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-weight: 400;
	}
	.check input {
		width: auto;
		margin: 0;
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
