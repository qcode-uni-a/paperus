<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import {
		errorMessage,
		listDuplicates,
		listItems,
		mergeItem,
		previewMerge,
		type Item,
		type ItemDetail
	} from '#lib/api/client.ts';
	import type { MergeStep } from '#lib/api/generated/types.gen.ts';
	import { shortAuthors } from '#lib/format.ts';
	import { libraryName, loadOrganize } from '#lib/organize.svelte.ts';

	/** Merge this paper into another one (the same paper twice), showing
	 * beforehand what moves and what stays behind. ``onmerged`` instead of
	 * going to the paper that stayed. */
	let { item, onmerged }: { item: ItemDetail | Item; onmerged?: (kept: ItemDetail) => void } =
		$props();

	const KINDS = [
		['version', 'Versions'],
		['file', 'Files'],
		['tag', 'Tags'],
		['collection', 'Collections'],
		['note', 'Notes']
	] as const;

	let dialog = $state<HTMLDialogElement>();
	let likely = $state<Item[]>([]);
	let words = $state('');
	let found = $state<Item[]>([]);
	let chosen = $state<Item | null>(null);
	let steps = $state<MergeStep[] | null>(null);
	let error = $state('');
	let merging = $state(false);
	let latest = 0;

	const staying = $derived((steps ?? []).filter((s) => s.action === 'stays'));
	const moving = $derived((steps ?? []).filter((s) => s.action === 'move'));

	/** With ``into``, straight to what merging into it would do. */
	export async function open(into?: Item) {
		words = '';
		chosen = null;
		steps = null;
		error = '';
		found = [];
		dialog?.showModal();
		if (into) {
			await choose(into);
			return;
		}
		const { data } = await listDuplicates({ path: { item_id: item.id } });
		likely = data ?? [];
	}

	$effect(() => {
		const query = words.trim();
		const request = ++latest;
		if (!query) {
			found = [];
			return;
		}
		const timer = setTimeout(async () => {
			const { data } = await listItems({ query: { title: query, limit: 20 } });
			if (request === latest) found = (data ?? []).filter((other) => other.id !== item.id);
		}, 200);
		return () => clearTimeout(timer);
	});

	async function choose(other: Item) {
		chosen = other;
		steps = null;
		error = '';
		const { data, error: failure } = await previewMerge({
			path: { item_id: item.id },
			query: { into: other.id }
		});
		if (chosen?.id !== other.id) return;
		if (failure) error = errorMessage(failure);
		steps = data?.steps ?? null;
	}

	async function merge() {
		if (!chosen) return;
		merging = true;
		const { data, error: failure } = await mergeItem({
			path: { item_id: item.id },
			body: { into: chosen.id }
		});
		merging = false;
		if (!data) {
			error = errorMessage(failure);
			return;
		}
		dialog?.close();
		await loadOrganize();
		if (onmerged) onmerged(data.item);
		else await goto(resolve('/items/[id]', { id: data.item.id }));
	}

	/** "Huber and Koren (2026), Shared library", leaving out what is missing. */
	function meta(other: { authors: string[]; year?: number | null; library_id: string }): string {
		const who = [shortAuthors(other.authors), other.year ? `(${other.year})` : '']
			.filter(Boolean)
			.join(' ');
		return [who, libraryName(other.library_id)].filter(Boolean).join(', ');
	}
</script>

