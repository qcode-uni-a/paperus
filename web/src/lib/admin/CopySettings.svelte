<script lang="ts">
	import { admin, formatSize } from '#lib/admin/data.svelte.ts';
	import { saveConfig } from '#lib/admin/config.svelte.ts';
	import SectionButtons from '#lib/admin/SectionButtons.svelte';
	import SettingRow from '#lib/admin/SettingRow.svelte';
	import Switch from '#lib/admin/Switch.svelte';
	import { previewTemplate, readableCopy, runJob } from '#lib/api/client.ts';
	import type { ReadableCopy } from '#lib/api/generated/types.gen.ts';
	import { ago, localTime } from '#lib/format.ts';
	import { notify } from '#lib/toasts.svelte.ts';

	const DEFAULT = '{owner}/{first_author}_{journal}_{year}';
	const config = $derived(admin.config);
	let info = $state<ReadableCopy | null>(null);
	let enabled = $state(false);
	let template = $state(DEFAULT);
	let links = $state(false);
	let saving = $state(false);
	let paths = $state<string[]>([]);
	let problem = $state<string | null>(null);
	let input = $state<HTMLInputElement | null>(null);

	async function loadInfo() {
		const { data } = await readableCopy();
		info = data ?? null;
	}
	$effect(() => {
		loadInfo();
		const timer = setInterval(loadInfo, 10000);
		return () => clearInterval(timer);
	});

	function reset() {
		enabled = config?.copy_enabled ?? false;
		template = config?.copy_template ?? DEFAULT;
		links = config?.copy_links ?? false;
	}
	// The page reloads its data every few seconds: start over only when the
	// saved values change (not while someone is typing).
	let seen = '';
	$effect(() => {
		if (!config) return;
		const saved = JSON.stringify([config.copy_enabled, config.copy_template, config.copy_links]);
		if (saved === seen) return;
		seen = saved;
		reset();
	});

	const changed = $derived(
		!!config &&
			(enabled !== (config.copy_enabled ?? false) ||
				template !== (config.copy_template ?? DEFAULT) ||
				links !== (config.copy_links ?? false))
	);

	// A preview of the template with the library's own papers, as one types.
	$effect(() => {
		const wanted = template;
		const timer = setTimeout(async () => {
			const { data } = await previewTemplate({ body: { template: wanted } });
			if (wanted !== template || !data) return;
			paths = data.paths;
			problem = data.error ?? null;
		}, 250);
		return () => clearTimeout(timer);
	});

	function insert(name: string) {
		const at = input?.selectionStart ?? template.length;
		const end = input?.selectionEnd ?? at;
		template = `${template.slice(0, at)}{${name}}${template.slice(end)}`;
		const caret = at + name.length + 2;
		requestAnimationFrame(() => {
			input?.focus();
			input?.setSelectionRange(caret, caret);
		});
	}

	async function save() {
		saving = true;
		const saved = await saveConfig(
			{ copy_enabled: enabled, copy_template: template, copy_links: links },
			'Storage template'
		);
		saving = false;
		if (saved && enabled) {
			notify({ kind: 'info', title: 'Updating the copy', text: 'In the background.' });
		}
	}

	async function run(job: 'copy' | 'copy-remove') {
		if (
			job === 'copy-remove' &&
			!confirm('Delete every file paperus wrote into the copy? The library stays as it is.')
		)
			return;
		await runJob({ path: { job } });
		notify({
			kind: 'info',
			title: job === 'copy' ? 'Updating the copy' : 'Deleting the copy',
			text: 'In the background.'
		});
	}
</script>

<p class="muted intro">
	paperus stores each file once, named by its fingerprint. Here it can also keep a copy of every
	paper’s files under readable names, in folders, for browsing the library on disk or with other
	programs. It is updated every night; only files paperus wrote there are ever changed or removed.
</p>

<SettingRow
	id="copy-on"
	title="Keep a readable copy"
	description={info ? `In ${info.path} on the server.` : undefined}
>
	<Switch id="copy-on" label="Keep a readable copy" bind:checked={enabled} />
</SettingRow>

