<script lang="ts">
	import { resolve } from '$app/paths';
	import {
		addItem,
		errorMessage,
		findReference,
		importReferences,
		listCiting,
		listReferences,
		refreshReferences,
		type Item
	} from '#lib/api/client.ts';
	import type { ReferenceOut, ReferencesOut } from '#lib/api/generated/types.gen.ts';
	import { shortAuthors } from '#lib/format.ts';
	import { addedPaper } from '#lib/hints.svelte.ts';
	import { watchImport } from '#lib/processing.svelte.ts';
	import { notify } from '#lib/toasts.svelte.ts';
	import Title from '#lib/Title.svelte';

	/** The paper's reference list (each reference a paper in the library, a
	 * link to add, or text to look up) and the papers here citing it. */
	let { item }: { item: string } = $props();

	let list = $state<ReferencesOut | null>(null);
	let citing = $state<Item[]>([]);
	let all = $state(false);
	let looking = $state(false);
	/** What is going on with a reference (by position): adding, finding, a message. */
	let busy = $state<Record<number, 'adding' | 'finding'>>({});
	let notes = $state<Record<number, string>>({});

	const FIRST = 40;
	const SOURCES: Record<string, string> = {
		arxiv: "From arXiv's LaTeX source",
		crossref: 'From Crossref',
		pdf: 'Read from the PDF'
	};

	async function load(about: string) {
		const [references, cited] = await Promise.all([
			listReferences({ path: { item_id: about } }),
			listCiting({ path: { item_id: about } })
		]);
		if (about !== item) return;
		list = references.data ?? null;
		citing = cited.data ?? [];
	}

	$effect(() => {
		const about = item;
		list = null;
		citing = [];
		all = false;
		looking = false;
		busy = {};
		notes = {};
		load(about);
	});

	const references = $derived(list?.references ?? []);
	const shown = $derived(all ? references : references.slice(0, FIRST));
	const links = $derived(references.filter((r) => !r.item && (r.doi || r.arxiv)));

	const byline = (authors: string[], year: number | null | undefined) =>
		[shortAuthors(authors), year ? `(${year})` : ''].filter(Boolean).join(' ');

	/** Who, when and where, when known: "Hu et al. (2011). Nature Nanotechnology". */
	const details = (reference: ReferenceOut) =>
		[
			[reference.authors, reference.year ? `(${reference.year})` : ''].filter(Boolean).join(' '),
			reference.container ?? ''
		]
			.filter(Boolean)
			.join('. ');

	/** Only a DOI (publishers deposit some references so): the link says it all. */
	const bare = (reference: ReferenceOut) =>
		!reference.title && reference.text.toLowerCase() === `doi:${reference.doi}`;

	function outward(reference: ReferenceOut): { href: string; label: string } | null {
		if (reference.doi) return { href: `https://doi.org/${reference.doi}`, label: reference.doi };
		if (reference.arxiv)
			return {
				href: `https://arxiv.org/abs/${reference.arxiv}`,
				label: `arXiv:${reference.arxiv}`
			};
		if (reference.url) return { href: reference.url, label: reference.url };
		return null;
	}

	function replace(updated: ReferenceOut) {
		if (!list) return;
		list.references = list.references.map((r) => (r.position === updated.position ? updated : r));
	}

	/** Add the paper as "Add → by DOI" does (an arXiv ID by its arXiv DOI). */
	async function add(reference: ReferenceOut) {
		busy[reference.position] = 'adding';
		delete notes[reference.position];
		const doi = reference.doi ?? `10.48550/arXiv.${reference.arxiv}`;
		const { data, error, response } = await addItem({ body: { doi } });
		delete busy[reference.position];
		if (!data) {
			notes[reference.position] = errorMessage(error);
			return;
		}
		if (response?.status === 201) addedPaper(data.id, data.title, data.library_id);
		replace({ ...reference, item: data });
	}

	async function find(reference: ReferenceOut) {
		busy[reference.position] = 'finding';
		delete notes[reference.position];
		const { data, response } = await findReference({
			path: { item_id: item, position: reference.position }
		});
		delete busy[reference.position];
		if (data) replace(data);
		else
			notes[reference.position] =
				response?.status === 422 ? 'Crossref knows no paper that surely fits.' : 'Not found.';
	}

	async function importAll() {
		const { data, error } = await importReferences({ path: { item_id: item } });
		if (!data) {
			notify({ kind: 'warning', title: 'Could not start', text: errorMessage(error) });
			return;
		}
		watchImport(data.id, data.filename);
		notify({
			kind: 'info',
			title: 'Import started',
			text: `The ${links.length} papers go into the collection “${data.filename}”; you get a message when it is done.`
		});
	}

	/** Look again in the background; the list is reloaded when done. */
	async function lookAgain() {
		const before = list?.checked_at ?? null;
		const about = item;
		looking = true;
		await refreshReferences({ path: { item_id: about } });
		for (let tries = 0; tries < 30 && about === item; tries++) {
			await new Promise((done) => setTimeout(done, 3000));
			const { data } = await listReferences({ path: { item_id: about } });
			if (about !== item) return;
			if (data && data.checked_at !== before) {
				await load(about);
				break;
			}
		}
		looking = false;
	}
