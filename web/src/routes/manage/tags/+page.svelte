<script lang="ts">
	import { resolve } from '$app/paths';
	import { deleteTag, errorMessage, removeKeywords } from '#lib/api/client.ts';
	import { notify } from '#lib/toasts.svelte.ts';
	import IconButton from '#lib/IconButton.svelte';
	import SharedIcon from '#lib/SharedIcon.svelte';
	import {
		isShared,
		libraryById,
		libraryName,
		loadOrganize,
		organize,
		type Tag
	} from '#lib/organize.svelte.ts';
	import TagDialog from '#lib/TagDialog.svelte';
	import { formatDateTime } from '#lib/dates.svelte.ts';
	import { ago } from '#lib/format.ts';

	type Sort = 'name' | 'count' | 'last_used' | 'created_at';

	let dialog = $state<TagDialog>();
	let loaded = $state(false);
	let filter = $state('');
	let sort = $state<Sort>('name');
	let descending = $state(false);
	let selected = $state<string[]>([]);
	let error = $state('');

	$effect(() => {
		loadOrganize().then(() => (loaded = true));
	});

	const writable = (tag: Tag) => libraryById(tag.library_id)?.writable ?? false;

	/** Only the papers' keywords (from their details on import: arXiv
	 * categories, a publisher's subjects), put on by no one: hidden unless
	 * asked for. */
	const keyword = (tag: Tag) =>
		tag.count > 0 && !tag.sources.manual && !tag.sources.ai && !!tag.sources.automatic;
	let showKeywords = $state(false);
	const keywordCount = $derived(organize.tags.filter(keyword).length);
	/** Keywords on papers that this person may take off. */
	const removable = $derived(organize.tags.some((tag) => tag.sources.automatic && writable(tag)));

	let owner = $state('');
	const shown = $derived.by(() => {
		const words = filter.trim().toLowerCase();
		const matching = organize.tags.filter(
			(tag) =>
				(showKeywords || !keyword(tag)) &&
				(((!owner || tag.library_id === owner) && !words) ||
					tag.name.toLowerCase().includes(words) ||
					(tag.description ?? '').toLowerCase().includes(words))
		);
		const key = (tag: Tag): string | number =>
			sort === 'name' ? tag.name.toLowerCase() : sort === 'count' ? tag.count : (tag[sort] ?? '');
		const sorted = matching.toSorted((a, b) => {
			const [x, y] = [key(a), key(b)];
			return x < y ? -1 : x > y ? 1 : a.name.localeCompare(b.name);
		});
		return descending ? sorted.reverse() : sorted;
	});

	const used = $derived(organize.tags.reduce((sum, tag) => sum + tag.count, 0));
	const unused = $derived(organize.tags.filter((tag) => tag.count === 0).length);
	const allShownSelected = $derived(
		shown.some(writable) && shown.filter(writable).every((tag) => selected.includes(tag.id))
	);

	function sortBy(column: Sort) {
		if (sort === column) descending = !descending;
		else {
			sort = column;
			// Numbers and dates: the most first.
			descending = column !== 'name';
		}
	}

	function toggle(id: string) {
		selected = selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id];
	}

	function toggleAll() {
		const ids = shown.filter(writable).map((tag) => tag.id);
		selected = allShownSelected
			? selected.filter((id) => !ids.includes(id))
			: [...new Set([...selected, ...ids])];
	}

	async function remove(tags: Tag[]) {
		const names = tags.length === 1 ? `the tag “${tags[0].name}”` : `${tags.length} tags`;
		const items = tags.reduce((sum, tag) => sum + tag.count, 0);
		const note = items ? ` It is removed from ${items} ${items === 1 ? 'item' : 'items'}.` : '';
		if (!confirm(`Delete ${names}?${note} The items stay.`)) return;
		error = '';
		for (const tag of tags) {
			const result = await deleteTag({ path: { tag_id: tag.id } });
			if (result.error) error = errorMessage(result.error);
		}
		selected = selected.filter((id) => !tags.some((tag) => tag.id === id));
		await loadOrganize();
	}

	async function removeAllKeywords() {
		if (
			!confirm(
				'Take the keywords off every paper? They came with the papers’ details on import (arXiv categories, publishers’ subjects, authors’ keywords), not from anyone here. Tags put on by hand stay, also where they were keywords before.'
			)
		)
			return;
		const { data, error: failure } = await removeKeywords();
		if (!data) {
			error = errorMessage(failure);
			return;
		}
		notify({
			kind: 'success',
			title: 'Keywords removed',
			text: `Taken off papers ${data.links} ${data.links === 1 ? 'time' : 'times'}; ${data.tags} no longer used.`
		});
		await loadOrganize();
	}

	function sources(tag: Tag): string {
		const parts = [
			['by hand', tag.sources.manual],
			['as keyword', tag.sources.automatic],
			['by AI', tag.sources.ai]
		] as const;
		const given = parts.filter(([, n]) => n);
		if (given.length <= 1) return given.length ? given[0][0] : '';
		return given.map(([label, n]) => `${n} ${label}`).join(', ');
	}
