<script lang="ts">
	import Title from '#lib/Title.svelte';
	import { mdiClose } from '@mdi/js';
	import { resolve } from '$app/paths';
	import { untrack } from 'svelte';
	import {
		errorMessage,
		getAuthor,
		keepApart,
		listItems,
		mergeAuthors,
		type Item
	} from '#lib/api/client.ts';
	import type { AuthorOut, AuthorRow } from '#lib/api/generated/types.gen.ts';
	import Icon from '#lib/Icon.svelte';
	import { notify } from '#lib/toasts.svelte.ts';

	/** Two author records side by side (their papers, co-authors, places),
	 * one pair after another: the same person (shown under the name chosen)
	 * or different people. ``prefer``: the record to keep when either could
	 * (the author page one is on). */
	type Pair = { one: AuthorRow; other: AuthorRow };
	let {
		pairs,
		prefer,
		onclose,
		onmerged
	}: {
		pairs: Pair[];
		prefer?: string;
		onclose: (changed: boolean) => void;
		onmerged?: (kept: AuthorRow) => void;
	} = $props();

	const PAPERS = 4;

	let dialog = $state<HTMLDialogElement>();
	// A copy taken once: the pairs left to review shrink as they are done.
	let queue = $state<Pair[]>(untrack(() => [...pairs]));
	let index = $state(0);
	let people = $state<Record<string, { author: AuthorOut; papers: Item[] } | null>>({});
	let busy = $state(false);
	let changed = false;

	$effect(() => {
		dialog?.showModal();
	});

	const pair = $derived(queue[index]);

	/** Both people's details, each once. */
	$effect(() => {
		if (!pair) return;
		for (const person of [pair.one, pair.other]) {
			if (person.id in untrack(() => people)) continue;
			people[person.id] = null;
			Promise.all([
				getAuthor({ path: { author_id: person.id } }),
				listItems({ query: { author_id: [person.id], limit: PAPERS } })
			]).then(([author, papers]) => {
				if (author.data) people[person.id] = { author: author.data, papers: papers.data ?? [] };
			});
		}
	});

	const left = $derived(pair ? people[pair.one.id] : null);
	const right = $derived(pair ? people[pair.other.id] : null);

	/** Two ORCID iDs are two people (the server refuses to merge them). */
	const twoOrcids = $derived(
		Boolean(pair?.one.orcid && pair.other.orcid && pair.one.orcid !== pair.other.orcid)
	);

	/** What both have: the same (green), or probably the same written
	 * differently (dashed). */
	type Match = 'same' | 'similar' | null;
	const fold = (text: string) =>
		text
			.normalize('NFD')
			.replace(/\p{M}/gu, '')
			.toLowerCase()
			.replace(/[^\p{L}\p{N}]+/gu, ' ')
			.trim();
	/** "W. Huang" and "Wister Huang": the same family name and initial. */
	function alike(a: string, b: string): boolean {
		const [x, y] = [fold(a).split(' '), fold(b).split(' ')];
		return x.length > 1 && y.length > 1 && x.at(-1) === y.at(-1) && x[0][0] === y[0][0];
	}
	function coauthor(person: AuthorRow, other: AuthorOut | undefined): Match {
		if (!other) return null;
		if (other.coauthors.some((c) => c.id === person.id)) return 'same';
		return other.coauthors.some((c) => alike(c.name, person.name)) ? 'similar' : null;
	}
	/** "UNSW Sydney" in both; one place's name in the other's ("Delft
	 * University of Technology" and "QuTech, Delft University of
	 * Technology") is probably the same. */
	/** A paper's affiliation may name several places: "UNSW Sydney;
	 * Quantum Motion Technologies". */
	const places = (author: AuthorOut) =>
		author.affiliations.flatMap((a) => a.name.split(/\s*;\s*/).filter(Boolean));
	function place(name: string, other: AuthorOut | undefined): Match {
		if (!other) return null;
		const mine = fold(name);
		const theirs = places(other).map(fold);
		if (theirs.includes(mine)) return 'same';
		return theirs.some((t) => t.includes(mine) || mine.includes(t)) ? 'similar' : null;
	}
	const PLACES = 3;
	const COAUTHORS = 8;
	/** Co-authors, those in common first (the same, then probably). */
	function coauthors(author: AuthorOut, other: AuthorOut | undefined) {
		const rank = { same: 0, similar: 1 } as const;
		return author.coauthors
			.map((person) => ({ person, match: coauthor(person, other) }))
			.sort((a, b) => (a.match ? rank[a.match] : 2) - (b.match ? rank[b.match] : 2));
	}
	/** In common, for the summary above both. */
	const common = $derived.by(() => {
		if (!left || !right) return null;
		const where = [...new Set(places(left.author))].map((p) => place(p, right.author));
		const people = left.author.coauthors.map((c) => coauthor(c, right.author));
		const count = (found: Match[], match: Match) => found.filter((m) => m === match).length;
		return {
			places: count(where, 'same') + count(where, 'similar'),
			same: count(people, 'same'),
			similar: count(people, 'similar')
		};
	});
	const MATCH: Record<string, string> = {
		same: 'Both have this',
		similar: 'Probably both: written differently'
	};

	/** The record that stays (its page, its ids): the one with an ORCID
	 * iD, else an OpenAlex id, else more papers, else the one preferred. */
	const kept = $derived.by(() => {
		if (!pair) return null;
		const score = (p: AuthorRow) => [
			p.orcid ? 1 : 0,
			people[p.id]?.author.openalex_id ? 1 : 0,
			p.papers,
			p.id === prefer ? 1 : 0
		];
		const [a, b] = [score(pair.one), score(pair.other)];
		for (let i = 0; i < a.length; i++)
			if (a[i] !== b[i]) return a[i] > b[i] ? pair.one : pair.other;
		return pair.one;
	});
	const merged = $derived(pair && kept ? (kept.id === pair.one.id ? pair.other : pair.one) : null);

	function next() {
		if (index < queue.length - 1) index += 1;
		else dialog?.close();
	}

	/** This pair is decided (and any others that ``gone`` settles). */
	function done(gone: (p: Pair) => boolean = () => false) {
		const current = queue[index];
		queue = queue.filter((p) => p !== current && !gone(p));
		changed = true;
		if (index >= queue.length) index = Math.max(0, queue.length - 1);
		if (queue.length === 0) dialog?.close();
	}

	async function same() {
		if (!kept || !merged || busy || twoOrcids) return;
		busy = true;
		const { data, error } = await mergeAuthors({
			path: { author_id: kept.id },
			body: { other_id: merged.id }
		});
		busy = false;
		if (!data) {
			notify({ kind: 'warning', title: 'Not merged', text: errorMessage(error) });
			return;
		}
		notify({ kind: 'success', title: `One person now: ${data.name}` });
		// The merged record is gone: later pairs with it name the kept one
		// (and a pair of the two is settled).
		const gone = merged.id;
		const current = queue[index];
		queue = queue.map((p) =>
			p === current
				? p
				: {
						one: p.one.id === gone ? data : p.one,
						other: p.other.id === gone ? data : p.other
					}
		);
		delete people[kept.id];
		onmerged?.(data);
		done((p) => p.one.id === p.other.id);
	}

	async function different() {
		if (!pair || busy) return;
		busy = true;
		const { error } = await keepApart({
			path: { author_id: pair.one.id },
			body: { other_id: pair.other.id }
		});
		busy = false;
		if (error) {
			notify({ kind: 'warning', title: 'Not saved', text: errorMessage(error) });
			return;
		}
		done();
	}

	function key(event: KeyboardEvent) {
		if (busy) return;
		const actions: Record<string, () => void> = {
			s: () => same(),
			d: () => different(),
			ArrowRight: () => next(),
			ArrowLeft: () => (index = Math.max(0, index - 1))
		};
		const action = actions[event.key];
		if (action) {
			event.preventDefault();
			action();
		}
	}

	const years = (first: number | null, last: number | null) =>
		!first ? '' : first === last ? String(first) : `${first}–${last}`;
