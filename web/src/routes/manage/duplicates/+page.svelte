<script lang="ts">
	import { resolve } from '$app/paths';
	import { tick } from 'svelte';
	import { errorMessage, listDuplicatesEverywhere, markDifferent } from '#lib/api/client.ts';
	import type { DuplicateOut, ItemOut } from '#lib/api/generated/types.gen.ts';
	import { shortAuthors } from '#lib/format.ts';
	import DuplicateReview from '#lib/DuplicateReview.svelte';
	import MergeDialog from '#lib/MergeDialog.svelte';
	import { isShared, libraryName, loadOrganize } from '#lib/organize.svelte.ts';
	import SharedIcon from '#lib/SharedIcon.svelte';

	const REASONS: Record<string, string> = {
		identifier: 'Same DOI or arXiv ID',
		file: 'Same file',
		title: 'Same title'
	};

	let pairs = $state<DuplicateOut[] | null>(null);
	let error = $state('');
	let merged = $state(0);
	/** The pair being merged: its paper to merge, and the one to keep. */
	let active = $state<{ merge: ItemOut; keep: ItemOut } | null>(null);
	let dialog = $state<MergeDialog>();
	let reviewing = $state(false);

	async function load() {
		const { data, error: failure } = await listDuplicatesEverywhere();
		pairs = data ?? [];
		if (failure) error = errorMessage(failure);
	}

	$effect(() => {
		loadOrganize();
		load();
	});

	async function merge(merge: ItemOut, keep: ItemOut) {
		active = { merge, keep };
		// The dialog renders for the paper to merge, then opens on the pair.
		await tick();
		dialog?.open(keep);
	}

	async function different(pair: DuplicateOut) {
		const { error: failure } = await markDifferent({
			body: { a: pair.keep.id, b: pair.merge.id }
		});
		if (failure) error = errorMessage(failure);
		await load();
	}

	function line(item: ItemOut): string {
		const who = [shortAuthors(item.authors), item.year ? `(${item.year})` : '']
			.filter(Boolean)
			.join(' ');
		return [who, item.container_title].filter(Boolean).join('. ');
	}

	function facts(item: ItemOut): string[] {
		return [
			item.identifiers.length
				? item.identifiers.map((i) => `${i.scheme.toUpperCase()} ${i.value}`).join(', ')
				: 'no identifier',
			item.tags.length ? `${item.tags.length} ${item.tags.length === 1 ? 'tag' : 'tags'}` : '',
			item.collection_ids.length
				? `in ${item.collection_ids.length} ${item.collection_ids.length === 1 ? 'collection' : 'collections'}`
				: '',
			libraryName(item.library_id)
		].filter(Boolean);
	}
</script>

<svelte:head><title>Duplicates · paperus</title></svelte:head>

<header class="head">
	<h1>Duplicates</h1>
	<p class="muted">
		Papers that look like the same paper twice: the same DOI or arXiv ID, the same file, or the same
		title. Merging keeps one and moves the other's versions, files, tags and collections to it; the
		merged one goes to the trash, where it can be restored.
	</p>
	{#if pairs?.length}
		<button class="primary review" onclick={() => (reviewing = true)}>
			Review one by one ({pairs.length})
		</button>
	{/if}
</header>

{#if reviewing && pairs}
	<DuplicateReview
		{pairs}
		onclose={async (changed) => {
			reviewing = false;
			if (changed) await load();
		}}
	/>
{/if}

{#if error}<p class="error">{error}</p>{/if}
{#if merged}<p class="saved" role="status">
		{merged}
		{merged === 1 ? 'pair' : 'pairs'} merged.
	</p>{/if}

{#if pairs === null}
	<p class="muted">Looking for duplicates…</p>
{:else if pairs.length === 0}
	<p class="muted">No likely duplicates. Everything looks like it is here once.</p>
{:else}
	<ul class="pairs">
		{#each pairs as pair (pair.keep.id + pair.merge.id)}
			<li>
				<div class="reasons">
					{#each pair.reasons as reason (reason)}<span class="badge"
							>{REASONS[reason] ?? reason}</span
						>{/each}
				</div>
				<div class="cards">
					{#each [pair.keep, pair.merge] as item, index (item.id)}
						{#if index === 1}<span class="arrow" aria-hidden="true">←</span>{/if}
						<article class:recommended={index === 0}>
							<span class="role"
								>{index === 0
									? 'Keep this one'
									: pair.can_merge
										? 'Merged into it, then to the trash'
										: 'The other one'}</span
							>
							<div class="title">
								<a href={resolve('/items/[id]', { id: item.id })}>{item.title}</a>
								{#if isShared(item.library_id)}<SharedIcon owner={item.library_id} size={13} />{/if}
							</div>
							{#if line(item)}<small>{line(item)}</small>{/if}
							<small class="muted">{facts(item).join(' · ')}</small>
						</article>
					{/each}
				</div>
				<p class="why muted">
					{pair.can_merge ? 'Recommended because it ' : 'Cannot merge: '}{pair.why.join(', ')}.
				</p>
				<div class="buttons">
					{#if pair.can_merge}
						<button class="primary" onclick={() => merge(pair.merge, pair.keep)}>Merge…</button>
						<button onclick={() => merge(pair.keep, pair.merge)}>Keep the other one…</button>
					{/if}
					<button class="link" onclick={() => different(pair)}>Not the same paper</button>
				</div>
			</li>
		{/each}
	</ul>
{/if}

{#if active}
	{#key active.merge.id + active.keep.id}
		<MergeDialog
			bind:this={dialog}
			item={active.merge}
			onmerged={async () => {
				merged += 1;
				active = null;
				await load();
			}}
		/>
	{/key}
{/if}

<style>
	.head {
		margin-bottom: 16px;
	}
	h1 {
		margin: 0 0 6px;
	}
	.head p {
		max-width: 70ch;
		margin: 0;
	}
	.pairs {
		margin: 0;
		padding: 0;
		list-style: none;
		display: grid;
		gap: 14px;
	}
	.pairs > li {
		display: grid;
		gap: 10px;
		padding: 14px 0 16px;
		border-bottom: 1px solid var(--rule);
	}
	.reasons {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.cards {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
		align-items: center;
		gap: 10px;
	}
	.arrow {
		color: var(--royal);
		font-size: 1.6em;
		font-weight: 700;
	}
	.review {
		margin-top: 12px;
	}
	@media (max-width: 720px) {
		.cards {
			grid-template-columns: minmax(0, 1fr);
		}
		.arrow {
			justify-self: center;
			transform: rotate(90deg);
		}
	}
	article {
		display: grid;
		gap: 4px;
		align-content: start;
		padding: 10px 12px;
		border: 1px solid var(--rule);
		border-radius: 10px;
		min-width: 0;
	}
	article.recommended {
		border-color: var(--royal);
	}
	.role {
		color: var(--muted);
		font-size: var(--step--1);
		font-weight: 600;
	}
	.recommended .role {
		color: var(--royal);
	}
	article a {
		font-family: var(--serif);
		font-weight: 600;
		color: var(--ink);
		overflow-wrap: anywhere;
	}
	.title {
		display: flex;
		align-items: baseline;
		gap: 6px;
	}
	small {
		overflow-wrap: anywhere;
	}
	.why {
		margin: 0;
		font-size: var(--step--1);
	}
	.buttons {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
	}
	.link {
		border: none;
		background: none;
		color: var(--muted);
	}
	.saved {
		color: var(--success);
	}
</style>
