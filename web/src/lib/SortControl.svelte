<script lang="ts">
	import { mdiArrowDown, mdiArrowUp, mdiChevronDown, mdiSort } from '@mdi/js';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import Icon from '#lib/Icon.svelte';
	import {
		defaultOrder,
		orderName,
		SORT_FIELDS,
		sortFromAddress,
		sortToAddress,
		type Sort,
		type SortField
	} from '#lib/librarySort.ts';

	/** How the list is sorted: by what, and which way (a click turns it
	 * round). Kept in the address, like the filter. */
	const sort = $derived(sortFromAddress(page.url.searchParams));
	const turned = $derived<Sort>({ ...sort, order: sort.order === 'asc' ? 'desc' : 'asc' });
	const way = $derived(`${orderName(sort)}; click for ${orderName(turned).toLowerCase()}`);

	function show(next: Sort) {
		goto(`?${sortToAddress(next, page.url.searchParams)}`, { replace: true, reset: false });
	}
</script>

<div class="sort" role="group" aria-label="Sort">
	<span class="field">
		<Icon path={mdiSort} size={17} />
		<select
			aria-label="Sort by"
			value={sort.field}
			onchange={(event) => {
				const field = event.currentTarget.value as SortField;
				show({ field, order: defaultOrder(field) });
			}}
		>
			{#each SORT_FIELDS as option (option.value)}
				<option value={option.value}>{option.label}</option>
			{/each}
		</select>
		<span class="chevron"><Icon path={mdiChevronDown} size={16} /></span>
	</span>
	<button class="way" aria-label={way} title={way} onclick={() => show(turned)}>
		<Icon path={sort.order === 'asc' ? mdiArrowUp : mdiArrowDown} size={16} />
	</button>
</div>

<style>
	/* One pill, as the Filter button beside it: what, then which way. */
	.sort {
		display: inline-flex;
		align-items: stretch;
		border: 1px solid var(--rule);
		border-radius: 999px;
		background: var(--surface);
		color: var(--ink);
		font-weight: 550;
	}
	.sort:focus-within {
		border-color: var(--focus);
	}
	.field {
		position: relative;
		display: inline-flex;
		align-items: center;
		padding-left: 9px;
		color: var(--muted);
	}
	select {
		width: auto;
		padding: 3px 26px 3px 6px;
		border: none;
		border-radius: 0;
		background: none;
		color: var(--ink);
		font-weight: 550;
		appearance: none;
		/* As wide as the choice (where browsers can), not the longest one. */
		field-sizing: content;
		cursor: pointer;
	}
	select:focus-visible {
		outline: none;
	}
	.chevron {
		position: absolute;
		right: 6px;
		display: inline-flex;
		pointer-events: none;
	}
	.way {
		display: inline-flex;
		align-items: center;
		padding: 3px 10px 3px 8px;
		border: none;
		border-left: 1px solid var(--rule);
		border-radius: 0 999px 999px 0;
		background: none;
	}
	.way:hover {
		background: var(--rail);
	}
	.way:focus-visible {
		outline: 2px solid var(--focus);
		outline-offset: -2px;
	}
</style>
