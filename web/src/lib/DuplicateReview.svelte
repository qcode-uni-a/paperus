<script lang="ts">
	import { mdiArrowLeftBold, mdiClose } from '@mdi/js';
	import { resolve } from '$app/paths';
	import { untrack } from 'svelte';
	import { errorMessage, markDifferent, mergeItem, previewMerge } from '#lib/api/client.ts';
	import type { DuplicateOut, ItemOut, MergeStep } from '#lib/api/generated/types.gen.ts';
	import { fullName, typeName } from '#lib/format.ts';
	import Icon from '#lib/Icon.svelte';
	import { libraryName, loadOrganize, organize } from '#lib/organize.svelte.ts';
	import PdfThumb from '#lib/PdfThumb.svelte';
	import { notify } from '#lib/toasts.svelte.ts';

	/** The likely duplicates one pair after another: both papers side by
	 * side (first page and details), and what merging would do. */
	let { pairs, onclose }: { pairs: DuplicateOut[]; onclose: (changed: boolean) => void } = $props();

	const REASONS: Record<string, string> = {
		identifier: 'Same DOI or arXiv ID',
		file: 'Same file',
		title: 'Same title'
	};

	let dialog = $state<HTMLDialogElement>();
	// A copy taken once: the pairs left to review shrink as they are done.
	let queue = $state<DuplicateOut[]>(untrack(() => [...pairs]));
	let index = $state(0);
	/** The other paper kept instead of the recommended one. */
	let swapped = $state(false);
	let steps = $state<MergeStep[] | null>(null);
	let busy = $state(false);
	let changed = false;

	$effect(() => {
		dialog?.showModal();
	});

	const pair = $derived(queue[index]);
	const keep = $derived(pair ? (swapped ? pair.merge : pair.keep) : null);
	const away = $derived(pair ? (swapped ? pair.keep : pair.merge) : null);

	// What merging would do, from the same plan the merge carries out.
	$effect(() => {
		const from = away;
		const into = keep;
		steps = null;
		if (!from || !into || !pair?.can_merge) return;
		previewMerge({ path: { item_id: from.id }, query: { into: into.id } }).then(({ data }) => {
			if (away?.id === from.id && keep?.id === into.id) steps = data?.steps ?? [];
		});
	});

	function next() {
		swapped = false;
		if (index < queue.length - 1) index += 1;
		else finish();
	}

	function done() {
		// The pair leaves the queue; the next one moves up to this place.
		queue = queue.filter((_, i) => i !== index);
		swapped = false;
		changed = true;
		if (index >= queue.length) index = Math.max(0, queue.length - 1);
		if (queue.length === 0) finish();
	}

	async function merge() {
		if (!keep || !away || busy) return;
		busy = true;
		const { error } = await mergeItem({ path: { item_id: away.id }, body: { into: keep.id } });
		busy = false;
		if (error) {
			notify({ kind: 'warning', title: 'Not merged', text: errorMessage(error) });
			return;
		}
		notify({ kind: 'success', title: 'Merged', text: `“${away.title}” is in the trash.` });
		await loadOrganize();
		done();
	}

	async function different() {
		if (!pair || busy) return;
		busy = true;
		await markDifferent({ body: { a: pair.keep.id, b: pair.merge.id } });
		busy = false;
		done();
	}

	function finish() {
		dialog?.close();
	}

	function key(event: KeyboardEvent) {
		if (busy || event.target instanceof HTMLInputElement) return;
		const actions: Record<string, () => void> = {
			m: () => pair?.can_merge && merge(),
			s: () => (swapped = !swapped),
			n: () => different(),
			ArrowRight: () => next(),
			ArrowLeft: () => {
				swapped = false;
				index = Math.max(0, index - 1);
			}
		};
		const action = actions[event.key];
		if (action) {
			event.preventDefault();
			action();
		}
	}

	const collectionNames = (item: ItemOut): string[] =>
		item.collection_ids
			.map((id) => organize.collections.find((c) => c.id === id)?.name)
			.filter((name): name is string => Boolean(name));

	/** What becomes of a value when merging: on the kept paper it stays; on
	 * the other it moves over, is there already, or goes to the trash with
	 * the paper. Plain: not known yet. */
	type Fate = 'stays' | 'moves' | 'same' | 'goes' | 'plain';
	type Chip = { text: string; fate: Fate; why?: string };
	const FATE: Record<Fate, { mark: string; words: string }> = {
		stays: { mark: '✓', words: 'stays' },
		moves: { mark: '←', words: 'moves to the kept paper' },
		same: { mark: '=', words: 'there already' },
		goes: { mark: '✕', words: 'goes to the trash with the paper' },
		plain: { mark: '', words: '' }
	};

	const identifierText = (i: { scheme: string; value: string }) =>
		`${i.scheme.toUpperCase()} ${i.value}`;

	/** A paper's details, each with its label, to compare line by line. */
	function details(item: ItemOut): [string, string[]][] {
		return [
			['Authors', item.authors.length ? [item.authors.map(fullName).join(', ')] : []],
			['Year', item.year ? [String(item.year)] : []],
			['Published in', item.container_title ? [item.container_title] : []],
			['Type', [typeName(item.type)]],
			['Identifiers', item.identifiers.map(identifierText)],
			['Files', (item.files ?? []).map((f) => f.filename)],
			['Tags', item.tags.map((t) => t.name)],
			['Collections', collectionNames(item)],
			['Owner', [libraryName(item.library_id)]]
		];
	}
	// Rows whose things merging moves one by one: from the merge's own plan.
	const PLANNED: Record<string, string> = {
		Files: 'file',
		Tags: 'tag',
		Collections: 'collection',
		Notes: 'note'
	};
	const FROM_STEP: Record<string, Fate> = { move: 'moves', already: 'same', stays: 'goes' };

	function fateOf(label: string, text: string, onKept: string[]): Chip {
		if (!steps) return { text, fate: 'plain' };
		if (label === 'Identifiers') {
			// It goes along with its version.
			const id = text.replace(/^(\S+) /, (_, scheme: string) => `${scheme.toLowerCase()} `);
			const version = steps.find((s) => s.kind === 'version' && s.name.includes(id));
			if (version)
				return { text, fate: FROM_STEP[version.action], why: version.reason ?? undefined };
		}
		if (onKept.includes(text)) return { text, fate: 'same' };
		// Kept with its version when that moves over (the kept paper's
		// details are the ones shown); otherwise gone with the paper.
		if (label !== 'Owner' && steps.some((s) => s.kind === 'version' && s.action === 'move')) {
			return {
				text,
				fate: 'moves',
				why: 'kept with its version; the kept paper’s details are shown'
			};
		}
		return { text, fate: 'goes', why: 'the kept paper’s details are used' };
	}

	const rows = $derived.by(() => {
		if (!keep || !away) return [];
		const left = details(keep);
		const right = new Map(details(away));
		const result = left.map(([label, values]) => {
			const theirs = right.get(label) ?? [];
			const kind = PLANNED[label];
			const planned = kind && steps ? steps.filter((s) => s.kind === kind) : null;
			return {
				label,
				left: values.map((text): Chip => ({ text, fate: 'stays' })),
				right: planned
					? planned.map((s): Chip => ({
							text: s.name,
							fate: FROM_STEP[s.action],
							why: s.reason ?? undefined
						}))
					: theirs.map((text) => fateOf(label, text, values))
			};
		});
		// Notes are only known from the plan (the kept paper's are not listed).
		const notes = (steps ?? []).filter((s) => s.kind === 'note');
		if (notes.length) {
			result.push({
				label: 'Notes',
				left: notes
					.filter((s) => s.action === 'already')
					.map((s): Chip => ({ text: s.name, fate: 'stays' })),
				right: notes.map((s): Chip => ({ text: s.name, fate: FROM_STEP[s.action] }))
			});
		}
		return result;
	});
