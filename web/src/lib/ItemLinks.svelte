<script lang="ts">
	import {
		mdiCodeBraces,
		mdiCommentCheckOutline,
		mdiDatabaseOutline,
		mdiFileDocumentOutline,
		mdiFileOutline,
		mdiLinkVariant,
		mdiPresentation
	} from '@mdi/js';
	import Icon from '#lib/Icon.svelte';
	import {
		addLink,
		apiHref,
		errorMessage,
		removeLink,
		uploadToItem,
		type FileInfo,
		type FileRole
	} from '#lib/api/client.ts';
	import type { ItemLink, LinkKind } from '#lib/api/generated/types.gen.ts';

	/** A paper's attachments in one line: links to its code, data and more,
	 * and its files besides the paper itself (supplementary material, code,
	 * data, slides, peer review); each says what it is, its name in its
	 * tooltip. Those
	 * who may change the paper add and remove them. */
	let {
		item,
		links,
		files = [],
		writable,
		onchange
	}: {
		item: string;
		links: ItemLink[];
		files?: FileInfo[];
		writable: boolean;
		onchange: () => void;
	} = $props();

	/** What one attaches: a link (code, data, other) or a file in a role. */
	const KINDS: { kind: string; name: string; icon: string; link?: LinkKind; role?: FileRole }[] = [
		{ kind: 'code', name: 'Code', icon: mdiCodeBraces, link: 'code', role: 'code' },
		{ kind: 'data', name: 'Data', icon: mdiDatabaseOutline, link: 'data', role: 'data' },
		{
			kind: 'supplementary',
			name: 'Supplement',
			icon: mdiFileDocumentOutline,
			link: 'other',
			role: 'supplementary'
		},
		{ kind: 'slides', name: 'Slides', icon: mdiPresentation, link: 'other', role: 'slides' },
		{
			kind: 'peer_review',
			name: 'Peer review',
			icon: mdiCommentCheckOutline,
			link: 'peer_review',
			role: 'peer_review'
		},
		{ kind: 'other', name: 'Other', icon: mdiLinkVariant, link: 'other', role: 'other' }
	];
	const BY_KIND = Object.fromEntries(KINDS.map((k) => [k.kind, k]));
	const ROLE_NAMES: Partial<Record<FileRole, string>> = {
		transcript: 'Transcript',
		recording: 'Recording'
	};

	let adding = $state(false);
	let url = $state('');
	let upload = $state<FileList | null>(null);
	let kind = $state('code');
	let label = $state('');
	let error = $state('');
	let busy = $state(false);

	/** The site and its path, short: "github.com/ada/qubits". */
	function address(link: ItemLink): string {
		try {
			const at = new URL(link.url);
			return `${at.host.replace(/^www\./, '')}${at.pathname.replace(/\/$/, '')}`;
		} catch {
			return link.url;
		}
	}
	/** Its name, else its address. */
	function shown(link: ItemLink): string {
		return link.label || address(link);
	}
	/** On the chip: what it is ("Code"); a link of no kind by its name. */
	function chip(link: ItemLink): string {
		const kind = link.kind ?? 'other';
		return kind === 'other' ? shown(link) : BY_KIND[kind].name;
	}
	function fileName(file: FileInfo): string {
		return BY_KIND[file.role]?.name ?? ROLE_NAMES[file.role] ?? file.filename;
	}
	function fileIcon(file: FileInfo): string {
		return BY_KIND[file.role]?.icon ?? mdiFileOutline;
	}

	/** What the address says it is: a repository is code. */
	function guess(at: string): string {
		if (/github\.com|gitlab\.|bitbucket\.org|codeocean\.com|softwareheritage\.org/i.test(at))
			return 'code';
		if (
			/zenodo\.org|10\.5281\/|figshare\.com|10\.6084\/|datadryad\.org|10\.5061\/|osf\.io|dataverse|huggingface\.co\/datasets|kaggle\.com/i.test(
				at
			)
		)
			return 'data';
		return kind;
	}

	async function add(event: SubmitEvent) {
		event.preventDefault();
		error = '';
		busy = true;
		const chosen = BY_KIND[kind];
		const file = upload?.[0];
		if (file) {
			const { error: failure } = await uploadToItem({
				path: { item_id: item },
				body: { upload: file, role: chosen.role ?? 'other' }
			});
			if (failure) error = errorMessage(failure);
		} else {
			let at = url.trim();
			if (at && !/^https?:\/\//i.test(at)) at = `https://${at}`;
			const { error: failure } = await addLink({
				path: { item_id: item },
				body: { url: at, kind: chosen.link ?? 'other', label: label.trim() || null }
			});
			if (failure) error = errorMessage(failure);
		}
		busy = false;
		if (error) return;
		adding = false;
		url = label = '';
		upload = null;
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

{#if links.length || files.length || writable}
	<div class="links">
		{#each links as link (link.url)}
			{@const kindName = BY_KIND[link.kind ?? 'other'].name}
			<span class="link">
				<a
					href={link.url}
					target="_blank"
					rel="noreferrer"
					title="{shown(link)} — {link.url}"
					aria-label="{kindName}: {shown(link)}"
				>
					<Icon path={BY_KIND[link.kind ?? 'other'].icon} size={14} />
					<span>{chip(link)}</span>
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
		{#each files as file (file.id)}
			<span class="link">
				<a
					href={apiHref(`/api/files/${file.id}/content`)}
					target="_blank"
					rel="noreferrer"
					title={file.filename}
					aria-label="{fileName(file)}: {file.filename}"
				>
					<Icon path={fileIcon(file)} size={14} />
					<span>{fileName(file)}</span>
				</a>
			</span>
		{/each}
		{#if writable && !adding}
			<button class="new" onclick={() => (adding = true)}>+ Attachment</button>
		{/if}
	</div>
	{#if adding}
		<form class="add" onsubmit={add}>
			<select bind:value={kind} aria-label="Kind">
				{#each KINDS as option (option.kind)}<option value={option.kind}>{option.name}</option
					>{/each}
			</select>
			{#if !upload?.length}
				<input
					bind:value={url}
					oninput={() => (kind = guess(url))}
					placeholder="https://github.com/… or a dataset's DOI link"
					aria-label="Address"
					required
				/>
				<input bind:value={label} placeholder="Name (optional)" aria-label="Name" />
			{/if}
			<label class="file"
				><input type="file" bind:files={upload} aria-label="Or a file" /><span
					>{upload?.length ? upload[0].name : 'or a file…'}</span
				></label
			>
			<button class="primary" disabled={busy}>{upload?.length ? 'Upload' : 'Add link'}</button>
			<button type="button" onclick={() => ((adding = false), (upload = null))}>Cancel</button>
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
	.add input[aria-label='Address'] {
		flex: 1 1 260px;
	}
	/* "or a file…": a link-like button over the file input. */
	.file {
		position: relative;
		display: inline-flex;
		align-items: center;
		color: var(--royal);
		cursor: pointer;
	}
	.file input {
		position: absolute;
		inset: 0;
		opacity: 0;
		cursor: pointer;
	}
	.add input,
	.add select {
		width: auto;
	}
	.error {
		margin: 4px 0 0;
	}
</style>
