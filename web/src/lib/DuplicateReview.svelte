<script lang="ts">
	import Title from '#lib/Title.svelte';
	import { plainTitle } from '#lib/title.svelte.ts';
	import { mdiArrowLeftBold, mdiClose } from '@mdi/js';
	import { resolve } from '$app/paths';
	import { untrack } from 'svelte';
	import {
		errorMessage,
		markDifferent,
		mergeItem,
		previewMerge,
		trashItem
	} from '#lib/api/client.ts';
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
	/** The version whose details the paper shows after merging. */
	let shownVersion = $state<string | null>(null);
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
			if (away?.id !== from.id || keep?.id !== into.id) return;
			steps = data?.steps ?? [];
			shownVersion = data?.shown_version_id ?? null;
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
		const { error } = await mergeItem({
			path: { item_id: away.id },
			body: { into: keep.id, leave, drop }
		});
		busy = false;
		if (error) {
			notify({ kind: 'warning', title: 'Not merged', text: errorMessage(error) });
			return;
		}
		notify({
			kind: 'success',
			title: 'Merged',
			text: `“${plainTitle(away.title)}” is in the trash.`
		});
		await loadOrganize();
		done();
	}

	/** No merging: the other paper simply goes to the trash. */
	async function trashOther() {
		if (!away || busy) return;
		busy = true;
		const { error } = await trashItem({ path: { item_id: away.id } });
		busy = false;
		if (error) {
			notify({ kind: 'warning', title: 'Not moved to the trash', text: errorMessage(error) });
			return;
		}
		notify({
			kind: 'success',
			title: 'In the trash',
			text: `“${plainTitle(away.title)}”, not merged.`
		});
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
			t: () => trashOther(),
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

	/** What becomes of a value when merging: on the kept paper it stays; on
	 * the other it moves over, is there already, or goes to the trash with
	 * the paper. Plain: not known yet. */
	type Fate = 'stays' | 'moves' | 'same' | 'goes' | 'plain';
	type Chip = { text: string; fate: Fate; why?: string; toggle?: () => void };
	const FATE: Record<Fate, { mark: string; words: string }> = {
		stays: { mark: '✓', words: 'stays' },
		moves: { mark: '←', words: 'moves to the kept paper' },
		same: { mark: '=', words: 'there already' },
		goes: { mark: '✕', words: 'goes to the trash' },
		plain: { mark: '', words: '' }
	};
	const FROM_STEP: Record<string, Fate> = { move: 'moves', already: 'same', stays: 'goes' };

	/** The person's choices for this pair: what of the other paper not to
	 * take over, and what to remove from the kept one. */
	let leave = $state<string[]>([]);
	let drop = $state<string[]>([]);
	$effect(() => {
		void keep?.id;
		void away?.id;
		leave = [];
		drop = [];
	});
	const flip = (list: string[], id: string) =>
		list.includes(id) ? list.filter((x) => x !== id) : [...list, id];

	/** Files that move along with their version (they follow it in the plan). */
	const versionOf = $derived.by(() => {
		const found = new Map<string, string>();
		let version: MergeStep | null = null;
		for (const step of steps ?? []) {
			if (step.kind === 'version') version = step;
			else if (step.kind === 'file' && step.id && version?.action === 'move' && version.id) {
				found.set(step.id, version.id);
			}
		}
		return found;
	});
	const versionsMoving = $derived(
		(steps ?? []).some((s) => s.kind === 'version' && s.action === 'move' && !leave.includes(s.id!))
	);

	/** The other paper's version will be the one shown (it ranks first:
	 * pinned, or published before preprint) unless it is left out. */
	const otherShown = $derived(
		Boolean(
			shownVersion &&
			!leave.includes(shownVersion) &&
			(steps ?? []).some(
				(s) => s.kind === 'version' && s.id === shownVersion && s.action === 'move'
			)
		)
	);

	/** A step of the plan as a chip: what moves over can be left out. */
	function planned(step: MergeStep): Chip {
		const chip: Chip = {
			text: step.name,
			fate: FROM_STEP[step.action],
			why: step.reason ?? undefined
		};
		const version = step.id ? versionOf.get(step.id) : undefined;
		if (version && leave.includes(version)) {
			return { ...chip, fate: 'goes', why: 'its version stays with the other paper' };
		}
		if (step.action === 'already' && step.id && drop.includes(step.id)) {
			return { ...chip, fate: 'goes', why: 'removed from the kept paper too' };
		}
		if (step.action !== 'move' || !step.id) return chip;
		const id = step.id;
		const left = leave.includes(id);
		return {
			...chip,
			fate: left ? 'goes' : 'moves',
			why: left ? 'left out' : undefined,
			toggle: () => (leave = flip(leave, id))
		};
	}

	/** One of the kept paper's tags, collections or files: can be removed. */
	function own(text: string, id: string, what: string): Chip {
		const dropped = drop.includes(id);
		return {
			text,
			fate: dropped ? 'goes' : 'stays',
			why: dropped ? what : undefined,
			toggle: () => (drop = flip(drop, id))
		};
	}

	/** One of the other paper's details: stays with its version if that
	 * moves over (the kept paper's details are the ones shown). */
	function detail(text: string, onKept: string[], owner = false): Chip {
		if (!steps) return { text, fate: 'plain' };
		if (onKept.includes(text)) return { text, fate: 'same' };
		if (!owner && otherShown) {
			return { text, fate: 'moves', why: 'shown after merging: its version comes first' };
		}
		if (!owner && versionsMoving) {
			return {
				text,
				fate: 'moves',
				why: 'kept with its version; the kept paper’s details are shown'
			};
		}
		return { text, fate: 'goes', why: 'the kept paper’s details are used' };
	}

	/** An identifier goes where its version goes. */
	function identifier(text: string, scheme: string, value: string): Chip {
		const version = (steps ?? []).find(
			(s) => s.kind === 'version' && s.name.includes(`${scheme} ${value}`)
		);
		if (!steps || !version) return { text, fate: 'plain' };
		return { ...planned(version), text };
	}

	const rows = $derived.by(() => {
		if (!keep || !away) return [];
		const k = keep;
		const a = away;
		const plan = (kind: string) => (steps ?? []).filter((s) => s.kind === kind).map(planned);
		const names = (item: ItemOut) =>
			item.collection_ids.map((id) => ({
				id,
				name: organize.collections.find((c) => c.id === id)?.name ?? ''
			}));
		const shown = (item: ItemOut): Record<string, string[]> => ({
			Authors: item.authors.length ? [item.authors.map(fullName).join(', ')] : [],
			Year: item.year ? [String(item.year)] : [],
			'Published in': item.container_title ? [item.container_title] : [],
			Type: [typeName(item.type)]
		});
		const mine = shown(k);
		const theirs = shown(a);
		const stays = (text: string): Chip => ({ text, fate: 'stays' });
		const notes = (steps ?? []).filter((s) => s.kind === 'note');
		return [
			...Object.keys(mine).map((label) => ({
				label,
				left: mine[label].map(stays),
				right: theirs[label].map((text) => detail(text, mine[label]))
			})),
			{
				label: 'Identifiers',
				left: k.identifiers.map((i) => stays(`${i.scheme.toUpperCase()} ${i.value}`)),
				right: a.identifiers.map((i) =>
					identifier(`${i.scheme.toUpperCase()} ${i.value}`, i.scheme, i.value)
				)
			},
			{
				label: 'Files',
				left: (k.files ?? []).map((f) => own(f.filename, f.id, 'goes to the trash')),
				right: steps ? plan('file') : (a.files ?? []).map((f) => detail(f.filename, []))
			},
			{
				label: 'Tags',
				left: k.tags.map((t) => own(t.name, t.id, 'removed from the paper')),
				right: steps ? plan('tag') : a.tags.map((t) => detail(t.name, []))
			},
			{
				label: 'Collections',
				left: names(k).map((c) => own(c.name, c.id, 'removed from the collection')),
				right: steps ? plan('collection') : names(a).map((c) => detail(c.name, []))
			},
			// Notes only from the plan (the kept paper's are not listed).
			...(notes.length
				? [
						{
							label: 'Notes',
							left: notes.filter((s) => s.action === 'already').map((s) => stays(s.name)),
							right: notes.map(planned)
						}
					]
				: []),
			{
				label: 'Owner',
				left: [stays(libraryName(k.library_id))],
				right: [detail(libraryName(a.library_id), [libraryName(k.library_id)], true)]
			}
		];
	});
	const choosable = $derived(rows.some((r) => [...r.left, ...r.right].some((c) => c.toggle)));
</script>

{#snippet chips(list: Chip[])}
	{#if list.length === 0}<span class="muted">none</span>{/if}
	{#each list as chip, i (i)}
		{@const fate = FATE[chip.fate]}
		{@const title = [fate.words, chip.why].filter(Boolean).join(': ')}
		{#if chip.toggle}
			<button
				type="button"
				class="chip {chip.fate}"
				title="{title}. Click to {chip.fate === 'goes' ? 'keep it' : 'let it go'}."
				onclick={chip.toggle}
				disabled={busy}
				><b aria-hidden="true">{fate.mark}</b>
				{chip.text}<span class="visually-hidden">({title})</span></button
			>
		{:else}
			<span class="chip {chip.fate}" title={title || undefined}
				>{#if fate.mark}<b aria-hidden="true">{fate.mark}</b>
				{/if}{chip.text}{#if title}<span class="visually-hidden">({title})</span>{/if}</span
			>
		{/if}
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
			><Title text={item.title} /></a
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
		<p class="legend muted">
			{#each ['stays', 'moves', 'same', 'goes'] as const as fate (fate)}
				<span><b class={fate} aria-hidden="true">{FATE[fate].mark}</b> {FATE[fate].words}</span>
			{/each}
			{#if steps === null && pair.can_merge}<span>Working it out…</span>{/if}
		</p>
		{#if otherShown}<p class="muted hint">
				After merging, the paper shows the other one’s details: its version comes first (a pinned or
				published version before a preprint, else the newer one). The kept paper’s details stay with
				its own version.
			</p>{/if}
		{#if choosable}<p class="muted hint">
				Click a file, tag, collection or note to keep it or let it go.
			</p>{/if}
		{#if pair.can_merge && !swapped && pair.why.length}<p class="muted hint">
				Suggested to keep the left one because it {pair.why.join(', ')}.
			</p>{/if}

		<footer>
			<div class="keys muted">
				<kbd>M</kbd> merge <kbd>S</kbd> swap <kbd>N</kbd> not the same <kbd>T</kbd> trash the other
				<kbd>→</kbd> skip
			</div>
			<div class="buttons">
				<button onclick={different} disabled={busy}>Not the same paper</button>
				<button onclick={trashOther} disabled={busy}>Trash the other one</button>
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
	button.chip {
		font: inherit;
		color: inherit;
		background: none;
		cursor: pointer;
	}
	button.chip:hover {
		background: var(--rail);
	}
	button.chip.goes {
		text-decoration: line-through;
		text-decoration-color: var(--danger);
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 2px 14px;
		margin: 0 0 4px;
		font-size: var(--step--1);
	}
	.legend b {
		font-weight: 700;
	}
	.legend .stays,
	.legend .moves {
		color: var(--success);
	}
	.legend .goes {
		color: var(--danger);
	}
	.hint {
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
