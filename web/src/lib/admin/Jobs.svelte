<script lang="ts">
	import { mdiChartLine } from '@mdi/js';
	import { resolve } from '$app/paths';
	import { admin, history, loadAdmin, type Sample } from '#lib/admin/data.svelte.ts';
	import { listImports, runJob } from '#lib/api/client.ts';
	import type { ImportOut } from '#lib/api/generated/types.gen.ts';
	import { notify } from '#lib/toasts.svelte.ts';
	import Icon from '#lib/Icon.svelte';
	import QueueChart from '#lib/admin/QueueChart.svelte';

	/** What the background jobs are doing now, with the last minutes as a
	 * chart (sampled while an admin page is open). */
	const QUEUES = [
		{
			queue: 'text',
			title: 'Reading files',
			description: 'Text and, for uploads, details from each file.',
			color: 'var(--royal)'
		},
		{
			queue: 'ml',
			title: 'Search by meaning',
			description: 'Vectors for passages, from the ML service.',
			color: 'var(--success)'
		},
		{
			queue: 'ocr',
			title: 'Reading scans',
			description: 'Text of scanned pages and images (OCR), from the ML service.',
			color: 'var(--tag-teal-ink)'
		},
		{
			queue: 'import',
			title: 'Imports',
			description: 'Libraries from Zotero and others.',
			color: 'var(--highlighter)'
		},
		{
			queue: 'backup',
			title: 'Maintenance',
			description: 'Backups, the trash, integrity checks, tidying up.',
			color: 'var(--muted)'
		}
	] as const;

	const stats = $derived(admin.stats);

	// Which queues show their chart (remembered in this browser).
	const CHARTS_KEY = 'paperus.jobs.charts';
	let charts = $state<Record<string, boolean>>(readCharts());
	function readCharts(): Record<string, boolean> {
		try {
			return JSON.parse(localStorage.getItem(CHARTS_KEY) ?? '{}');
		} catch {
			return {};
		}
	}
	function toggleChart(queue: string) {
		charts = { ...charts, [queue]: !charts[queue] };
		try {
			localStorage.setItem(CHARTS_KEY, JSON.stringify(charts));
		} catch {
			// Storage may be blocked; the chart still shows for this visit.
		}
	}
	const counts = (queue: string) => stats?.jobs[queue] ?? {};
	const total = (status: string) =>
		Object.values(stats?.jobs ?? {}).reduce((sum, c) => sum + (c[status] ?? 0), 0);

	// Imports one started, with their progress.
	let imports = $state<ImportOut[]>([]);
	$effect(() => {
		let alive = true;
		const poll = async () => {
			const { data } = await listImports();
			if (alive)
				imports = (data ?? []).filter((i) => i.status === 'running' || i.status === 'waiting');
		};
		poll();
		const timer = setInterval(poll, 3000);
		return () => {
			alive = false;
			clearInterval(timer);
		};
	});

	/** Jobs finished per minute, from the samples of the last minute. */
	function perMinute(samples: Sample[], at: number): number {
		const now = samples.findLast((s) => s.at <= at);
		const before = samples.find((s) => s.at >= at - 60_000);
		if (!now || !before || now.at - before.at < 5_000) return 0;
		const finished = Math.max(0, now.succeeded - before.succeeded);
		return Math.round((finished * 60_000) / (now.at - before.at));
	}
	const rate = $derived(perMinute(history.samples, Date.now()));

	async function run(job: 'text' | 'embeddings' | 'ocr' | 'text-all' | 'text-failed') {
		if (
			job === 'text-all' &&
			!confirm(
				'Read every file again? Needed after improvements to text extraction. Items, files ' +
					'and your edits stay; unchanged passages keep their search vectors.'
			)
		)
			return;
		await runJob({ path: { job } });
		notify({ kind: 'info', title: 'Started', text: 'It runs in the background.' });
		await loadAdmin();
	}
</script>

<h1>Jobs</h1>
<p class="muted lead">
	Live, updated every 3 seconds. How many run at once and when the night jobs run: <a
		href="{resolve('/admin/settings')}?open=jobs">Settings → Job settings</a
	>.
</p>

<div class="tiles">
	<div><strong>{total('todo').toLocaleString()}</strong><span>waiting</span></div>
	<div><strong>{total('doing')}</strong><span>running now</span></div>
	<div><strong>{rate}</strong><span>finished per minute</span></div>
	<div class:bad={total('failed') > 0}>
		<strong>{total('failed')}</strong><span>failed (kept a month)</span>
	</div>
</div>

