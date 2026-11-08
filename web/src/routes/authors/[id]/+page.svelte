<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import {
		errorMessage,
		getAuthor,
		listAuthors,
		listItems,
		splitAuthor,
		undoAuthorChange,
		type Item
	} from '#lib/api/client.ts';
	import type { AuthorChangeOut, AuthorOut, AuthorRow } from '#lib/api/generated/types.gen.ts';
	import AuthorCompare from '#lib/AuthorCompare.svelte';
	import CollectionDialog from '#lib/CollectionDialog.svelte';
	import { ago } from '#lib/format.ts';
	import { personName } from '#lib/names.svelte.ts';
	import ItemRow from '#lib/ItemRow.svelte';
	import { writableLibraries } from '#lib/organize.svelte.ts';
	import { notify } from '#lib/toasts.svelte.ts';

	/** An author as a person: their papers here, who they wrote with, where
	 * they were; and the fixes when two people share a name (split) or one
	 * person has two records (merge). */

	const id = $derived(page.params.id ?? '');
	const PAGE = 50;

	let author = $state<AuthorOut | null>(null);
	let collectionDialog = $state<CollectionDialog>();
	let missing = $state(false);
	let items = $state<Item[]>([]);
	let total = $state(0);

	async function load(shown: string) {
		const [person, papers] = await Promise.all([
			getAuthor({ path: { author_id: shown } }),
			listItems({ query: { author_id: [shown], limit: PAGE } })
		]);
		if (shown !== id) return;
		missing = !person.data;
		author = person.data ?? null;
		items = papers.data ?? [];
		total = Number(papers.response?.headers.get('X-Total-Count') ?? items.length);
	}

	async function more() {
		const { data } = await listItems({
			query: { author_id: [id], limit: PAGE, before: items.at(-1)?.id }
		});
		items = [...items, ...(data ?? [])];
	}

	$effect(() => {
		const shown = id;
		splitting = false;
		chosen = [];
		load(shown);
	});

	// Split: some papers are by someone else of the same name.
	let splitting = $state(false);
	let chosen = $state<string[]>([]);
	let working = $state(false);

	async function split() {
		working = true;
		const { data, error } = await splitAuthor({
			path: { author_id: id },
			body: { item_ids: chosen }
		});
		working = false;
		if (!data) {
			notify({ kind: 'warning', title: 'Not split', text: errorMessage(error) });
			return;
		}
		notify({
			kind: 'success',
			title: `${chosen.length} ${chosen.length === 1 ? 'paper' : 'papers'} moved to another ${personName(data)}`,
			text: 'The two are kept apart from now on.',
			link: { href: resolve('/authors/[id]', { id: data.id }), label: 'Open' }
		});
		splitting = false;
		chosen = [];
		load(id);
	}

	// Merge: the same person as another record.
	let merging = $state(false);
	let search = $state('');
	let found = $state<AuthorRow[]>([]);
	$effect(() => {
		const words = search.trim();
		if (!merging || words.length < 2) {
			found = [];
			return;
		}
		const timer = setTimeout(async () => {
			const { data } = await listAuthors({ query: { q: words, limit: 8 } });
			if (words === search.trim()) found = (data ?? []).filter((a) => a.id !== id);
		}, 250);
		return () => clearTimeout(timer);
	});

	/** Compared side by side with another record, to merge or keep apart. */
	let comparing = $state<AuthorRow | null>(null);
	function merge(other: AuthorRow) {
		comparing = other;
	}
	let keptAs = $state<string | null>(null);

	// Fixes by hand: who is who is shared by everyone, so each is kept and
	// can be taken back.
	const DONE: Record<AuthorChangeOut['kind'], string> = {
		split: 'Papers moved to another',
		merge: 'Merged with',
		apart: 'Said to be different from'
	};

	async function undo(change: AuthorChangeOut) {
		const { data, error } = await undoAuthorChange({ path: { change_id: change.id } });
		if (!data) {
			notify({ kind: 'warning', title: 'Not undone', text: errorMessage(error) });
			return;
		}
		notify({ kind: 'success', title: 'Undone' });
		load(id);
	}

	const mayChoose = (item: Item) => writableLibraries().some((l) => l.id === item.library_id);

	const years = (first: number | null, last: number | null) =>
		!first ? '' : first === last ? String(first) : `${first}–${last}`;
