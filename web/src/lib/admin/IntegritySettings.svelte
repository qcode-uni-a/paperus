<script lang="ts">
	import { resolve } from '$app/paths';
	import { formatSize } from '#lib/admin/data.svelte.ts';
	import { integrityReport, runJob } from '#lib/api/client.ts';
	import type { Report } from '#lib/api/generated/types.gen.ts';
	import { ago } from '#lib/format.ts';
	import { notify } from '#lib/toasts.svelte.ts';

	let report = $state<Report | null>(null);
	let running = $state(false);
	let alive = true;
	$effect(() => () => (alive = false));

	async function load() {
		const { data } = await integrityReport();
		report = data ?? null;
	}
	$effect(() => {
		load();
	});

	/** Start a check and wait for its report (it runs in the background). */
	async function run(job: 'integrity' | 'integrity-deep' | 'integrity-clean') {
		running = true;
		const before = report?.checked_at;
		await runJob({ path: { job } });
		for (let i = 0; i < 600 && alive; i++) {
			await new Promise((done) => setTimeout(done, 2000));
			await load();
			if (report?.checked_at !== before) break;
		}
		running = false;
		if (!alive || !report) return;
		const bad = report.missing + report.damaged;
		notify({
			kind: bad ? 'warning' : 'success',
			title: bad ? `${bad} files have a problem` : 'All files are in order',
			text: report.removed ? `${report.removed} unused stored contents removed.` : undefined
		});
	}
</script>

<p class="muted intro">
	Compares the library with the storage: whether every file’s contents are there (a quick check,
	also every Sunday night), and with a deep check whether they are unchanged (reads every file,
	takes a while). Stored contents nothing uses any more can be removed.
</p>

{#if report}
	<div class="facts">
		<div>
			<strong>{report.contents.toLocaleString()}</strong><span>stored contents in use</span>
		</div>
		<div class:bad={report.missing}>
			<strong>{report.missing}</strong><span>missing</span>
		</div>
		<div class:bad={report.damaged}>
			<strong>{report.deep ? report.damaged : '–'}</strong><span>changed (deep check)</span>
		</div>
		<div>
			<strong>{report.unused}</strong><span
				>unused{report.unused ? `, ${formatSize(report.unused_bytes)}` : ''}</span
			>
		</div>
	</div>
	<p class="muted small">
		Last {report.deep ? 'deep ' : ''}check {ago(report.checked_at)}{report.removed
			? `; ${report.removed} unused removed`
			: ''}.
	</p>
	{#if report.problems.length}
		<h3>Files with a problem</h3>
		<p class="muted small">
			Restore them from a backup (Administration → Backups), or upload the file again on the paper.
		</p>
		<ul class="problems">
			{#each report.problems as problem (problem.file_id)}
				<li>
					<a href={resolve('/items/[id]', { id: problem.item_id })}>{problem.title}</a>
					<span class="muted">{problem.filename}</span>
				</li>
			{/each}
		</ul>
	{/if}
{:else}
	<p class="muted">No check has run yet.</p>
{/if}

<div class="buttons">
	<button onclick={() => run('integrity')} disabled={running}>
		{running ? 'Checking…' : 'Check now'}
	</button>
	<button onclick={() => run('integrity-deep')} disabled={running}>Check deeply</button>
	{#if report?.unused}
		<button class="danger-button" onclick={() => run('integrity-clean')} disabled={running}
			>Remove {report.unused} unused</button
		>
	{/if}
</div>

<style>
	.intro {
		margin: 14px 0;
	}
	.facts {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
		gap: 10px;
	}
	.facts div {
		display: grid;
		padding: 12px 14px;
		border: 1px solid var(--rule);
		border-radius: 12px;
	}
	.facts strong {
		font-size: var(--step-2);
		font-variant-numeric: tabular-nums;
	}
	.facts span {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.facts .bad {
		border-color: var(--danger);
	}
	.facts .bad strong {
		color: var(--danger);
	}
	.small {
		margin: 8px 0 0;
		font-size: var(--step--1);
	}
	h3 {
		margin: 16px 0 4px;
		font-size: var(--step-0);
	}
	.problems {
		margin: 8px 0 0;
		padding-left: 18px;
	}
	.problems li {
		margin: 2px 0;
	}
	.problems span {
		margin-left: 8px;
		font-size: var(--step--1);
	}
	.buttons {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		padding-top: 16px;
	}
	.danger-button {
		border-color: var(--danger);
		color: var(--danger);
	}
</style>