{#each imports as running (running.id)}
	<section class="card import">
		<div class="row">
			<strong>Importing {running.filename}</strong>
			<span class="muted"
				>{running.total ? `${running.done} of ${running.total}` : 'starting…'}</span
			>
		</div>
		<progress value={running.done} max={running.total || 1}></progress>
	</section>
{/each}

<div class="queues">
	{#each QUEUES as q (q.queue)}
		{@const c = counts(q.queue)}
		<section class="card queue">
			<div class="queue-head">
				<h2><span class="dot" style:background={q.color}></span>{q.title}</h2>
				<button
					class="chart-toggle"
					class:on={charts[q.queue]}
					aria-pressed={charts[q.queue] ?? false}
					aria-label="Chart of the last two minutes"
					title="Chart of the last two minutes"
					onclick={() => toggleChart(q.queue)}
				>
					<Icon path={mdiChartLine} size={20} />
				</button>
			</div>
			<p class="muted">{q.description}</p>
			{#if charts[q.queue]}
				<QueueChart samples={history.samples} queue={q.queue} color={q.color} />
			{/if}
			<dl>
				<div>
					<dt>Waiting</dt>
					<dd>{(c.todo ?? 0).toLocaleString()}</dd>
				</div>
				<div>
					<dt>Running</dt>
					<dd>{c.doing ?? 0}</dd>
				</div>
				<div>
					<dt>Done</dt>
					<dd>{(c.succeeded ?? 0).toLocaleString()}</dd>
				</div>
				<div class:bad={(c.failed ?? 0) > 0}>
					<dt>Failed</dt>
					<dd>{c.failed ?? 0}</dd>
				</div>
			</dl>
			{#if q.queue === 'text' && stats}
				<progress value={stats.files - stats.files_pending} max={stats.files || 1}></progress>
				<p class="muted small">
					{(stats.files - stats.files_pending).toLocaleString()} of {stats.files.toLocaleString()} files
					read
				</p>
				{#if stats.files_failed}
					<p class="failed">
						{stats.files_failed.toLocaleString()}
						{stats.files_failed === 1 ? 'file' : 'files'} could not be read. They are not tried again
						by themselves (a broken file would fail for ever); try once more after a fix. Everyone finds
						their own, with the reason, under Manage → Unsorted.
					</p>
				{/if}
				<div class="buttons">
					{#if stats.files_failed}
						<button class="primary" onclick={() => run('text-failed')}
							>Read failed files again</button
						>
					{/if}
					<button onclick={() => run('text')}>Read waiting files now</button>
					<button onclick={() => run('text-all')}>Read all files again</button>
				</div>
			{:else if q.queue === 'ml' && stats}
				<progress value={stats.embedded} max={stats.chunks || 1}></progress>
				<p class="muted small">
					{stats.embedded.toLocaleString()} of {stats.chunks.toLocaleString()} passages searchable by
					meaning
				</p>
				<div class="buttons">
					<button onclick={() => run('embeddings')}>Look for missing vectors now</button>
				</div>
			{:else if q.queue === 'ocr' && stats}
				<p class="muted small">
					{stats.files_ocr
						? `${stats.files_ocr.toLocaleString()} ${stats.files_ocr === 1 ? 'file waits' : 'files wait'} for its scanned pages to be read.`
						: 'No scanned pages waiting.'}
				</p>
				{#if stats.files_ocr}
					<div class="buttons">
						<button onclick={() => run('ocr')}>Read scans now</button>
					</div>
				{/if}
			{/if}
		</section>
	{/each}
</div>

<style>
	h1 {
		margin: 0 0 4px;
	}
	.lead {
		margin: 0 0 18px;
	}
	h2 {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 0;
		font-size: var(--step-0);
	}
	p {
		margin: 0;
	}
	.tiles {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
		gap: 10px;
		margin-bottom: 16px;
	}
	.tiles div {
		display: grid;
		padding: 14px 16px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
	}
	.tiles strong {
		font-size: var(--step-2);
		font-variant-numeric: tabular-nums;
	}
	.tiles span,
	.small {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.bad strong,
	.bad dd {
		color: var(--danger);
	}
	section {
		margin-bottom: 16px;
	}
	.import .row {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 8px;
	}
	progress {
		width: 100%;
		height: 8px;
		accent-color: var(--royal);
	}
	.queues {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
		gap: 16px;
	}
	.queue-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}
	.chart-toggle {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		padding: 0;
		border: none;
		border-radius: 50%;
		background: none;
		color: var(--muted);
	}
	.chart-toggle:hover,
	.chart-toggle.on {
		background: var(--rail);
		color: var(--royal);
	}
	.queue {
		display: grid;
		align-content: start;
		gap: 10px;
		margin: 0;
	}
	.dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
	}
	dl {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 8px;
		margin: 0;
	}
	dl div {
		display: grid;
	}
	dt {
		color: var(--muted);
		font-size: var(--step--1);
	}
	dd {
		margin: 0;
		font-weight: 650;
		font-size: var(--step-1);
		font-variant-numeric: tabular-nums;
	}
	.failed {
		padding: 8px 10px;
		border-left: 3px solid var(--danger);
		background: color-mix(in srgb, var(--danger) 8%, var(--surface));
		font-size: var(--step--1);
	}
	.buttons {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
</style>