</script>

{#snippet chips(list: Chip[])}
	{#if list.length === 0}<span class="muted">none</span>{/if}
	{#each list as chip, i (i)}
		{@const fate = FATE[chip.fate]}
		<span
			class="chip {chip.fate}"
			title={[fate.words, chip.why].filter(Boolean).join(': ') || undefined}
			>{#if fate.mark}<b aria-hidden="true">{fate.mark}</b>
			{/if}{chip.text}{#if fate.words}<span class="visually-hidden"
					>({fate.words}{chip.why ? `: ${chip.why}` : ''})</span
				>{/if}</span
		>
	{/each}
{/snippet}

{#snippet paper(item: ItemOut, role: string, kept: boolean)}
	{@const pdf = (item.files ?? []).find((f) => f.media_type === 'application/pdf')}
	<article class="paper" class:kept>
		<span class="role">{role}</span>
		<div class="preview">
			{#if pdf}
				{#key pdf.id}<PdfThumb url="/api/files/{pdf.id}/content" width={220} />{/key}
			{:else}
				<div class="no-file">{(item.files ?? []).length ? 'No PDF' : 'No file'}</div>
			{/if}
		</div>
		<a class="title" href={resolve('/items/[id]', { id: item.id })} target="_blank" rel="noopener"
			>{item.title}</a
		>
	</article>
{/snippet}

<dialog
	bind:this={dialog}
	aria-labelledby="review-title"
	onclose={() => onclose(changed)}
	onkeydown={key}
>
	{#if pair && keep && away}
		<header>
			<div>
				<h2 id="review-title">Duplicate {index + 1} of {queue.length}</h2>
				<div class="reasons">
					{#each pair.reasons as reason (reason)}<span class="badge"
							>{REASONS[reason] ?? reason}</span
						>{/each}
				</div>
			</div>
			<button class="icon" aria-label="Close" onclick={finish}><Icon path={mdiClose} /></button>
		</header>

		<div class="sides">
			{@render paper(
				keep,
				swapped ? 'Keep this one (your choice)' : 'Keep this one (suggested)',
				true
			)}
			<div class="arrow" aria-hidden="true">
				<Icon path={mdiArrowLeftBold} size={28} />
				<span>merged into</span>
			</div>
			{@render paper(away, 'Merged into it, then to the trash', false)}
		</div>

		{#if !pair.can_merge}
			<p class="warn">Cannot merge: {pair.why.join(', ')}.</p>
		{:else}
			<p class="legend">
				{#each ['stays', 'moves', 'same', 'goes'] as const as fate (fate)}
					<span class="chip {fate}"
						><b aria-hidden="true">{FATE[fate].mark}</b> {FATE[fate].words}</span
					>
				{/each}
				{#if steps === null}<span class="muted">Working it out…</span>{/if}
			</p>
		{/if}

		<table class="compare">
			<thead>
				<tr>
					<th scope="col">Kept</th>
					<th></th>
					<th scope="col">Merged into it, then to the trash (can be restored)</th>
				</tr>
			</thead>
			<tbody>
				{#each rows as row (row.label)}
					<tr>
						<td>{@render chips(row.left)}</td>
						<th scope="row">{row.label}</th>
						<td>{@render chips(row.right)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
		{#if pair.can_merge && !swapped && pair.why.length}<p class="muted why">
				Suggested to keep the left one because it {pair.why.join(', ')}.
			</p>{/if}

		<footer>
			<div class="keys muted">
				<kbd>M</kbd> merge <kbd>S</kbd> swap <kbd>N</kbd> not the same <kbd>→</kbd> skip
			</div>
			<div class="buttons">
				<button onclick={different} disabled={busy}>Not the same paper</button>
				<button onclick={() => (swapped = !swapped)} disabled={busy}>Keep the other one</button>
				<button onclick={next} disabled={busy}>Skip</button>
				<button
					class="primary"
					onclick={merge}
					disabled={busy || !pair.can_merge || steps === null}
				>
					{busy ? 'Merging…' : 'Merge'}
				</button>
			</div>
		</footer>
	{/if}
</dialog>

<style>
	dialog {
		width: min(1100px, calc(100vw - 32px));
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
		margin: 0 0 6px;
		font-size: var(--step-2);
	}
	.reasons {
		display: flex;
		gap: 6px;
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
		grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
		gap: 12px;
		align-items: start;
	}
	.paper {
		display: grid;
		gap: 10px;
		justify-items: center;
		padding: 14px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--rail);
	}
	.paper.kept {
		border-color: var(--royal);
		box-shadow: 0 0 0 1px var(--royal);
	}
	.role {
		justify-self: start;
		font-size: var(--step--1);
		font-weight: 650;
		color: var(--muted);
	}
	.kept .role {
		color: var(--royal);
	}
	.no-file {
		display: grid;
		place-items: center;
		width: 220px;
		height: 286px;
		border: 2px dashed var(--rule);
		border-radius: 4px;
		color: var(--muted);
	}
	.title {
		font-family: var(--serif);
		font-weight: 600;
		text-align: center;
		color: var(--ink);
	}
	.arrow {
		display: grid;
		justify-items: center;
		gap: 4px;
		align-self: center;
		color: var(--royal);
		font-size: var(--step--1);
	}
	.compare {
		width: 100%;
		margin: 16px 0;
		border-collapse: collapse;
		font-size: var(--step--1);
	}
	.compare td,
	.compare th {
		padding: 5px 8px;
		border-top: 1px solid var(--rule);
		vertical-align: top;
		overflow-wrap: anywhere;
	}
	.compare td {
		width: 45%;
	}
	.compare td:first-child {
		text-align: right;
	}
	.compare th {
		width: 10%;
		color: var(--muted);
		font-weight: 600;
		text-align: center;
		white-space: nowrap;
	}
	.compare thead th {
		border-top: none;
		font-size: var(--step--1);
		font-weight: 650;
		color: var(--muted);
		white-space: normal;
	}
	.compare thead th:first-child {
		text-align: right;
	}
	.compare thead th:last-child {
		text-align: left;
	}
	.compare td {
		line-height: 1.9;
	}
	/* Each value with what becomes of it: the border's colour and a mark. */
	.chip {
		display: inline-block;
		margin: 1px 2px;
		padding: 0 8px;
		border: 1.5px solid var(--rule);
		border-radius: 999px;
		line-height: 1.6;
		overflow-wrap: anywhere;
	}
	.chip b {
		margin-right: 2px;
	}
	.chip.stays,
	.chip.moves {
		border-color: var(--success);
	}
	.chip.stays b,
	.chip.moves b {
		color: var(--success);
	}
	.chip.same {
		border-style: dashed;
		color: var(--muted);
	}
	.chip.goes {
		border-color: var(--danger);
	}
	.chip.goes b {
		color: var(--danger);
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 8px;
		margin: 14px 0 0;
		font-size: var(--step--1);
	}
	.why {
		margin: 0;
		font-size: var(--step--1);
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}
	.warn {
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
		.arrow {
			transform: rotate(90deg);
		}
		.compare td:first-child {
			text-align: left;
		}
	}
</style>
