<script lang="ts">
	import { untrack } from 'svelte';
	import {
		apiHref,
		deleteExport,
		errorMessage,
		estimateExport,
		listExports,
		startExport
	} from '#lib/api/client.ts';
	import type { Estimate, ExportOut, Include } from '#lib/api/generated/types.gen.ts';
	import { formatDateTime } from '#lib/dates.svelte.ts';
	import { ago, fileSize } from '#lib/format.ts';
	import { collectionPath, flatTree, libraryName, organize } from '#lib/organize.svelte.ts';
	import { watchExport } from '#lib/processing.svelte.ts';
	import { notify } from '#lib/toasts.svelte.ts';

	/** Settings → Export: everything the person sees, as a SQLite database
	 * and the files, in zips to download (docs/export.md). */
	let { collection = '' }: { collection?: string } = $props();

	// What comes along with the papers; each can be left out. (Authors get
	// a line here once there are author records.)
	const PARTS: { key: keyof Include; label: string; help: string }[] = [
		{ key: 'files', label: 'Files', help: 'the PDFs and other files' },
		{ key: 'notes', label: 'Notes', help: 'with their links to papers' },
		{ key: 'tags', label: 'Tags and keywords', help: '' },
		{ key: 'collections', label: 'Collections', help: 'also smart ones, and which are pinned' },
		{ key: 'references', label: 'Reference lists', help: 'what each paper cites' },
		{
			key: 'annotations',
			label: 'Annotations',
			help: 'your highlights, comments and drawings on the PDFs'
		},
		{
			key: 'authors',
			label: 'Authors as people',
			help: 'who is who (splits, merges, ids) and where they were'
		},
		{ key: 'archived', label: 'Archived papers', help: '' }
	];

	type Format = 'paperus' | 'zotero' | 'jabref' | 'mendeley';
	const FORMATS: { value: Format; label: string; help: string }[] = [
		{
			value: 'paperus',
			label: 'paperus',
			help: 'complete, can be imported back; a SQLite database any tool opens'
		},
		{ value: 'zotero', label: 'Zotero', help: 'Zotero RDF with the files' },
		{ value: 'jabref', label: 'JabRef', help: 'BibTeX with the files' },
		{ value: 'mendeley', label: 'Mendeley (RIS)', help: 'RIS; also EndNote, Citavi' }
	];
	// What a format cannot hold, and why (as the server's export.CANNOT_HOLD).
	const CANNOT: Record<Format, Partial<Record<keyof Include, string>>> = {
		paperus: {},
		zotero: {
			references: 'not in Zotero RDF',
			authors: 'names only in Zotero RDF',
			annotations: 'not yet: download a PDF with them instead'
		},
		jabref: {
			references: 'not in BibTeX',
			authors: 'names only in BibTeX',
			annotations: 'not in BibTeX'
		},
		mendeley: {
			references: 'not in RIS',
			collections: 'RIS has none',
			authors: 'names only in RIS',
			annotations: 'not in RIS'
		}
	};
	let format = $state<Format>('paperus');
	let owners = $state<string[]>([]);
	let include = $state<Include>({
		files: true,
		notes: true,
		tags: true,
		collections: true,
		references: true,
		annotations: true,
		authors: true,
		archived: true
	});
	let trash = $state(false);
	let only = $state(untrack(() => collection));
	let estimate = $state<Estimate | null>(null);
	let exports = $state<ExportOut[]>([]);
	let error = $state('');
	let starting = $state(false);

	// Every owner ticked at first.
	$effect(() => {
		const ids = organize.libraries.map((library) => library.id);
		untrack(() => {
			if (!owners.length) owners = ids;
		});
	});

	const options = $derived({
		format,
		owners: owners.length === organize.libraries.length ? null : owners,
		collection_id: only || null,
		include: Object.fromEntries(
			PARTS.map((part) => [part.key, !!include[part.key] && !CANNOT[format][part.key]])
		) as Include,
		trash
	});

	// The estimate follows the choices (a moment after the last change).
	let estimating: ReturnType<typeof setTimeout> | undefined;
	$effect(() => {
		const body = $state.snapshot(options);
		clearTimeout(estimating);
		if (!owners.length) {
			estimate = null;
			return;
		}
		estimating = setTimeout(async () => {
			const { data } = await estimateExport({ body });
			estimate = data ?? null;
		}, 250);
	});

	let timer: ReturnType<typeof setTimeout> | undefined;
	async function load() {
		const { data } = await listExports();
		exports = data ?? [];
		clearTimeout(timer);
		if (exports.some((e) => e.status === 'waiting' || e.status === 'running'))
			timer = setTimeout(load, 1500);
	}
	$effect(() => {
		load();
		return () => clearTimeout(timer);
	});

	async function start(event: SubmitEvent) {
		event.preventDefault();
		error = '';
		starting = true;
		const { data, error: failure } = await startExport({ body: $state.snapshot(options) });
		starting = false;
		if (!data) {
			error = errorMessage(failure);
			return;
		}
		const zips = estimate && estimate.parts > 1 ? `each of its ${estimate.parts} zips` : 'it';
		notify(
			{
				kind: 'info',
				title: 'Your export is being prepared',
				text: `You get a notification (the bell) when ${zips} is ready to download. You can leave this page meanwhile.`
			},
			12
		);
		watchExport(data.id);
		await load();
	}

	async function remove(record: ExportOut) {
		await deleteExport({ path: { export_id: record.id } });
		await load();
	}

	function count(n: number, one: string, many: string): string {
		return `${n} ${n === 1 ? one : many}`;
	}

	function described(record: ExportOut): string {
		const left = PARTS.filter((part) => !record.options.include?.[part.key]).map((part) =>
			part.label.toLowerCase()
		);
		const what = record.collection_name ? `Collection “${record.collection_name}”` : 'Everything';
		const program = FORMATS.find((f) => f.value === record.options.format);
		return [
			what,
			program && program.value !== 'paperus' ? `for ${program.label}` : '',
			record.options.owners ? `of ${record.options.owners.map(libraryName).join(', ')}` : '',
			left.length ? `without ${left.join(', ')}` : '',
			record.options.trash ? 'with the trash' : ''
		]
			.filter(Boolean)
			.join(' ');
	}