</script>

{#snippet chip(text: string, match: Match)}
	<span class="chip {match ?? ''}" title={match ? MATCH[match] : undefined}
		>{text}{#if match}<span class="visually-hidden"> ({MATCH[match]})</span>{/if}</span
	>
{/snippet}

{#snippet person(
	row: AuthorRow,
	found: { author: AuthorOut; papers: Item[] } | null,
	other: AuthorOut | undefined
)}
	<article class="person">
		<h3>
			<a href={resolve('/authors/[id]', { id: row.id })} target="_blank" rel="noopener"
				>{row.name}</a
			>
		</h3>
		<p class="ids muted">
			{row.papers}
			{row.papers === 1 ? 'paper' : 'papers'}{#if row.orcid}{' '}· ORCID {row.orcid}{/if}{#if found?.author.openalex_id}{' '}·
				OpenAlex{/if}
		</p>
		{#if !found}
			<p class="muted">Loading…</p>
		{:else}
			{@const author = found.author}
			{#if author.spellings.length}
				<p><span class="label">Written as</span> {author.spellings.join('; ')}</p>
			{/if}
			{#if author.affiliations.length}
				<p class="chips">
					<span class="label">Where</span>
					{#each author.affiliations.slice(0, PLACES) as where (where.name)}
						<span class="place"
							>{#each where.name.split(/\s*;\s*/).filter(Boolean) as part (part)}{@render chip(
									part,
									place(part, other)
								)}{/each}{#if where.first_year}<span class="muted"
									>{years(where.first_year, where.last_year)}</span
								>{/if}</span
						>
					{/each}
				</p>
			{/if}
			{#if author.coauthors.length}
				<p class="chips">
					<span class="label">Wrote with</span>
					{#each coauthors(author, other).slice(0, COAUTHORS) as { person, match } (person.id)}
						{@render chip(person.name, match)}
					{/each}
				</p>
			{/if}
			<ul class="papers">
				{#each found.papers as item (item.id)}
					<li>
						<a href={resolve('/items/[id]', { id: item.id })} target="_blank" rel="noopener"
							><Title text={item.title} /></a
						>{#if item.year}{' '}<span class="muted">({item.year})</span>{/if}
					</li>
				{/each}
				{#if row.papers > found.papers.length}
					<li class="muted">and {row.papers - found.papers.length} more</li>
				{/if}
			</ul>
		{/if}
	</article>
{/snippet}

<dialog
	bind:this={dialog}
	aria-labelledby="compare-title"
	onclose={() => onclose(changed)}
	onkeydown={key}
>
	{#if pair}
		<header>
			<div>
				<h2 id="compare-title">
					The same person?{#if queue.length > 1}<span class="count">
							{index + 1} of {queue.length}</span
						>{/if}
				</h2>
				{#if common && (common.places || common.same || common.similar)}
					<p class="muted">
						In common (green):
						{[
							common.places && `${common.places} ${common.places === 1 ? 'place' : 'places'}`,
							common.same && `${common.same} ${common.same === 1 ? 'co-author' : 'co-authors'}`,
							common.similar &&
								`${common.similar} ${common.similar === 1 ? 'co-author' : 'co-authors'} written differently (dashed)`
						]
							.filter(Boolean)
							.join(', ')}.
					</p>
				{:else if common}
					<p class="muted">No co-authors or places in common.</p>
				{/if}
			</div>
			<button class="icon" aria-label="Close" onclick={() => dialog?.close()}
				><Icon path={mdiClose} /></button
			>
		</header>

		<div class="sides">
			{@render person(pair.one, left, right?.author)}
			{@render person(pair.other, right, left?.author)}
		</div>

		{#if twoOrcids}
			<p class="warn">They have different ORCID iDs, so they are two people.</p>
		{/if}

		<footer>
			<div class="keys muted">
				<kbd>S</kbd> same <kbd>D</kbd> different{#if queue.length > 1}{' '}<kbd>→</kbd> skip{/if}
			</div>
			<div class="buttons">
				<button onclick={different} disabled={busy}>Different people</button>
				{#if queue.length > 1}<button onclick={next} disabled={busy}>Skip</button>{/if}
				<button class="primary" onclick={same} disabled={busy || twoOrcids}>
					{busy ? 'Merging…' : 'The same person'}
				</button>
			</div>
		</footer>
	{/if}
</dialog>

<style>
	dialog {
		width: min(960px, calc(100vw - 32px));
		max-height: calc(100vh - 32px);
		padding: 20px 24px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	dialog::backdrop {
		background: rgb(10 14 30 / 0.5);
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 12px;
		margin-bottom: 14px;
	}
	h2 {
		margin: 0 0 4px;
		font-size: var(--step-2);
	}
	header p {
		margin: 0;
	}
	.count {
		margin-left: 10px;
		font-family: var(--sans);
		font-size: var(--step--1);
		font-weight: 500;
		color: var(--muted);
	}
	.icon {
		display: grid;
		place-items: center;
		width: 36px;
		height: 36px;
		padding: 0;
		border: none;
		border-radius: 50%;
		background: none;
	}
	.sides {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
		align-items: start;
	}
	.person {
		padding: 14px 16px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--rail);
		overflow-wrap: anywhere;
	}
	.person h3 {
		margin: 0;
		font-size: var(--step-1);
	}
	.person h3 a {
		color: var(--ink);
	}
	.person p {
		margin: 6px 0 0;
		font-size: var(--step--1);
	}
	.person .ids {
		margin-top: 2px;
	}
	.label {
		margin-right: 4px;
		font-weight: 650;
		color: var(--muted);
	}
	.chips {
		line-height: 1.9;
	}
	.chip {
		display: inline-block;
		margin: 0 2px;
		padding: 0 8px;
		border: 1.5px solid var(--rule);
		border-radius: 12px;
		line-height: 1.6;
	}
	.place {
		margin-right: 6px;
	}
	.chip.same,
	.chip.similar {
		border-color: var(--success);
		background: color-mix(in srgb, var(--success) 12%, transparent);
	}
	.chip.similar {
		border-style: dashed;
		background: none;
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}
	.papers {
		display: grid;
		gap: 4px;
		margin: 10px 0 0;
		padding: 10px 0 0;
		border-top: 1px solid var(--rule);
		list-style: none;
		font-size: var(--step--1);
	}
	.papers a {
		font-family: var(--serif);
		color: var(--ink);
	}
	.warn {
		margin: 16px 0 0;
		color: var(--danger);
	}
	footer {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: center;
		gap: 10px;
		margin-top: 16px;
		padding-top: 12px;
		border-top: 1px solid var(--rule);
	}
	.keys {
		font-size: var(--step--1);
	}
	kbd {
		padding: 1px 6px;
		border: 1px solid var(--rule);
		border-radius: 4px;
		background: var(--rail);
		font-size: 0.85em;
	}
	.buttons {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	@media (max-width: 720px) {
		.sides {
			grid-template-columns: minmax(0, 1fr);
		}
		.keys {
			display: none;
		}
	}
</style>
