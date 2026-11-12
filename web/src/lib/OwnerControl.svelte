<script lang="ts">
	import { mdiAccountGroupOutline, mdiChevronDown } from '@mdi/js';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import Icon from '#lib/Icon.svelte';
	import { fromAddress, toAddress } from '#lib/libraryFilter.ts';
	import { libraryName, organize } from '#lib/organize.svelte.ts';

	/** Whose papers the library lists: all, only one's own, or a group's.
	 * The filter's "Owned by" rule, at hand (several owners chosen in the
	 * filter: "Several"). */
	const filter = $derived(fromAddress(page.url.searchParams));
	const mine = $derived(organize.libraries.find((library) => library.kind === 'personal'));
	const groups = $derived(organize.libraries.filter((library) => library.kind !== 'personal'));
	const owners = $derived(filter.rules.owners ?? []);
	const chosen = $derived(owners.length === 0 ? '' : owners.length === 1 ? owners[0] : 'several');

	function choose(value: string) {
		const rules = { ...filter.rules, owners: value ? [value] : [] };
		const search = toAddress({ ...filter, rules }, page.url.searchParams).toString();
		goto(search ? `?${search}` : page.url.pathname, { replace: true, reset: false });
	}
</script>

{#if mine && groups.length}
	<span class="owner" class:active={chosen !== ''}>
		<Icon path={mdiAccountGroupOutline} size={17} />
		<select
			aria-label="Whose papers"
			value={chosen}
			onchange={(event) => choose(event.currentTarget.value)}
		>
			<option value="">All</option>
			<option value={mine.id}>Only mine</option>
			{#each groups as group (group.id)}
				<option value={group.id}>{libraryName(group.id)}</option>
			{/each}
			{#if chosen === 'several'}<option value="several" disabled>Several</option>{/if}
		</select>
		<span class="chevron"><Icon path={mdiChevronDown} size={16} /></span>
	</span>
{/if}

<style>
	/* A pill, as Sort and Filter beside it; its colour when it filters. */
	.owner {
		position: relative;
		display: inline-flex;
		align-items: center;
		padding-left: 9px;
		border: 1px solid var(--rule);
		border-radius: 999px;
		background: var(--surface);
		color: var(--muted);
	}
	.owner:focus-within {
		border-color: var(--focus);
	}
	.owner.active {
		border-color: var(--royal);
		color: var(--royal);
	}
	select {
		width: auto;
		max-width: 14em;
		padding: 3px 26px 3px 6px;
		border: none;
		border-radius: 0;
		background: none;
		color: var(--ink);
		font-weight: 550;
		appearance: none;
		field-sizing: content;
		cursor: pointer;
		text-overflow: ellipsis;
	}
	.owner.active select {
		color: var(--royal);
	}
	select:focus-visible {
		outline: none;
	}
	.chevron {
		position: absolute;
		right: 7px;
		display: inline-flex;
		pointer-events: none;
	}
</style>