</script>

<p class="muted">
	Take home everything you can see: a SQLite database with your papers, notes, tags and collections
	(open it with any SQLite tool) and a folder of the files, in a zip. Groups' papers come along,
	marked with their group. paperus can import it again. Or a file for Zotero, JabRef or Mendeley,
	with the files beside it.
</p>

<form onsubmit={start}>
	<fieldset>
		<legend>Format</legend>
		{#each FORMATS as option (option.value)}
			<label class="check"
				><input type="radio" bind:group={format} value={option.value} />
				<span>{option.label}{' '}<small>— {option.help}</small></span></label
			>
		{/each}
	</fieldset>
	{#if organize.libraries.length > 1}
		<fieldset>
			<legend>Whose</legend>
			{#each organize.libraries as library (library.id)}
				<label class="check" style:margin-left="{library.path.length * 20}px"
					><input type="checkbox" bind:group={owners} value={library.id} />
					{library.kind === 'personal' ? 'My own papers' : library.name}</label
				>
			{/each}
			{#if !owners.length}<small class="error">Choose at least one.</small>{/if}
		</fieldset>
	{/if}
	<fieldset>
		<legend>What</legend>
		{#each PARTS as part (part.key)}
			{@const cannot = CANNOT[format][part.key]}
			<label class="check" class:off={cannot}
				><input
					type="checkbox"
					checked={!cannot && include[part.key]}
					disabled={!!cannot}
					onchange={(event) => (include[part.key] = event.currentTarget.checked)}
				/>
				<span
					>{part.label}{#if cannot}{' '}<small>— {cannot}</small>{:else if part.help}{' '}<small
							>— {part.help}</small
						>{/if}</span
				></label
			>
		{/each}
		<label class="check"
			><input type="checkbox" bind:checked={trash} /> <span>Also what is in the trash</span></label
		>
	</fieldset>
	<label class="only"
		>Papers
		<select bind:value={only}>
			<option value="">All</option>
			{#each flatTree() as { collection: c } (c.id)}
				<option value={c.id}>Only collection “{collectionPath(c.id)}”</option>
			{/each}
		</select>
	</label>
	<p class="estimate" aria-live="polite">
		{#if estimate}
			{count(estimate.items, 'paper', 'papers')}, {count(
				estimate.notes,
				'note',
				'notes'
			)}{include.files ? `, ${count(estimate.files, 'file', 'files')}` : ''}: about {fileSize(
				estimate.size
			)}{estimate.parts > 1 ? `, in ${estimate.parts} zips of at most 2 GB` : ''}.
		{:else}&nbsp;{/if}
	</p>
	{#if error}<p class="error">{error}</p>{/if}
	<div><button class="primary" disabled={starting || !owners.length}>Export</button></div>
</form>

{#if exports.length}
	<h3>Your exports</h3>
	<ul class="exports">
		{#each exports as record (record.id)}
			<li>
				<div class="head">
					<strong>{described(record)}</strong>
					<small>{ago(record.created_at)}</small>
					{#if record.status !== 'running'}
						<button class="link danger" onclick={() => remove(record)}>Delete</button>
					{/if}
				</div>
				{#if record.status === 'waiting'}
					<small>Waiting to start…</small>
				{:else if record.status === 'running'}
					<progress value={record.done} max={record.total || 1}></progress>
					<small
						>{record.total ? `${record.done} of ${record.total}` : 'Reading the library…'}</small
					>
				{:else if record.status === 'failed'}
					<p class="error">{record.error}</p>
				{:else if record.status === 'expired'}
					<small>Expired: exports can be downloaded for a day.</small>
				{/if}
				<!-- Each zip as soon as it is written. -->
				{#if (record.status === 'running' || record.status === 'done') && record.parts.length}
					{@const numbered = record.parts.length > 1 || record.status === 'running'}
					<ul class="parts">
						{#each record.parts as part (part.part)}
							<li>
								<a
									href={apiHref(`/api/exports/${record.id}/parts/${part.part}`)}
									download={part.name}>Download{numbered ? ` part ${part.part}` : ''}</a
								>
								<small>{part.name}, {fileSize(part.size)}</small>
							</li>
						{/each}
					</ul>
				{/if}
				{#if record.status === 'waiting' || record.status === 'running'}
					<small
						>You get a notification (the bell) as each zip is ready; you can leave this page.</small
					>
				{:else if record.status === 'done' && record.expires_at}
					<small
						>Until {formatDateTime(record.expires_at)}{record.parts.length > 1
							? '. Unpack all zips into one folder.'
							: '.'}</small
					>
				{/if}
			</li>
		{/each}
	</ul>
{/if}

<style>
	p {
		margin: 0 0 12px;
	}
	form {
		display: grid;
		gap: 14px;
	}
	fieldset {
		margin: 0;
		padding: 0;
		border: none;
		display: grid;
		gap: 4px;
	}
	legend {
		padding: 0;
		margin-bottom: 6px;
		font-weight: 600;
	}
	.check {
		display: flex;
		align-items: flex-start;
		gap: 8px;
	}
	.check input {
		width: auto;
		margin-top: 4px;
	}
	.check.off {
		color: var(--muted);
	}
	.only {
		display: grid;
		gap: 6px;
		font-weight: 600;
	}
	.only select {
		font-weight: 400;
	}
	small {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.estimate {
		margin: 0;
		color: var(--muted);
	}
	h3 {
		margin: 22px 0 8px;
		font-size: var(--step-0);
	}
	.exports,
	.parts {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.exports > li {
		display: grid;
		gap: 6px;
		padding: 10px 0;
		border-bottom: 1px solid var(--rule);
	}
	.head {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 4px 10px;
	}
	.head .link {
		margin-left: auto;
	}
	.parts li {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 10px;
		align-items: baseline;
	}
	.link {
		padding: 2px 6px;
		border: none;
		background: none;
		color: var(--royal);
		font-size: var(--step--1);
	}
	.link.danger {
		color: var(--danger);
	}
	progress {
		width: 100%;
	}
	.error {
		margin: 0;
	}
</style>
