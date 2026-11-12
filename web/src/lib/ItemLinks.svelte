<script lang="ts">
	import { mdiCodeBraces, mdiDatabaseOutline, mdiLinkVariant } from '@mdi/js';
	import Icon from '#lib/Icon.svelte';
	import { addLink, errorMessage, removeLink } from '#lib/api/client.ts';
	import type { ItemLink, LinkKind } from '#lib/api/generated/types.gen.ts';

	/** Where a paper's code, data and more are, in one line; those who may
	 * change the paper add and remove them. */
	let {
		item,
		links,
		writable,
		onchange
	}: { item: string; links: ItemLink[]; writable: boolean; onchange: () => void } = $props();

	const KINDS: { kind: LinkKind; name: string; icon: string }[] = [
		{ kind: 'code', name: 'Code', icon: mdiCodeBraces },
		{ kind: 'data', name: 'Data', icon: mdiDatabaseOutline },
		{ kind: 'other', name: 'Other', icon: mdiLinkVariant }
	];
	const ICON = Object.fromEntries(KINDS.map((k) => [k.kind, k.icon]));

	let adding = $state(false);
	let url = $state('');
	let kind = $state<LinkKind>('code');
	let label = $state('');
	let error = $state('');

	/** The site and its path, short: "github.com/ada/qubits". */
	function shown(link: ItemLink): string {
		if (link.label) return link.label;
		try {
			const address = new URL(link.url);
			const path = address.pathname.replace(/\/$/, '');
			return `${address.host.replace(/^www\./, '')}${path}`;
		} catch {
			return link.url;
		}
	}

	/** What the address says it is: a repository is code. */
	function guess(address: string): LinkKind {
		if (/github\.com|gitlab\.|bitbucket\.org|codeocean\.com|softwareheritage\.org/i.test(address))
			return 'code';
		if (
			/zenodo\.org|10\.5281\/|figshare\.com|10\.6084\/|datadryad\.org|10\.5061\/|osf\.io|dataverse|huggingface\.co\/datasets|kaggle\.com/i.test(
				address
			)
		)
			return 'data';
		return kind;
	}

	async function add(event: SubmitEvent) {
		event.preventDefault();
		error = '';
		let address = url.trim();
		if (address && !/^https?:\/\//i.test(address)) address = `https://${address}`;
		const { error: failure } = await addLink({
			path: { item_id: item },
			body: { url: address, kind, label: label.trim() || null }
		});
		if (failure) {
			error = errorMessage(failure);
			return;
		}
		adding = false;
		url = label = '';
		onchange();
	}

	async function remove(link: ItemLink) {
		const { error: failure } = await removeLink({
			path: { item_id: item },
			query: { url: link.url }
		});
		if (failure) error = errorMessage(failure);
		onchange();
	}
</script>

{#if links.length || writable}
	<div class="links">
		{#each links as link (link.url)}
			<span class="link">
				<a href={link.url} target="_blank" rel="noreferrer" title={link.url}>
					<Icon path={ICON[link.kind ?? 'other']} size={14} label={link.kind ?? 'other'} />
					<span>{shown(link)}</span>
				</a>
				{#if writable}
					<button
						class="remove"
						onclick={() => remove(link)}
						aria-label="Remove the link to {shown(link)}">✕</button
					>
				{/if}
			</span>
		{/each}
		{#if writable && !adding}
			<button class="new" onclick={() => (adding = true)}>+ Code or data</button>
		{/if}
	</div>
	{#if adding}
		<form class="add" onsubmit={add}>
			<input
				bind:value={url}
				oninput={() => (kind = guess(url))}
				placeholder="https://github.com/… or a dataset's DOI link"
				aria-label="Address"
				required
			/>
			<select bind:value={kind} aria-label="Kind">
				{#each KINDS as option (option.kind)}<option value={option.kind}>{option.name}</option
					>{/each}
			</select>
			<input bind:value={label} placeholder="Name (optional)" aria-label="Name" />
			<button class="primary">Add link</button>
			<button type="button" onclick={() => (adding = false)}>Cancel</button>
		</form>
	{/if}
	{#if error}<p class="error">{error}</p>{/if}
{/if}

<style>
	.links {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px 8px;
		margin-top: 8px;
		font-size: var(--step--1);
	}
	.link {
		display: inline-flex;
		align-items: center;
		max-width: 100%;
		border: 1px solid var(--rule);
		border-radius: 999px;
	}
	.link:hover {
		border-color: var(--royal);
	}
	.link a {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
		padding: 2px 10px;
		color: var(--ink);
		text-decoration: none;
	}
	.link a span {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.remove {
		margin-left: -6px;
		padding: 2px 8px 2px 2px;
		border: none;
		background: none;
		color: var(--muted);
		line-height: 1;
	}
	.remove:hover {
		color: var(--danger, #c0392b);
	}
	.new {
		padding: 2px 10px;
		border: 1px dashed var(--rule);
		border-radius: 999px;
		background: none;
		color: var(--royal);
	}
	.add {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-top: 8px;
	}
	.add input:first-child {
		flex: 1 1 260px;
	}
	.add input,
	.add select {
		width: auto;
	}
	.error {
		margin: 4px 0 0;
	}
</style>
