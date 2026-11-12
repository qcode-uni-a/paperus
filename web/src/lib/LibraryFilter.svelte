<script lang="ts">
	import { mdiFilterVariant } from '@mdi/js';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { untrack, type Snippet } from 'svelte';
	import type { Rules } from '#lib/api/generated/types.gen.ts';
	import CollectionDialog from '#lib/CollectionDialog.svelte';
	import Icon from '#lib/Icon.svelte';
	import { fromAddress, isEmpty, toAddress, type Filter } from '#lib/libraryFilter.ts';
	import { describeRules } from '#lib/organize.svelte.ts';
	import RulesEditor from '#lib/RulesEditor.svelte';
	import OwnerControl from '#lib/OwnerControl.svelte';
	import SortControl from '#lib/SortControl.svelte';
	import { writtenName } from '#lib/names.svelte.ts';

	/** The library's filter: a button opening the rules of smart collections
	 * (tags and keywords, types, dates, owners, when added), and what is
	 * filtered by, in words. The filter lives in the address. */

	/** ``count``: the line's left side (how many papers). */
	let { count }: { count: Snippet } = $props();

	const filter = $derived(fromAddress(page.url.searchParams));
	let open = $state(false);
	let draft = $state<Rules>({});
	let dialog = $state<CollectionDialog>();

	const address = (f: Filter) => toAddress(f, page.url.searchParams).toString();

	function show(f: Filter) {
		const search = address(f);
		goto(search ? `?${search}` : page.url.pathname, { replace: true, reset: false });
	}

	function toggle() {
		if (!open) draft = structuredClone($state.snapshot(filter.rules));
		open = !open;
	}

	// The panel's changes go to the address as they are made…
	$effect(() => {
		if (!open) return;
		const rules = $state.snapshot(draft);
		// Only the panel's changes count here, not the address's.
		untrack(() => {
			const wanted = { rules, author: filter.author };
			if (address(wanted) !== address(filter)) show(wanted);
		});
	});
	// …and changes elsewhere (Clear, a tag clicked) to the panel.
	$effect(() => {
		const current = filter;
		untrack(() => {
			if (open && address(current) !== address({ rules: draft, author: current.author })) {
				draft = structuredClone($state.snapshot(current.rules));
			}
		});
	});

	const summary = $derived.by(() => {
		const rules = isEmpty({ rules: filter.rules, author: '' }) ? '' : describeRules(filter.rules);
		const by = filter.author ? `by ${writtenName(filter.author)}` : '';
		if (!by) return rules;
		// "by Benito, M." ends with its own full stop.
		const end = by.endsWith('.') ? '' : '.';
		return rules ? `${rules.slice(0, -1)}, ${by}${end}` : `Papers ${by}${end}`;
	});
</script>

<div class="filter">
	<div class="head">
		{@render count()}
		<div class="tools">
			<span class="sorting"><OwnerControl /><SortControl /></span>
			<button class="toggle" class:active={!isEmpty(filter)} aria-expanded={open} onclick={toggle}
				><Icon path={mdiFilterVariant} size={18} />Filter</button
			>
		</div>
	</div>
	{#if !isEmpty(filter)}
		<div class="row">
			<p class="summary">{summary}</p>
			<button class="link" onclick={() => show({ rules: {}, author: '' })}>Clear filter</button>
			<button
				class="link"
				title="A collection that always holds the papers matching these rules"
				onclick={() => dialog?.open(undefined, true, filter.rules)}
				disabled={!!filter.author}>Save as smart collection</button
			>
		</div>
	{/if}
	{#if open}
		<div class="panel">
			<RulesEditor bind:rules={draft} library="" />
			{#if filter.author}
				<p class="author">
					By {writtenName(filter.author)}
					<button
						class="link"
						onclick={() => show({ rules: filter.rules, author: '' })}
						aria-label="Remove the author">×</button
					>
				</p>
			{/if}
		</div>
	{/if}
</div>

<CollectionDialog bind:this={dialog} />

<style>
	.filter {
		display: grid;
		gap: 10px;
	}
	/* Filter beside the number; on a narrow screen whose papers and the
	   order below, on a line of their own. */
	.head {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: center;
		gap: 10px 12px;
	}
	.tools,
	.sorting {
		display: flex;
		gap: 8px;
	}
	.tools {
		margin-left: auto;
	}
	@media (max-width: 560px) {
		.tools {
			display: contents;
		}
		.sorting {
			order: 1;
			margin-left: auto;
		}
	}
	.row {
		gap: 6px 14px;
	}
	.toggle {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 3px 12px 3px 9px;
	}
	.toggle.active {
		border-color: var(--royal);
		color: var(--royal);
	}
	.summary {
		margin: 0;
		color: var(--ink);
	}
	.link {
		padding: 0;
		border: none;
		background: none;
		color: var(--royal);
		font-size: var(--step--1);
	}
	.link:hover:not(:disabled) {
		text-decoration: underline;
	}
	.panel {
		display: grid;
		gap: 8px;
		max-width: 720px;
	}
	.author {
		margin: 0;
	}
</style>