</script>

<svelte:head><title>{author ? personName(author) : 'Author'} · paperus</title></svelte:head>

{#if comparing && author}
	<AuthorCompare
		pairs={[{ one: author, other: comparing }]}
		prefer={id}
		onmerged={(kept) => (keptAs = kept.id)}
		onclose={async (changed) => {
			comparing = null;
			if (!changed) return;
			merging = false;
			search = '';
			if (keptAs && keptAs !== id) await goto(resolve('/authors/[id]', { id: keptAs }));
			else load(id);
			keptAs = null;
		}}
	/>
{/if}

{#if missing}
	<h1>Author not found</h1>
	<p class="muted">
		No paper of theirs is in your library (any more). <a href={resolve('/manage/authors')}
			>All authors</a
		>
	</p>
{:else if author}
	<header class="head">
		<p class="kicker"><a href={resolve('/manage/authors')}>Authors</a></p>
		<h1>{personName(author)}</h1>
		<p class="meta">
			{author.papers}
			{author.papers === 1 ? 'paper' : 'papers'} in your library{#if author.orcid}
				· <a href="https://orcid.org/{author.orcid}" target="_blank" rel="noopener"
					>ORCID {author.orcid}</a
				>{/if}{#if author.openalex_id}
				· <a href="https://openalex.org/{author.openalex_id}" target="_blank" rel="noopener"
					>OpenAlex</a
				>{/if}
		</p>
		{#if author.spellings.length > 1}
			<p class="muted">Written as {author.spellings.join('; ')}</p>
		{/if}
	</header>

	{#if author.affiliations.length}
		<section>
			<h2>Where they were</h2>
			<ul class="places">
				{#each author.affiliations as place, i (place.name)}
					<li>
						<span>{place.name}</span>
						<span class="muted"
							>{years(place.first_year, place.last_year)}{#if i === 0}{' '}· latest known{/if}</span
						>
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	{#if author.coauthors.length}
		<section>
			<h2>Wrote with</h2>
			<p class="chips">
				{#each author.coauthors as other (other.id)}
					<a class="chip" href={resolve('/authors/[id]', { id: other.id })}
						>{personName(other)} <span class="muted">{other.papers}</span></a
					>
				{/each}
			</p>
		</section>
	{/if}

	{#if author.namesakes.length}
		<section class="namesakes">
			<h2>Others named {personName(author)}</h2>
			<ul>
				{#each author.namesakes as other (other.id)}
					<li>
						<a href={resolve('/authors/[id]', { id: other.id })}>{personName(other)}</a>
						<span class="muted">{other.papers} {other.papers === 1 ? 'paper' : 'papers'}</span>
						{#if author.may_change}
							<button class="link" onclick={() => merge(other)}>The same person</button>
						{/if}
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	<section>
		<div class="papers-head">
			<h2>Papers</h2>
			<div class="row">
				{#if author.may_change && !splitting && author.papers > 1}
					<button onclick={() => (splitting = true)}>Some are by someone else</button>
				{/if}
				{#if author.may_change && !merging}
					<button onclick={() => (merging = true)}>Same person as…</button>
				{/if}
				<button
					title="A collection that always holds their papers, also those added later"
					onclick={() =>
						author &&
						collectionDialog?.open(undefined, true, { authors: [author.id] }, personName(author))}
					>Smart collection</button
				>
			</div>
		</div>
		{#if merging}
			<div class="tool">
				<label for="merge-search">The same person as</label>
				<!-- svelte-ignore a11y_autofocus -->
				<input
					id="merge-search"
					bind:value={search}
					placeholder="Another author’s name"
					autocomplete="off"
					autofocus
				/>
				{#if found.length}
					<ul class="found">
						{#each found as other (other.id)}
							<li>
								<button class="link" onclick={() => merge(other)}
									>{personName(other)}{#if other.orcid}{' '}(ORCID){/if}</button
								>
								<span class="muted">{other.papers} {other.papers === 1 ? 'paper' : 'papers'}</span>
							</li>
						{/each}
					</ul>
				{:else if search.trim().length >= 2}
					<p class="muted">No other author of that name.</p>
				{/if}
				<button class="quiet" onclick={() => ((merging = false), (search = ''))}>Cancel</button>
			</div>
		{/if}
		{#if splitting}
			<div class="tool">
				<p>
					Choose the papers by another {personName(author)}; they go to a new person, and the two
					are kept apart from then on.
				</p>
				<div class="row">
					<button class="primary" disabled={!chosen.length || working} onclick={split}
						>Move {chosen.length}
						{chosen.length === 1 ? 'paper' : 'papers'} to another {personName(author)}</button
					>
					<button class="quiet" onclick={() => ((splitting = false), (chosen = []))}>Cancel</button>
				</div>
			</div>
		{/if}
		<ul class="items">
			{#each items as item (item.id)}
				<ItemRow {item}>
					{#snippet actions()}
						{#if splitting && mayChoose(item)}
							<label class="choose"
								><input type="checkbox" bind:group={chosen} value={item.id} /> By someone else</label
							>
						{/if}
					{/snippet}
				</ItemRow>
			{/each}
		</ul>
		{#if items.length < total}
			<div class="more"><button onclick={more}>Show more</button></div>
		{/if}
	</section>

	{#if author.changes.length}
		<section class="changes">
			<h2>Changed by hand</h2>
			<ul>
				{#each author.changes as change (change.id)}
					<li class:undone={change.undone}>
						<span
							>{DONE[change.kind]}
							{#if change.other_id}<a href={resolve('/authors/[id]', { id: change.other_id })}
									>{change.other_name}</a
								>{:else}{change.other_name ??
									'another person'}{/if}{#if change.papers}{' '}({change.papers}
								{change.papers === 1 ? 'paper' : 'papers'}){/if}{#if change.renamed_from}, before
								named {change.renamed_from}{/if}</span
						>
						<span class="muted"
							>{change.by_you ? 'by you' : 'by someone else'}, {ago(
								change.at
							)}{#if change.undone}{' '}· undone{/if}</span
						>
						{#if change.may_undo}
							<button class="link" onclick={() => undo(change)}>Undo</button>
						{/if}
					</li>
				{/each}
			</ul>
		</section>
	{/if}
{:else}
	<p class="muted">Loading…</p>
{/if}

<CollectionDialog bind:this={collectionDialog} />

<style>
	.head {
		display: grid;
		gap: 4px;
		margin-bottom: 8px;
	}
	.kicker {
		margin: 0;
		font-size: var(--step--1);
	}
	h1 {
		margin: 0;
	}
	.meta {
		margin: 0;
		color: var(--muted);
	}
	section {
		margin-top: 24px;
	}
	h2 {
		margin: 0 0 8px;
		font-size: var(--step-1);
	}
	.places,
	.namesakes ul,
	.changes ul,
	.found {
		display: grid;
		gap: 6px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.places li {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 12px;
	}
	.namesakes li,
	.changes li,
	.found li {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 4px 12px;
	}
	.changes .undone > span:first-child {
		text-decoration: line-through;
		color: var(--muted);
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 0;
	}
	.chip {
		padding: 2px 10px;
		border-radius: 14px;
		background: var(--rail);
		color: var(--ink);
		text-decoration: none;
	}
	.chip:hover {
		color: var(--royal);
	}
	.papers-head {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
	}
	.papers-head h2 {
		margin: 0;
	}
	.tool {
		display: grid;
		gap: 8px;
		margin: 12px 0;
		padding: 12px 14px;
		border: 1px solid var(--rule);
		border-radius: 10px;
		max-width: 640px;
	}
	.tool p {
		margin: 0;
	}
	.tool .quiet {
		justify-self: start;
	}
	.link {
		padding: 0;
		border: none;
		background: none;
		color: var(--royal);
	}
	.link:hover {
		text-decoration: underline;
	}
	.quiet {
		border-color: transparent;
		background: none;
		color: var(--muted);
	}
	.items {
		margin: 8px 0 0;
		padding: 0;
	}
	.choose {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-weight: 600;
	}
	.more {
		display: flex;
		justify-content: center;
		padding: 12px 0 24px;
	}
</style>
