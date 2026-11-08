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

	/** Co-authors both have. */
	const shared = $derived.by(() => {
		if (!left || !right) return new Set<string>();
		const theirs = new Set(right.author.coauthors.map((c) => c.id));
		return new Set(left.author.coauthors.filter((c) => theirs.has(c.id)).map((c) => c.id));
	});

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

	/** The names to choose from: both, the fuller one first (more letters,
	 * accents included), and one typed in. */
	const names = $derived.by(() => {
		if (!pair) return [];
		const both = [pair.one.name, pair.other.name].filter((n, i, all) => all.indexOf(n) === i);
		return both.sort((a, b) => b.normalize('NFD').length - a.normalize('NFD').length);
	});
	let name = $state('');
	let typed = $state('');
	$effect(() => {
		void pair?.one.id;
		void pair?.other.id;
		name = untrack(() => names[0] ?? '');
		typed = '';
	});
	const OTHER = '\u0000other';
	const chosenName = $derived(name === OTHER ? typed.trim() : name);

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
		if (!kept || !merged || busy || twoOrcids || !chosenName) return;
		busy = true;
		const { data, error } = await mergeAuthors({
			path: { author_id: kept.id },
			body: { other_id: merged.id, name: chosenName }
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
		if (busy || (event.target instanceof HTMLInputElement && event.target.type === 'text')) return;
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

{#snippet person(row: AuthorRow, found: { author: AuthorOut; papers: Item[] } | null)}
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
				<p>
					<span class="label">Where</span>
					{#each author.affiliations.slice(0, 2) as place, i (place.name)}{i
							? '; '
							: ''}{place.name}
						<span class="muted">{years(place.first_year, place.last_year)}</span>{/each}
				</p>
			{/if}
			{#if author.coauthors.length}
				<p class="chips">
					<span class="label">Wrote with</span>
					{#each author.coauthors.slice(0, 8) as other (other.id)}
						<span
							class="chip"
							class:shared={shared.has(other.id)}
							title={shared.has(other.id) ? 'Both wrote with them' : undefined}>{other.name}</span
						>
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
				{#if shared.size}
					<p class="muted">
						{shared.size}
						{shared.size === 1 ? 'co-author' : 'co-authors'} in common (marked).
					</p>
				{/if}
			</div>
			<button class="icon" aria-label="Close" onclick={() => dialog?.close()}
				><Icon path={mdiClose} /></button
			>
		</header>

		<div class="sides">
			{@render person(pair.one, left)}
			{@render person(pair.other, right)}
		</div>

		{#if twoOrcids}
			<p class="warn">They have different ORCID iDs, so they are two people.</p>
		{:else}
			<fieldset class="name">
				<legend>If they are the same person, show them as</legend>
				{#each names as option (option)}
					<label><input type="radio" bind:group={name} value={option} /> {option}</label>
				{/each}
				<label class="typed">
					<input type="radio" bind:group={name} value={OTHER} />
					<input
						type="text"
						bind:value={typed}
						placeholder="Another spelling"
						aria-label="Another spelling"
						maxlength="200"
						onfocus={() => (name = OTHER)}
					/>
				</label>
			</fieldset>
		{/if}

		<footer>
			<div class="keys muted">
				<kbd>S</kbd> same <kbd>D</kbd> different{#if queue.length > 1}{' '}<kbd>→</kbd> skip{/if}
			</div>
			<div class="buttons">
				<button onclick={different} disabled={busy}>Different people</button>
				{#if queue.length > 1}<button onclick={next} disabled={busy}>Skip</button>{/if}
				<button class="primary" onclick={same} disabled={busy || twoOrcids || !chosenName}>
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
		border-radius: 999px;
		line-height: 1.6;
	}
	.chip.shared {
		border-color: var(--royal);
		color: var(--royal);
		font-weight: 600;
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
	.name {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px 18px;
		margin: 16px 0 0;
		padding: 0;
		border: none;
	}
	.name legend {
		margin-bottom: 6px;
		padding: 0;
		font-weight: 650;
	}
	.name label {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.name input[type='radio'] {
		width: auto;
		margin: 0;
	}
	.typed input[type='text'] {
		width: 14rem;
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
