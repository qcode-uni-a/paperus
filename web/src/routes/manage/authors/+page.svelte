<script lang="ts">
	import { resolve } from '$app/paths';
	import {
		assignAuthor,
		authorSuggestions,
		authorsToCheck,
		errorMessage,
		keepApart,
		listAuthors
	} from '#lib/api/client.ts';
	import AuthorCompare from '#lib/AuthorCompare.svelte';
	import type { AuthorRow, AuthorToCheck, LikelyOut } from '#lib/api/generated/types.gen.ts';
	import { fullName } from '#lib/format.ts';
	import { plainTitle } from '#lib/title.svelte.ts';
	import { notify } from '#lib/toasts.svelte.ts';

	/** The authors of one's papers, as people; and the authors to check: a
	 * name several people share, with nothing on the paper to tell which. */

	const PAGE = 100;
	let search = $state('');
	let sort = $state<'papers' | 'name'>('papers');
	let rows = $state<AuthorRow[] | null>(null);
	let total = $state(0);
	let toCheck = $state<AuthorToCheck[]>([]);

	async function load(more = false) {
		const words = search.trim();
		const { data, response } = await listAuthors({
			query: { q: words || undefined, sort, limit: PAGE, offset: more ? (rows?.length ?? 0) : 0 }
		});
		if (words !== search.trim()) return;
		rows = more ? [...(rows ?? []), ...(data ?? [])] : (data ?? []);
		total = Number(response?.headers.get('X-Total-Count') ?? rows.length);
	}

	$effect(() => {
		void sort;
		void search;
		const timer = setTimeout(() => load(), 200);
		return () => clearTimeout(timer);
	});

	async function loadToCheck() {
		toCheck = (await authorsToCheck({ query: { limit: 50 } })).data ?? [];
	}
	$effect(() => {
		loadToCheck();
	});

	// Probably the same person: merged, or kept apart.
	let likely = $state<LikelyOut[]>([]);
	async function loadLikely() {
		likely = (await authorSuggestions({ query: { limit: 50 } })).data ?? [];
	}
	$effect(() => {
		loadLikely();
	});

	/** Compared side by side: these pairs, one after another. */
	let comparing = $state<LikelyOut[] | null>(null);

	async function different(pair: LikelyOut) {
		await keepApart({ path: { author_id: pair.one.id }, body: { other_id: pair.other.id } });
		likely = likely.filter((p) => p !== pair);
	}

	async function decide(entry: AuthorToCheck, person: AuthorRow | null) {
		const { error } = await assignAuthor({
			path: { item_id: entry.item.id, position: entry.position },
			body: { author_id: person?.id ?? null }
		});
		if (error) {
			notify({ kind: 'warning', title: 'Not saved', text: errorMessage(error) });
			return;
		}
		toCheck = toCheck.filter((e) => e !== entry);
		load();
	}
</script>

<svelte:head><title>Authors · paperus</title></svelte:head>

<header class="head">
	<h1>Authors</h1>
	<p class="muted">
		The people who wrote the papers in your library. The same full name is one person; a person with
		several names (initials, a typo) is merged on their page, and papers by someone else of the same
		name are split off there.
	</p>
</header>