</script>

<svelte:head><title>Tags · paperus</title></svelte:head>

<header class="head">
	<div>
		<h1>Tags</h1>
		{#if organize.tags.length}
			<p class="muted">
				{organize.tags.length}
				{organize.tags.length === 1 ? 'tag' : 'tags'} on {used}
				{used === 1 ? 'item' : 'items'}{unused ? `; ${unused} not used` : ''}{keywordCount &&
				!showKeywords
					? `; ${keywordCount} keywords, not shown`
					: ''}.
			</p>
		{/if}
	</div>
	<button onclick={() => dialog?.open()}>New tag</button>
</header>

{#if loaded && organize.tags.length === 0}
	<p class="muted">
		No tags yet. Tag items on their pages, or create tags here to have them ready.
	</p>
{:else if organize.tags.length}
	<div class="tools">
		<input
			type="search"
			bind:value={filter}
			placeholder="Filter by name or description"
			aria-label="Filter tags"
		/>
		{#if organize.libraries.length > 1}
			<select bind:value={owner} aria-label="Owner">
				<option value="">All owners</option>
				{#each organize.libraries as library (library.id)}
					<option value={library.id}>{libraryName(library.id)}</option>
				{/each}
			</select>
		{/if}

		{#if keywordCount}
			<label class="show-keywords">
				<input type="checkbox" bind:checked={showKeywords} />
				Show keywords ({keywordCount})
			</label>
		{/if}
		{#if removable}
			<button onclick={removeAllKeywords}>Remove all keywords</button>
		{/if}

		{#if selected.length}
			<div class="bulk">
				<span>{selected.length} selected</span>
				<button
					class="danger"
					onclick={() => remove(organize.tags.filter((tag) => selected.includes(tag.id)))}
					>Delete</button
				>
				<button onclick={() => (selected = [])}>Clear</button>
			</div>
		{/if}
	</div>
	{#if error}<p class="error">{error}</p>{/if}

	<table>
		<thead>
			<tr>
				<th class="check">
					<input
						type="checkbox"
						checked={allShownSelected}
						onchange={toggleAll}
						aria-label="Select all shown tags"
					/>
				</th>
				{@render header('name', 'Name')}
				{@render header('count', 'Items', 'number')}
				<th class="wide">Tagged</th>
				{@render header('last_used', 'Last used', 'wide')}
				{@render header('created_at', 'Created', 'wide')}
				<th class="actions"><span class="visually-hidden">Actions</span></th>
			</tr>
		</thead>
		<tbody>
			{#each shown as tag (tag.id)}
				<tr class:selected={selected.includes(tag.id)}>
					<td class="check">
						<input
							type="checkbox"
							checked={selected.includes(tag.id)}
							onchange={() => toggle(tag.id)}
							disabled={!writable(tag)}
							aria-label="Select {tag.name}"
						/>
					</td>
					<td class="name">
						<button
							class="chip"
							data-tag-color={tag.color}
							disabled={!writable(tag)}
							onclick={() => dialog?.open(tag)}
						>
							{tag.name}
						</button>
						{#if isShared(tag.library_id)}<SharedIcon size={15} owner={tag.library_id} />{/if}
						{#if tag.description}<p>{tag.description}</p>{/if}
					</td>
					<td class="number">
						{#if tag.count}<a href="{resolve('/')}?tag={tag.id}" title="Papers tagged {tag.name}"
								>{tag.count}</a
							>{:else}0{/if}
					</td>
					<td class="wide muted">{sources(tag)}</td>
					<td class="wide muted">
						{#if tag.last_used}
							<time datetime={tag.last_used} title={formatDateTime(tag.last_used)}
								>{ago(tag.last_used)}</time
							>
						{:else}never{/if}
					</td>
					<td class="wide muted">
						<time datetime={tag.created_at} title={formatDateTime(tag.created_at)}
							>{ago(tag.created_at)}</time
						>
					</td>
					<td class="actions">
						{#if writable(tag)}
							<div class="row-actions">
								<IconButton icon="edit" label="Edit {tag.name}" onclick={() => dialog?.open(tag)} />
								<IconButton icon="delete" label="Delete {tag.name}" onclick={() => remove([tag])} />
							</div>
						{/if}
					</td>
				</tr>
			{:else}
				<tr
					><td colspan="7" class="muted none"
						>{filter.trim()
							? `No tag matches “${filter}”.`
							: 'All of these are keywords: tick “Show keywords” to see them.'}</td
					></tr
				>
			{/each}
		</tbody>
	</table>
{/if}

<TagDialog bind:this={dialog} onsaved={loadOrganize} />

{#snippet header(column: Sort, label: string, kind = '')}
	<th
		class={kind}
		aria-sort={sort === column ? (descending ? 'descending' : 'ascending') : undefined}
	>
		<button class="sort" onclick={() => sortBy(column)}>
			{label}
			<span class="arrow" aria-hidden="true">{sort === column ? (descending ? '↓' : '↑') : ''}</span
			>
		</button>
	</th>
{/snippet}

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		gap: 16px;
		margin-bottom: 20px;
	}
	h1 {
		margin: 0 0 4px;
	}
	.head button {
		white-space: nowrap;
	}
	.head p {
		margin: 0;
	}
	.tools {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 12px;
		margin-bottom: 12px;
	}
	.tools input[type='search'] {
		flex: 1;
		min-width: 200px;
		max-width: 360px;
	}
	.bulk {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	table {
		width: 100%;
		border-collapse: collapse;
	}
	th,
	td {
		padding: 8px 10px;
		border-bottom: 1px solid var(--rule);
		text-align: left;
		vertical-align: top;
	}
	th {
		font-size: var(--step--1);
		font-weight: 600;
		color: var(--muted);
		white-space: nowrap;
	}
	td {
		font-size: 0.95em;
	}
	tr.selected td {
		background: var(--rail);
	}
	.check {
		width: 32px;
		padding-right: 0;
	}
	.check input {
		width: auto;
		margin-top: 4px;
	}
	.number {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	th.number .sort {
		margin-left: auto;
	}
	.actions {
		width: 76px;
		padding: 2px 0;
	}
	.row-actions {
		display: flex;
		justify-content: flex-end;
	}
	.sort {
		display: inline-flex;
		gap: 4px;
		padding: 0;
		border: none;
		background: none;
		color: inherit;
		font: inherit;
	}
	.sort:hover:not(:disabled) {
		color: var(--ink);
		background: none;
	}
	.arrow {
		display: inline-block;
		width: 1ch;
	}
	.name :global(.shared) {
		margin-left: 6px;
		vertical-align: middle;
	}
	.name p {
		margin: 4px 0 0;
		max-width: 60ch;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.chip {
		padding: 2px 10px;
		border: none;
		border-radius: 999px;
		background: var(--tag-bg, var(--rail));
		color: var(--tag-ink, var(--ink));
		font-size: 0.95em;
		text-align: left;
	}
	.chip:disabled {
		cursor: default;
		opacity: 1;
	}
	.chip:hover:not(:disabled) {
		background: var(--tag-bg, var(--rail));
		box-shadow: 0 0 0 2px var(--tag-ink, var(--rule));
	}
	.none {
		padding: 16px 10px;
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
	}
	/* Phones: name, count and actions only. */
	@media (max-width: 720px) {
		.wide {
			display: none;
		}
	}
	.show-keywords {
		display: flex;
		align-items: center;
		gap: 6px;
		white-space: nowrap;
	}
	.show-keywords input {
		width: auto;
		flex: none;
		margin: 0;
	}
</style>