<div class="template" class:off={!enabled}>
	<label class="title" for="copy-template">Template</label>
	<p class="muted small">
		Folders and file name for each file; <code>/</code> starts a folder. The extension is added.
	</p>
	<input
		id="copy-template"
		class="mono"
		bind:this={input}
		bind:value={template}
		spellcheck="false"
		autocomplete="off"
	/>
	{#if info}
		<div class="variables" aria-label="Variables">
			{#each Object.entries(info.variables) as [name, help] (name)}
				<button type="button" title={help} onclick={() => insert(name)}>{name}</button>
			{/each}
		</div>
	{/if}
	<div class="preview" aria-live="polite">
		{#if problem}
			<p class="bad">{problem}</p>
		{:else if paths.length}
			<span class="label">For example</span>
			<ul>
				{#each paths as path (path)}
					{@const slash = path.lastIndexOf('/')}
					<li>
						{#if slash >= 0}<span class="folder">{path.slice(0, slash + 1)}</span>{/if}<span
							>{path.slice(slash + 1)}</span
						>
					</li>
				{/each}
			</ul>
		{:else}
			<p class="muted">No papers with files yet.</p>
		{/if}
	</div>
</div>

<SettingRow
	id="copy-links"
	title="Hard links instead of copies"
	description={info?.links_possible === false
		? 'Only with files stored on a disk, not with S3.'
		: 'Takes no extra space, if the copy is on the same disk as the files. But the copy’s files are the stored ones: never edit them there.'}
>
	<Switch id="copy-links" label="Hard links instead of copies" bind:checked={links} />
</SettingRow>
<SectionButtons {changed} {saving} onreset={reset} onsave={save} />

{#if info?.report || config?.copy_enabled}
	<div class="status">
		<p>
			{#if info?.report?.error}
				<strong class="bad">The last update failed:</strong> {info.report.error}
			{:else if info?.report}
				<strong>{(info.report.files ?? 0).toLocaleString()} files</strong>, {formatSize(
					info.report.bytes
				)}; updated {ago(info.report.at)}{info.report.written || info.report.removed
					? ` (${info.report.written} written, ${info.report.removed} removed)`
					: ''}.
			{:else}
				Not written yet.
			{/if}
			{#if info?.free_bytes != null}
				<span class="muted">{formatSize(info.free_bytes)} free there.</span>
			{/if}
			{#if config?.copy_enabled}
				<span class="muted">Next update tonight at {localTime(config.night_hour ?? 2, 50)}.</span>
			{/if}
		</p>
		<div class="buttons">
			{#if config?.copy_enabled}<button onclick={() => run('copy')}>Update now</button>{/if}
			{#if info?.report?.files}
				<button class="danger-button" onclick={() => run('copy-remove')}>Delete the copy</button>
			{/if}
		</div>
	</div>
{/if}
<p class="muted small docker">
	With Docker, the copy’s folder is a folder on the host: <code>COPY_LOCATION</code> in
	<code>.env</code>.
</p>

<style>
	.intro {
		margin: 14px 0 4px;
		max-width: 72ch;
	}
	.template {
		display: grid;
		gap: 6px;
		padding: 14px 0;
		border-top: 1px solid var(--rule);
		border-bottom: 1px solid var(--rule);
	}
	.template.off {
		opacity: 0.7;
	}
	.title {
		font-weight: 600;
	}
	.small {
		margin: 0;
		font-size: var(--step--1);
	}
	.mono,
	code,
	.preview ul {
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
	}
	.mono {
		font-size: 0.95em;
	}
	code {
		font-size: 0.9em;
	}
	.variables {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.variables button {
		padding: 3px 10px;
		border: 1px solid var(--rule);
		border-radius: 999px;
		background: var(--surface);
		color: var(--royal);
		font-size: var(--step--1);
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
	}
	.variables button::before {
		content: '{';
		color: var(--muted);
	}
	.variables button::after {
		content: '}';
		color: var(--muted);
	}
	.variables button:hover {
		border-color: var(--royal);
	}
	.preview {
		margin-top: 6px;
		padding: 10px 12px;
		border-radius: 10px;
		background: var(--rail);
	}
	.preview p {
		margin: 0;
	}
	.label {
		display: block;
		margin-bottom: 4px;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.preview ul {
		margin: 0;
		padding: 0;
		list-style: none;
		font-size: 0.85em;
		line-height: 1.7;
	}
	.preview li {
		overflow-wrap: anywhere;
	}
	.folder {
		color: var(--muted);
	}
	.bad {
		color: var(--danger);
	}
	.status {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 10px 16px;
		margin-top: 14px;
	}
	.status p {
		margin: 0;
		flex: 1 1 300px;
	}
	.buttons {
		display: flex;
		gap: 8px;
	}
	.danger-button {
		border-color: var(--danger);
		color: var(--danger);
	}
	.docker {
		margin-top: 12px;
	}
</style>
