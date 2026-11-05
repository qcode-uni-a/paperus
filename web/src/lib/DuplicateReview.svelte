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

	const collectionNames = (item: ItemOut) =>
		item.collection_ids
			.map((id) => organize.collections.find((c) => c.id === id)?.name)
			.filter(Boolean)
			.join(', ');

	/** A paper's details, each as label and text, to compare line by line. */
	function details(item: ItemOut): [string, string][] {
		return [
			['Authors', item.authors.map(fullName).join(', ') || '–'],
			['Year', item.year ? String(item.year) : '–'],
			['Published in', item.container_title ?? '–'],
			['Type', typeName(item.type)],
			[
				'Identifiers',
				item.identifiers.map((i) => `${i.scheme.toUpperCase()} ${i.value}`).join(', ') || 'none'
			],
			['Files', (item.files ?? []).map((f) => f.filename).join(', ') || 'none'],
			['Tags', item.tags.map((t) => t.name).join(', ') || 'none'],
			['Collections', collectionNames(item) || 'none'],
			['Owner', libraryName(item.library_id)]
		];
	}
	const rows = $derived.by(() => {
		if (!keep || !away) return [];
		const left = details(keep);
		const right = details(away);
		return left.map(([label, value], i) => ({
			label,
			left: value,
			right: right[i][1],
			differs: value !== right[i][1]
		}));
	});

	const STEP_KIND: Record<string, string> = {
		version: 'Version',
		file: 'File',
		tag: 'Tag',
		collection: 'Collection',
		note: 'Note'
	};
	const moving = $derived((steps ?? []).filter((s) => s.action === 'move'));
	const already = $derived((steps ?? []).filter((s) => s.action === 'already'));
	const staying = $derived((steps ?? []).filter((s) => s.action === 'stays'));
</script>

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

		<table class="compare">
			<tbody>
				{#each rows as row (row.label)}
					<tr class:differs={row.differs}>
						<td>{row.left}</td>
						<th scope="row">{row.label}</th>
						<td>{row.right}</td>
					</tr>
				{/each}
			</tbody>
		</table>

		<section class="plan">
			<h3>What merging does</h3>
			{#if !pair.can_merge}
				<p class="warn">Cannot merge: {pair.why.join(', ')}.</p>
			{:else if steps === null}
				<p class="muted">Working it out…</p>
			{:else}
				{#if !swapped && pair.why.length}<p class="muted">
						Suggested to keep the left one because it {pair.why.join(', ')}.
					</p>{/if}
				<ul>
					{#each moving as step (step.kind + step.name)}
						<li class="move">
							<b>{STEP_KIND[step.kind]}</b>
							{step.name} <span class="muted">moves to the kept paper</span>
						</li>
					{/each}
					{#each already as step (step.kind + step.name)}
						<li class="already">
							<b>{STEP_KIND[step.kind]}</b>
							{step.name}
							<span class="muted">is there already{step.reason ? ` (${step.reason})` : ''}</span>
						</li>
					{/each}
					{#each staying as step (step.kind + step.name)}
						<li class="stays">
							<b>{STEP_KIND[step.kind]}</b>
							{step.name}
							<span class="muted">stays behind{step.reason ? `: ${step.reason}` : ''}</span>
						</li>
					{/each}
					<li class="trash">
						<b>Paper</b> “{away.title}”
						<span class="muted">goes to the trash (can be restored)</span>
					</li>
				</ul>
			{/if}
		</section>

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
	h3 {
		margin: 0 0 6px;
		font-size: var(--step-0);
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
	.compare tr.differs td {
		background: color-mix(in srgb, var(--highlighter) 22%, transparent);
	}
	.plan ul {
		display: grid;
		gap: 3px;
		margin: 0;
		padding: 0;
		list-style: none;
		font-size: var(--step--1);
	}
	.plan li::before {
		display: inline-block;
		width: 1.4em;
		font-weight: 700;
	}
	.plan .move::before {
		content: '→';
		color: var(--success);
	}
	.plan .already::before {
		content: '=';
		color: var(--muted);
	}
	.plan .stays::before {
		content: '×';
		color: var(--danger);
	}
	.plan .trash::before {
		content: '🗑';
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