{#snippet choice(other: Item)}
	<li>
		<button class="paper" onclick={() => choose(other)}>
			<strong>{other.title}</strong>
			<small>{meta(other)}</small>
		</button>
	</li>
{/snippet}

{#snippet mark(action: MergeStep['action'])}
	<span class="mark {action}" aria-hidden="true">
		<svg viewBox="0 0 24 24">
			{#if action === 'move'}
				<path d="m5 12.5 4.5 4.5L19 7.5" />
			{:else if action === 'already'}
				<path d="M6 10h12M6 14h12" />
			{:else}
				<path d="M12 7v6M12 17h.01" />
			{/if}
		</svg>
	</span>
{/snippet}

<dialog bind:this={dialog} aria-labelledby="merge-title">
	<h2 id="merge-title">Merge into another paper</h2>

	{#if !chosen}
		<p class="muted">
			For the same paper twice. This one goes to the trash; the paper you choose keeps its details
			and takes over what it can.
		</p>
		{#if likely.length}
			<h3>Likely the same paper</h3>
			<ul class="choices">
				{#each likely as other (other.id)}{@render choice(other)}{/each}
			</ul>
		{/if}
		<input
			type="search"
			bind:value={words}
			placeholder="Search by title"
			aria-label="Search papers"
		/>
		{#if found.length}
			<ul class="choices">
				{#each found as other (other.id)}{@render choice(other)}{/each}
			</ul>
		{/if}
	{:else}
		<div class="pair">
			<div class="card from">
				<small>This paper, to the trash</small>
				<strong>{item.title}</strong>
				<small>{meta(item)}</small>
			</div>
			<span class="arrow" aria-hidden="true">→</span>
			<div class="card to">
				<small>Stays, takes over</small>
				<strong>{chosen.title}</strong>
				<small>{meta(chosen)}</small>
			</div>
		</div>

		{#if steps === null && !error}
			<p class="muted">Checking what can move…</p>
		{:else if steps}
			{#if staying.length}
				<p class="banner">
					Not everything can move: {staying.length}
					{staying.length === 1 ? 'thing stays' : 'things stay'} with this paper in the trash (you can
					restore it from there).
				</p>
			{:else if moving.length === 0}
				<p class="banner calm">The other paper already has everything this one has.</p>
			{/if}
			{#each KINDS as [kind, label] (kind)}
				{@const rows = steps.filter((s) => s.kind === kind)}
				{#if rows.length}
					<section>
						<h3>{label}</h3>
						<ul class="steps">
							{#each rows as step, index (index)}
								<li class={step.action}>
									{@render mark(step.action)}
									<span class="name">{step.name}</span>
									<span class="what"
										>{step.action === 'move'
											? 'moves over'
											: step.action === 'already'
												? 'already there'
												: step.reason}</span
									>
								</li>
							{/each}
						</ul>
					</section>
				{/if}
			{/each}
		{/if}
		<button class="link back" onclick={() => ((chosen = null), (steps = null))}
			>Choose another paper</button
		>
	{/if}

	{#if error}<p class="error">{error}</p>{/if}
	<div class="buttons">
		<button type="button" onclick={() => dialog?.close()}>Cancel</button>
		<button class="primary" disabled={!steps || merging} onclick={merge}
			>{staying.length ? 'Merge anyway' : 'Merge'}</button
		>
	</div>
</dialog>

<style>
	dialog {
		width: min(640px, calc(100vw - 32px));
		max-height: min(800px, calc(100dvh - 32px));
		padding: 22px 24px 20px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	dialog[open] {
		display: grid;
		gap: 12px;
		overflow-y: auto;
	}
	dialog::backdrop {
		background: rgb(10 14 30 / 0.4);
	}
	h2 {
		margin: 0;
		font-size: var(--step-2);
	}
	h3 {
		margin: 4px 0 6px;
		font-size: var(--step-0);
	}
	p {
		margin: 0;
	}
	ul {
		margin: 0;
		padding: 0;
		list-style: none;
		display: grid;
		gap: 4px;
	}
	.paper {
		display: grid;
		gap: 2px;
		width: 100%;
		padding: 8px 10px;
		border: 1px solid var(--rule);
		border-radius: var(--radius);
		background: none;
		text-align: left;
		color: var(--ink);
	}
	.paper:hover:not(:disabled) {
		background: var(--rail);
	}
	.paper strong,
	.card strong {
		font-family: var(--serif);
		font-weight: 600;
		line-height: 1.3;
	}
	small {
		color: var(--muted);
		font-size: var(--step--1);
	}
	/* The two papers side by side. */
	.pair {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
		align-items: center;
		gap: 10px;
	}
	.card {
		display: grid;
		gap: 3px;
		padding: 10px 12px;
		border-radius: 8px;
		background: var(--rail);
	}
	.card.from {
		opacity: 0.75;
		border: 1px dashed var(--rule);
	}
	.card.to {
		border: 1px solid var(--royal);
	}
	.arrow {
		font-size: var(--step-2);
		color: var(--muted);
	}
	.banner {
		padding: 8px 12px;
		border-left: 3px solid var(--highlighter);
		background: color-mix(in srgb, var(--highlighter) 18%, var(--surface));
		font-size: var(--step--1);
	}
	.banner.calm {
		border-left-color: var(--rule);
		background: var(--rail);
	}
	.steps li {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: center;
		gap: 10px;
		padding: 5px 8px;
		border-radius: 6px;
	}
	.steps li.stays {
		background: color-mix(in srgb, var(--highlighter) 14%, var(--surface));
	}
	.steps li.already .name {
		color: var(--muted);
	}
	.name {
		overflow-wrap: anywhere;
	}
	.what {
		color: var(--muted);
		font-size: var(--step--1);
		text-align: right;
	}
	.mark {
		display: grid;
		place-items: center;
		width: 22px;
		height: 22px;
		border-radius: 50%;
	}
	.mark svg {
		width: 14px;
		height: 14px;
		fill: none;
		stroke: currentColor;
		stroke-width: 2.6;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.mark.move {
		background: color-mix(in srgb, var(--success) 18%, var(--surface));
		color: var(--success);
	}
	.mark.already {
		background: var(--rail);
		color: var(--faint);
	}
	.mark.stays {
		background: color-mix(in srgb, var(--highlighter) 45%, var(--surface));
		color: var(--on-highlighter);
	}
	.link {
		justify-self: start;
		padding: 0;
		border: none;
		background: none;
		color: var(--royal);
		font-size: var(--step--1);
		text-decoration: underline;
	}
	.link:hover:not(:disabled) {
		background: none;
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
	@media (max-width: 560px) {
		.pair {
			grid-template-columns: minmax(0, 1fr);
		}
		.arrow {
			justify-self: center;
			transform: rotate(90deg);
		}
		.steps li {
			grid-template-columns: auto minmax(0, 1fr);
		}
		.what {
			grid-column: 2;
			text-align: left;
		}
	}
</style>
