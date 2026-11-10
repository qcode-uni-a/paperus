<script lang="ts">
	import { enterSubmits } from '#lib/enterSubmits.ts';
	import { bulk, errorMessage, type Item } from '#lib/api/client.ts';
	import type { BulkIn, BulkOut } from '#lib/api/generated/types.gen.ts';
	import { copyCitations, downloadCitations } from '#lib/citations.ts';
	import { closeOnScroll } from '#lib/dismiss.ts';
	import {
		flatTree,
		libraryName,
		loadOrganize,
		organize,
		writableLibraries,
		type Collection
	} from '#lib/organize.svelte.ts';
	import type { Selection } from '#lib/selection.svelte.ts';

	/** What to do with the papers picked in a list: tag, collect, give to
	 * another owner, star, archive, trash, export. ``items``: the rows
	 * loaded (their tags and stars); ``collection``: the one shown, which
	 * they can leave; ``onchange``: reload the list. */
	let {
		selection,
		items,
		collection,
		onchange
	}: {
		selection: Selection;
		items: Item[];
		collection?: Collection;
		onchange: () => unknown;
	} = $props();

	// The citation export takes the papers in its address: not too many.
	const MOST_TO_EXPORT = 200;

	const id = $props.id();
	const picked = $derived(items.filter((item) => selection.has(item.id)));
	const count = $derived(selection.size);
	const allStarred = $derived(picked.length > 0 && picked.every((item) => item.favourite));
	/** Tags on the picked papers, the most used first (to take off). */
	const theirTags = $derived.by(() => {
		const counts = new Map<string, { id: string; name: string; count: number }>();
		for (const item of picked) {
			for (const tag of item.tags) {
				if (tag.source === 'automatic') continue;
				const seen = counts.get(tag.id) ?? { id: tag.id, name: tag.name, count: 0 };
				seen.count += 1;
				counts.set(tag.id, seen);
			}
		}
		return [...counts.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
	});
	const collections = $derived(
		flatTree().filter(({ collection: c }) => !c.rules && writableIds.has(c.library_id))
	);
	const owners = $derived(writableLibraries());
	const writableIds = $derived(new Set(writableLibraries().map((library) => library.id)));

	let busy = $state(false);
	let message = $state('');
	let skipped = $state<string[]>([]);
	/** Papers just trashed, for Undo. */
	let trashed = $state<string[]>([]);
	let tagName = $state('');
	let findCollection = $state('');
	const foundCollections = $derived(
		findCollection.trim()
			? collections.filter(({ collection: c }) =>
					c.name.toLowerCase().includes(findCollection.trim().toLowerCase())
				)
			: collections
	);

	$effect(() => {
		if (selection.active && !organize.libraries.length) void loadOrganize();
	});
	$effect(() =>
		closeOnScroll(() =>
			document
				.querySelectorAll<HTMLElement>(`[id^="${id}-"]:popover-open`)
				.forEach((menu) => menu.hidePopover())
		)
	);
	// Esc lets go of the selection (unless a menu is open: that closes first).
	$effect(() => {
		if (!selection.active) return;
		const onKey = (event: KeyboardEvent) => {
			if (event.key !== 'Escape' || document.querySelector(':popover-open')) return;
			selection.clear();
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	});
	// A new selection starts without the last action's message.
	$effect(() => {
		if (!selection.active) message = '';
	});

	/** Why papers were skipped, counted: "2 skipped: readers cannot …". */
	function why(result: BulkOut): string[] {
		const reasons = new Map<string, number>();
		for (const skip of result.skipped)
			reasons.set(skip.reason, (reasons.get(skip.reason) ?? 0) + 1);
		return [...reasons].map(([reason, n]) => `${n} skipped: ${reason}.`);
	}

	const papers = (n: number) => `${n.toLocaleString()} ${n === 1 ? 'paper' : 'papers'}`;

	/** Apply; ``done`` says what happened to how many. ``leaves``: the
	 * papers leave the list (it lets go of them). */
	async function run(
		action: BulkIn['action'],
		done: (n: number) => string,
		leaves = false
	): Promise<BulkOut | null> {
		busy = true;
		message = '';
		skipped = [];
		trashed = [];
		const { data, error } = await bulk({ body: { item_ids: [...selection.ids], action } });
		busy = false;
		if (!data) {
			message = errorMessage(error);
			return null;
		}
		message = done(data.done.length);
		skipped = why(data);
		await onchange();
		if (leaves) for (const each of data.done) selection.ids.delete(each);
		selection.keepShown();
		return data;
	}

	async function addTag(event: SubmitEvent) {
		event.preventDefault();
		const name = tagName.trim();
		if (!name) return;
		hide('tag');
		tagName = '';
		await run({ kind: 'tag', name }, (n) => `Tagged ${papers(n)} “${name}”.`);
		await loadOrganize();
	}

	async function trash() {
		const result = await run({ kind: 'trash' }, (n) => `${papers(n)} in the trash.`, true);
		if (result?.done.length) trashed = result.done;
	}

	async function undoTrash() {
		const back = trashed;
		trashed = [];
		const { error } = await bulk({ body: { item_ids: back, action: { kind: 'restore' } } });
		message = error ? errorMessage(error) : `${papers(back.length)} back from the trash.`;
		skipped = [];
		await onchange();
	}

	async function giveTo(libraryId: string) {
		const name = libraryName(libraryId);
		if (
			!confirm(
				`Give ${papers(count)} to ${name}? Who can see and change them follows the new owner.`
			)
		)
			return;
		await run(
			{ kind: 'owner', library_id: libraryId },
			(n) => `${papers(n)} now belong to ${name}.`
		);
	}

	function hide(menu: string) {
		document.getElementById(`${id}-${menu}`)?.hidePopover();
	}

	/** Above its button (the bar sits at the bottom), within the window. */
	function place(event: Event) {
		const menu = event.currentTarget as HTMLElement;
		const button = document.querySelector<HTMLElement>(`[popovertarget="${menu.id}"]`);
		if (!button) return;
		const rect = button.getBoundingClientRect();
		const width = Math.min(300, window.innerWidth - 24);
		menu.style.setProperty('--width', `${width}px`);
		menu.style.setProperty('--bottom', `${window.innerHeight - rect.top + 8}px`);
		menu.style.setProperty(
			'--left',
			`${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`
		);
	}

	const exportable = $derived(count <= MOST_TO_EXPORT);
	let copied = $state(false);
	async function copy() {
		copied = await copyCitations({ items: [...selection.ids] });
		message = copied ? `BibTeX of ${papers(count)} copied.` : '';
	}
</script>

{#if selection.active}
	<!-- Room below the list, so the bar covers none of its rows. -->
	<div class="room"></div>
	<div class="bar" role="toolbar" aria-label="Selected papers">
		<div class="count">
			<button
				class="close"
				onclick={() => selection.clear()}
				aria-label="Clear the selection"
				title="Clear (Esc)">×</button
			>
			<strong>{count.toLocaleString()} selected</strong>
			{#if count < items.length}<button class="link" onclick={() => selection.all()}
					>Select all {items.length.toLocaleString()} shown</button
				>{/if}
		</div>
		<div class="actions">
			<button popovertarget="{id}-tag" disabled={!count || busy}>Tag</button>
			<button popovertarget="{id}-collection" disabled={!count || busy}>Collection</button>
			{#if owners.length > 1}
				<button popovertarget="{id}-owner" disabled={!count || busy}>Owner</button>
			{/if}
			<button
				disabled={!count || busy}
				onclick={() =>
					allStarred
						? run({ kind: 'unstar' }, (n) => `Took the star off ${papers(n)}.`)
						: run({ kind: 'star' }, (n) => `Starred ${papers(n)}.`)}
				>{allStarred ? 'Unstar' : 'Star'}</button
			>
			<button
				disabled={!count || busy}
				onclick={() => run({ kind: 'archive' }, (n) => `${papers(n)} in the archive.`, true)}
				>Archive</button
			>
			<button popovertarget="{id}-export" disabled={!count || busy}>Export</button>
			<button class="danger" disabled={!count || busy} onclick={trash}>Trash</button>
		</div>
		{#if message || skipped.length}
			<p class="result" role="status">
				{message}
				{#each skipped as line (line)}<span class="skipped">{line}</span>{/each}
				{#if trashed.length}<button class="link" onclick={undoTrash}>Undo</button>{/if}
			</p>
		{/if}
	</div>

	<div id="{id}-tag" popover class="menu" onbeforetoggle={place}>
		<form onsubmit={addTag}>
			<label for="{id}-tag-name">Add a tag</label>
			<div class="with-button">
				<input
					id="{id}-tag-name"
					bind:value={tagName}
					list="{id}-tag-names"
					{@attach enterSubmits}
					autocomplete="off"
					maxlength="200"
					placeholder="Tag"
				/>
				<button class="primary" disabled={!tagName.trim()}>Add</button>
			</div>
			<datalist id="{id}-tag-names">
				{#each organize.tags as tag (tag.id)}<option value={tag.name}></option>{/each}
			</datalist>
		</form>
		{#if theirTags.length}
			<p class="heading">Take off</p>
			<div class="chips">
				{#each theirTags as tag (tag.id)}
					<button
						class="chip"
						title="Take “{tag.name}” off the selected papers"
						onclick={() => {
							hide('tag');
							run({ kind: 'untag', tag_id: tag.id }, (n) => `Took “${tag.name}” off ${papers(n)}.`);
						}}>{tag.name} <span aria-hidden="true">×</span></button
					>
				{/each}
			</div>
		{/if}
	</div>

	<div id="{id}-collection" popover class="menu list" onbeforetoggle={place}>
		{#if collection && !collection.rules}
			<button
				onclick={() => {
					hide('collection');
					run(
						{ kind: 'uncollect', collection_id: collection.id },
						(n) => `${papers(n)} taken out of “${collection.name}”.`,
						true
					);
				}}>Take out of “{collection.name}”</button
			>
			<hr />
		{/if}
		<p class="heading">Add to</p>
		{#if collections.length > 8}
			<input
				class="find"
				bind:value={findCollection}
				placeholder="Find a collection"
				aria-label="Find a collection"
			/>
		{/if}
		{#each foundCollections as { collection: target, depth } (target.id)}
			<button
				style:padding-left="{12 + (findCollection.trim() ? 0 : depth * 16)}px"
				onclick={() => {
					hide('collection');
					run(
						{ kind: 'collect', collection_id: target.id },
						(n) => `${papers(n)} added to “${target.name}”.`
					);
				}}>{target.name}</button
			>
		{:else}
			<p class="muted empty">No collections yet.</p>
		{/each}
	</div>

	<div id="{id}-owner" popover class="menu list" onbeforetoggle={place}>
		<p class="heading">Give to</p>
		{#each owners as owner (owner.id)}
			<button
				onclick={() => {
					hide('owner');
					giveTo(owner.id);
				}}>{libraryName(owner.id)}</button
			>
		{/each}
	</div>

	<div id="{id}-export" popover class="menu list" onbeforetoggle={place}>
		{#if exportable}
			<button
				onclick={() => {
					hide('export');
					downloadCitations({ items: [...selection.ids] }, 'bibtex');
				}}>Download BibTeX</button
			>
			<button
				onclick={() => {
					hide('export');
					void copy();
				}}>Copy BibTeX</button
			>
			<button
				onclick={() => {
					hide('export');
					downloadCitations({ items: [...selection.ids] }, 'csl-json');
				}}>Download CSL-JSON</button
			>
		{:else}
			<p class="muted empty">
				At most {MOST_TO_EXPORT} papers at once; a whole collection exports from its page, the library
				under Settings.
			</p>
		{/if}
	</div>
{/if}

<style>
	.room {
		height: 96px;
	}
	.bar {
		position: fixed;
		z-index: 20;
		left: 50%;
		bottom: 16px;
		transform: translateX(-50%);
		width: min(860px, calc(100vw - 32px));
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 8px 16px;
		padding: 10px 12px;
		border: 1px solid var(--rule);
		border-radius: 14px;
		background: var(--surface);
		box-shadow: var(--shadow);
	}
	.count {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.close {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		padding: 0;
		border-radius: 50%;
		font-size: 1.3rem;
		line-height: 1;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.actions button {
		padding: 5px 12px;
	}
	.danger {
		color: var(--danger);
	}
	.link {
		padding: 0;
		border: none;
		background: none;
		color: var(--royal);
		font-weight: 600;
	}
	.result {
		flex-basis: 100%;
		margin: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 4px 10px;
		font-size: var(--step--1);
	}
	.skipped {
		color: var(--danger);
	}
	.menu {
		position: fixed;
		inset: auto auto var(--bottom) var(--left);
		margin: 0;
		padding: 10px;
		width: var(--width);
		max-height: min(60vh, 420px);
		overflow-y: auto;
		border: 1px solid var(--rule);
		border-radius: 10px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	.menu label,
	.heading {
		display: block;
		margin: 0 0 6px;
		font-size: var(--step--1);
		font-weight: 600;
		color: var(--muted);
	}
	.menu.list {
		padding: 6px;
	}
	.menu.list .heading {
		margin: 4px 12px 4px;
	}
	.menu.list button {
		display: block;
		width: 100%;
		text-align: left;
		padding: 8px 12px;
		border: none;
		border-radius: var(--radius);
		background: none;
		color: var(--ink);
	}
	.menu.list button:hover {
		background: var(--rail);
	}
	.menu hr {
		margin: 6px 4px;
		border: none;
		border-top: 1px solid var(--rule);
	}
	.with-button {
		display: flex;
		gap: 6px;
	}
	.with-button input {
		flex: 1;
		min-width: 0;
	}
	.heading {
		margin-top: 12px;
	}
	.find {
		width: calc(100% - 12px);
		margin: 0 6px 6px;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.chip {
		padding: 2px 10px;
		border-radius: 999px;
		font-size: var(--step--1);
	}
	.empty {
		margin: 6px 12px;
		font-size: var(--step--1);
	}
</style>