{#if toCheck.length}
	<section class="check">
		<h2>To check <span class="count">{toCheck.length}</span></h2>
		<p class="muted">
			Several people have these names, and nothing on the paper tells which one wrote it.
		</p>
		<ul>
			{#each toCheck as entry (`${entry.item.id}-${entry.position}`)}
				<li>
					<p>
						<strong>{fullName(entry.written)}</strong> on
						<a href={resolve('/items/[id]', { id: entry.item.id })}
							>{plainTitle(entry.item.title)}</a
						>
					</p>
					<div class="row">
						{#each entry.candidates as person (person.id)}
							<button onclick={() => decide(entry, person)}
								>{person.name}: {person.papers}
								{person.papers === 1 ? 'paper' : 'papers'}</button
							>
							<a class="small" href={resolve('/authors/[id]', { id: person.id })}>see</a>
						{/each}
						<button class="quiet" onclick={() => decide(entry, null)}>Someone else</button>
					</div>
				</li>
			{/each}
		</ul>
	</section>
{/if}

{#if likely.length}
	<section class="check likely">
		<div class="likely-head">
			<h2>Probably the same <span class="count">{likely.length}</span></h2>
			<button class="primary" onclick={() => (comparing = likely)}>Review one by one</button>
		</div>
		<p class="muted">
			The same family name, given names that fit; with co-authors in common first.
		</p>
		<ul>
			{#each likely as pair (`${pair.one.id}-${pair.other.id}`)}
				<li>
					<p>
						<a href={resolve('/authors/[id]', { id: pair.one.id })}>{pair.one.name}</a>
						<span class="muted">({pair.one.papers})</span> and
						<a href={resolve('/authors/[id]', { id: pair.other.id })}>{pair.other.name}</a>
						<span class="muted">({pair.other.papers})</span>{#if pair.shared}<span class="muted"
								>{' '}· {pair.shared}
								{pair.shared === 1 ? 'co-author' : 'co-authors'} in common</span
							>{/if}
					</p>
					<div class="row">
						<button onclick={() => (comparing = [pair])}>Compare…</button>
						<button class="quiet" onclick={() => different(pair)}>Different people</button>
					</div>
				</li>
			{/each}
		</ul>
	</section>
{/if}

{#if comparing}
	<AuthorCompare
		pairs={comparing}
		onclose={(changed) => {
			comparing = null;
			if (changed) {
				loadLikely();
				load();
			}
		}}
	/>
{/if}

<div class="tools">
	<input
		type="search"
		bind:value={search}
		placeholder="Find an author"
		aria-label="Find an author"
	/>
	<select bind:value={sort} aria-label="Order">
		<option value="papers">Most papers first</option>
		<option value="name">By name</option>
	</select>
</div>

{#if rows === null}
	<p class="muted">Loading…</p>
{:else if rows.length === 0}
	<p class="muted">
		{search.trim()
			? 'No author of that name.'
			: 'No authors yet. They appear a few minutes after papers are added.'}
	</p>
{:else}
	<p class="muted">{total.toLocaleString()} {total === 1 ? 'author' : 'authors'}</p>
	<ul class="authors">
		{#each rows as person (person.id)}
			<li>
				<a href={resolve('/authors/[id]', { id: person.id })}>{person.name}</a>
				<span class="muted"
					>{person.papers}
					{person.papers === 1 ? 'paper' : 'papers'}{#if person.orcid}{' '}· ORCID{/if}</span
				>
			</li>
		{/each}
	</ul>
	{#if rows.length < total}
		<div class="more"><button onclick={() => load(true)}>Show more</button></div>
	{/if}
{/if}

<style>
	.head {
		margin-bottom: 16px;
	}
	h1 {
		margin: 0 0 4px;
	}
	.head p {
		margin: 0;
		max-width: 70ch;
	}
	.check {
		margin: 0 0 24px;
		padding: 14px 16px;
		border: 1px solid var(--rule);
		border-left: 4px solid var(--highlighter);
		border-radius: 10px;
	}
	.likely {
		border-left-color: var(--royal);
	}
	.likely-head {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
	}
	.check h2 {
		margin: 0 0 4px;
		font-size: var(--step-1);
	}
	.count {
		font-family: var(--sans);
		font-size: var(--step--1);
		color: var(--muted);
	}
	.check ul {
		display: grid;
		gap: 12px;
		margin: 12px 0 0;
		padding: 0;
		list-style: none;
	}
	.check li p {
		margin: 0 0 6px;
	}
	.check .row {
		gap: 6px 10px;
	}
	.small {
		font-size: var(--step--1);
	}
	.quiet {
		border-color: transparent;
		background: none;
		color: var(--muted);
	}
	.tools {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-bottom: 12px;
	}
	.tools input {
		flex: 1 1 16rem;
		max-width: 28rem;
	}
	.tools select {
		width: auto;
	}
	.authors {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
		gap: 6px 24px;
		margin: 8px 0 0;
		padding: 0;
		list-style: none;
	}
	.authors li {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 2px 8px;
		padding: 6px 0;
		border-bottom: 1px solid var(--rule);
	}
	.authors a {
		color: var(--ink);
		text-decoration: none;
		font-weight: 600;
	}
	.authors a:hover {
		color: var(--royal);
		text-decoration: underline;
	}
	.more {
		display: flex;
		justify-content: center;
		padding: 12px 0 24px;
	}
</style>
