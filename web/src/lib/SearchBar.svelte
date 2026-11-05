<script lang="ts">
	import { mdiClose, mdiMagnify } from '@mdi/js';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import Icon from '#lib/Icon.svelte';
	import SearchFilters, { type Filters } from '#lib/SearchFilters.svelte';

	/** The search in the top bar, on every page (like Immich). The search
	 * lives in the library's address (?q=…), so Back and links keep it;
	 * typing elsewhere goes to the library with the results. */
	const library = resolve('/');
	const onLibrary = $derived(page.url.pathname === library);
	const params = $derived(onLibrary ? page.url.searchParams : new URLSearchParams());
	const searched = $derived(params.get('q')?.trim() ?? '');
	const mode = $derived((params.get('mode') ?? 'hybrid') as 'hybrid' | 'keyword' | 'meaning');
	const filters = $derived<Filters>({
		words: mode !== 'meaning',
		meaning: mode !== 'keyword',
		types: params.getAll('type')
	});

	let query = $state(untrack(() => searched));
	let field = $state<HTMLInputElement>();

	/** The library address for a search with filters. */
	function searchUrl(q: string, next: Filters): string {
		const search = new URLSearchParams();
		if (q) search.set('q', q);
		if (!next.meaning) search.set('mode', 'keyword');
		else if (!next.words) search.set('mode', 'meaning');
		for (const type of next.types) search.append('type', type);
		const text = search.toString();
		return text ? `${library}?${text}` : library;
	}

	function setFilters(next: Filters) {
		goto(searchUrl(query.trim(), next), { replace: onLibrary, reset: false });
	}

	// Address → field, e.g. after Back or leaving the library.
	$effect(() => {
		const q = searched;
		if (untrack(() => query.trim()) !== q) query = q;
	});

	// Field → address, a moment after the last key. Starting a search adds a
	// history entry (Back returns to where one was); refining it replaces it.
	$effect(() => {
		const q = query.trim();
		const timer = setTimeout(() => {
			if (q === untrack(() => searched)) return;
			if (!q && !untrack(() => onLibrary)) return;
			goto(
				searchUrl(
					q,
					untrack(() => filters)
				),
				{ replace: Boolean(untrack(() => searched)) && Boolean(q), reset: false }
			);
		}, 250);
		return () => clearTimeout(timer);
	});

	function clear() {
		query = '';
		if (onLibrary) goto(searchUrl('', filters), { reset: false });
		field?.focus();
	}
</script>

<svelte:window
	onkeydown={(event) => {
		// "/" jumps to the search, as on many sites (not while typing elsewhere).
		const target = event.target as HTMLElement | null;
		if (event.key !== '/' || target?.closest('input, textarea, select, [contenteditable]')) return;
		event.preventDefault();
		field?.focus();
	}}
/>

<div class="search" role="search">
	<span class="glass"><Icon path={mdiMagnify} size={22} /></span>
	<input
		bind:this={field}
		type="search"
		bind:value={query}
		placeholder="Search by words or meaning"
		aria-label="Search the library"
		onkeydown={(event) => {
			if (event.key === 'Escape') clear();
		}}
	/>
	<div class="tools">
		{#if query}
			<button class="clear" onclick={clear} aria-label="Clear search" title="Clear search">
				<Icon path={mdiClose} />
			</button>
		{/if}
		<SearchFilters {filters} onchange={setFilters} />
	</div>
</div>

<style>
	.search {
		position: relative;
		display: grid;
		width: 100%;
	}
	input {
		grid-area: 1 / 1;
		height: 48px;
		padding: 0 88px 0 52px;
		border: 1px solid transparent;
		border-radius: 999px;
		background: var(--field);
		color: var(--ink);
		font-size: var(--step-0);
	}
	input:hover {
		border-color: var(--rule);
	}
	input:focus {
		background: var(--surface);
		border-color: var(--royal);
		outline: none;
		box-shadow: 0 0 0 3px var(--accent-soft);
	}
	input::-webkit-search-cancel-button {
		display: none;
	}
	.glass {
		grid-area: 1 / 1;
		position: relative;
		z-index: 1;
		align-self: center;
		margin-left: 18px;
		display: flex;
		color: var(--muted);
		pointer-events: none;
	}
	/* In the same grid cell, so the options panel is positioned against the
	   whole search box. */
	.tools {
		grid-area: 1 / 1;
		position: relative;
		z-index: 1;
		justify-self: end;
		align-self: center;
		margin-right: 8px;
		display: flex;
		gap: 2px;
	}
	.clear {
		display: grid;
		place-items: center;
		width: 36px;
		height: 36px;
		padding: 0;
		border: none;
		border-radius: 999px;
		background: none;
		color: var(--muted);
	}
	.clear:hover:not(:disabled) {
		background: var(--accent-soft);
		color: var(--ink);
	}
</style>
