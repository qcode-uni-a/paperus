<script lang="ts">
	import {
		deleteBackup,
		errorMessage,
		listBackups,
		setBackupConfig,
		startBackup
	} from '#lib/api/client.ts';
	import type { BackupConfig, Backups } from '#lib/api/generated/types.gen.ts';
	import { ago, localTime } from '#lib/format.ts';

	let data = $state<Backups | null>(null);
	let config = $state<BackupConfig | null>(null);
	let error = $state('');
	let notice = $state('');
	let withFiles = $state(true);
	let waiting = $state(false);

	async function load() {
		const result = await listBackups();
		if (result.error) error = errorMessage(result.error);
		data = result.data ?? null;
		if (data && !config) config = { ...data.config };
	}

	$effect(() => {
		load();
	});

	// While a backup is being written, look again now and then.
	$effect(() => {
		if (!waiting) return;
		const started = data?.backups[0]?.name;
		const timer = setInterval(async () => {
			await load();
			if (data?.backups[0]?.name !== started) {
				waiting = false;
				notice = 'Backup written.';
			}
		}, 3000);
		return () => clearInterval(timer);
	});

	async function backUpNow() {
		error = notice = '';
		const result = await startBackup({ body: { with_files: withFiles } });
		if (result.error) {
			error = errorMessage(result.error);
			return;
		}
		waiting = true;
		notice = 'Backing up… (the worker writes it; this page updates when it is done)';
	}

	async function saveConfig() {
		if (!config) return;
		error = '';
		const result = await setBackupConfig({ body: config });
		if (result.error) error = errorMessage(result.error);
		else notice = 'Schedule saved.';
	}

	async function remove(name: string) {
		if (!confirm(`Delete the backup ${name}?`)) return;
		const result = await deleteBackup({ path: { name } });
		if (result.error) error = errorMessage(result.error);
		await load();
	}

	function size(bytes: number): string {
		if (bytes < 1024 ** 2) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
		if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
		return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
	}

	const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
</script>

<svelte:head><title>Backups · paperus</title></svelte:head>

<h1>Backups</h1>
<p class="muted lead">
	The database (papers, tags, collections, groups, search data) and, if chosen, the files. Each
	backup copies only files that are new.
</p>

{#if error}<p class="error">{error}</p>{/if}
{#if notice}<p class="notice" aria-live="polite">{notice}</p>{/if}

<section class="card">
	<h2>Back up now</h2>
	<label class="check"
		><input type="checkbox" bind:checked={withFiles} /> With files (PDFs and other uploads)</label
	>
	<div><button class="primary" onclick={backUpNow} disabled={waiting}>Back up now</button></div>
</section>

{#if config}
	<section class="card">
		<h2>Schedule</h2>
		<div class="grid">
			<label
				>How often
				<select bind:value={config.schedule}>
					<option value="off">Off</option>
					<option value="daily">Every day</option>
					<option value="weekly">Every Monday</option>
				</select>
			</label>
			<label
				>At
				<select bind:value={config.hour} disabled={config.schedule === 'off'}>
					{#each HOURS as hour (hour)}<option value={hour}>{localTime(hour)}</option>{/each}
				</select>
			</label>
			<label
				>Keep
				<select bind:value={config.keep}>
					{#each [3, 7, 14, 30, 60] as keep (keep)}<option value={keep}>the newest {keep}</option
						>{/each}
				</select>
			</label>
		</div>
		<label class="check"
			><input
				type="checkbox"
				bind:checked={config.with_files}
				disabled={config.schedule === 'off'}
			/>
			With files</label
		>
		<div><button onclick={saveConfig}>Save schedule</button></div>
	</section>
{/if}

<section>
	<h2>Backups</h2>
	{#if data}
		<p class="muted">
			In <code>{data.path}</code>{data.files_size
				? `; files for all backups together: ${size(data.files_size)}`
				: ''}.
		</p>
		{#if data.backups.length === 0}
			<p class="muted">None yet.</p>
		{:else}
			<table>
				<thead>
					<tr>
						<th>When</th>
						<th class="wide">Contents</th>
						<th class="number">Size</th>
						<th class="wide">paperus</th>
						<th><span class="visually-hidden">Actions</span></th>
					</tr>
				</thead>
				<tbody>
					{#each data.backups as backup (backup.name)}
						<tr>
							<td>
								<strong>{new Date(backup.created_at).toLocaleString()}</strong>
								<small>{ago(backup.created_at)}</small>
							</td>
							<td class="wide"
								>{backup.items} papers{backup.with_files
									? `, ${backup.files} files`
									: ', database only'}</td
							>
							<td class="number">{size(backup.size)}</td>
							<td class="wide muted">{backup.paperus_version}</td>
							<td class="actions">
								<button class="link danger" onclick={() => remove(backup.name)}>Delete</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	{/if}
</section>

<section class="restore">
	<h2>Restoring</h2>
	<p>
		Restoring replaces everything, so it runs on the server while paperus is stopped, not here. On
		the server, in the folder with <code>compose.yaml</code>:
	</p>
	<pre><code
			>docker compose stop server worker
docker compose run --rm server paperus backup list
docker compose run --rm server paperus backup restore NAME --replace
docker compose up -d</code
		></pre>
	<p>
		Moving to a new server, or starting over after losing the old one? Start paperus there with an
		empty database and copy the backup's folder (and, for files, the <code>files</code> folder next
		to it) into its backups folder. On first start, the welcome page offers
		<strong>Restore from a backup</strong>, checks which files are there and restores it: no
		commands needed.
	</p>
	<p class="muted">
		A backup from an older paperus is brought up to date while restoring; one from a newer paperus
		needs that version first.
	</p>
</section>

<style>
	h1 {
		margin: 0 0 4px;
	}
	.lead {
		margin: 0 0 20px;
		max-width: 65ch;
	}
	section {
		margin-bottom: 24px;
	}
	section.card {
		display: grid;
		gap: 12px;
		max-width: 620px;
	}
	h2 {
		margin: 0 0 4px;
		font-size: var(--step-1);
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
		gap: 12px;
	}
	label {
		display: grid;
		gap: 6px;
		font-weight: 600;
	}
	label select {
		font-weight: 400;
	}
	label.check {
		display: flex;
		align-items: center;
		gap: 8px;
		font-weight: 400;
	}
	label.check input {
		width: auto;
	}
	.notice {
		padding: 8px 12px;
		border-left: 3px solid var(--success);
		background: var(--rail);
	}
	table {
		width: 100%;
		max-width: 900px;
		border-collapse: collapse;
	}
	th,
	td {
		padding: 8px 10px;
		border-bottom: 1px solid var(--rule);
		text-align: left;
	}
	th {
		font-size: var(--step--1);
		color: var(--muted);
		font-weight: 600;
	}
	td small {
		display: block;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.number {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.actions {
		text-align: right;
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
	.restore {
		max-width: 720px;
	}
	.restore p {
		margin: 0 0 10px;
	}
	pre {
		margin: 0 0 10px;
		padding: 12px 14px;
		overflow-x: auto;
		border-radius: 8px;
		background: var(--rail);
		font-size: 0.85em;
	}
	code {
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
		font-size: 0.92em;
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
	}
	@media (max-width: 720px) {
		.wide {
			display: none;
		}
	}
</style>