</script>

{#if list}
	<details>
		<summary>References{references.length ? ` (${references.length})` : ''}</summary>
		{#if references.length === 0}
			<p class="muted">
				{list.checked_at ? 'No reference list found yet.' : 'Not looked for yet.'}
				<button class="link" onclick={lookAgain} disabled={looking}
					>{looking ? 'Looking…' : 'Look again'}</button
				>
			</p>
		{:else}
			<p class="head">
				<span class="muted">{SOURCES[list.source ?? ''] ?? ''}</span>
				{#if links.length}
					<button class="link" onclick={importAll}
						>Import all {links.length} {links.length === 1 ? 'link' : 'links'}</button
					>
				{/if}
				<button class="link" onclick={lookAgain} disabled={looking}
					>{looking ? 'Looking…' : 'Look again'}</button
				>
			</p>
			<ol>
				{#each shown as reference (reference.position)}
					{@const link = outward(reference)}
					<li value={reference.position}>
						{#if reference.item}
							<a href={resolve('/items/[id]', { id: reference.item.id })}
								><Title text={reference.item.title} /></a
							>
							{#if byline(reference.item.authors, reference.item.year)}<span class="by"
									>{byline(reference.item.authors, reference.item.year)}</span
								>{/if}
						{:else}
							{#if !bare(reference)}<span class="text"
									>{#if reference.title}<Title
											text={reference.title}
										/>{:else}{reference.text}{/if}</span
								>{/if}
							{#if reference.title}<span class="by"
									>{details(reference) ||
										(reference.text.toLowerCase().startsWith('doi:') ? '' : reference.text)}</span
								>{/if}
							<span class="actions">
								{#if link}<a class="out" href={link.href} target="_blank" rel="noopener noreferrer"
										>{link.label}</a
									>{/if}
								{#if reference.doi || reference.arxiv}
									<button
										class="link"
										onclick={() => add(reference)}
										disabled={!!busy[reference.position]}
										>{busy[reference.position] === 'adding' ? 'Importing…' : 'Import'}</button
									>
								{:else if !reference.url}
									<button
										class="link"
										title="Look for it on Crossref"
										onclick={() => find(reference)}
										disabled={!!busy[reference.position]}
										>{busy[reference.position] === 'finding' ? 'Finding…' : 'Find'}</button
									>
								{/if}
								{#if notes[reference.position]}<span class="note">{notes[reference.position]}</span
									>{/if}
							</span>
						{/if}
					</li>
				{/each}
			</ol>
			{#if references.length > shown.length}
				<button class="link" onclick={() => (all = true)}>Show all {references.length}</button>
			{/if}
		{/if}
	</details>
{/if}
{#if citing.length}
	<details>
		<summary>Cited by ({citing.length}) in your library</summary>
		<ul>
			{#each citing as paper (paper.id)}
				<li>
					<a href={resolve('/items/[id]', { id: paper.id })}><Title text={paper.title} /></a>
					{#if byline(paper.authors, paper.year)}<span class="by"
							>{byline(paper.authors, paper.year)}</span
						>{/if}
				</li>
			{/each}
		</ul>
	</details>
{/if}

<style>
	details {
		margin-top: 10px;
		font-size: var(--step--1);
	}
	summary {
		cursor: pointer;
		color: var(--muted);
		width: fit-content;
	}
	summary:hover {
		color: inherit;
	}
	.head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 8px;
	}
	ol,
	ul {
		margin: 8px 0 0;
		display: grid;
		gap: 8px;
	}
	ol {
		padding-left: 2.4em;
	}
	ul {
		padding: 0;
		list-style: none;
	}
	li {
		min-width: 0;
		overflow-wrap: anywhere;
	}
	ol li::marker {
		color: var(--muted);
	}
	li > a,
	li > .by,
	li > .text {
		display: block;
	}
	li > a {
		font-weight: 600;
	}
	.by,
	.note {
		color: var(--muted);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 2px 6px;
		margin-top: 1px;
	}
	.out {
		color: var(--muted);
	}
	.link {
		padding: 2px 6px;
		border: none;
		background: none;
		color: var(--royal);
		font-size: var(--step--1);
		font-weight: 550;
	}
	p {
		margin: 8px 0 0;
	}
</style>
