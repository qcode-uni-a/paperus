<script lang="ts">
	import { resolve } from '$app/paths';
	import { admin, history, loadAdmin, type Sample } from '#lib/admin/data.svelte.ts';
	import { listImports, runJob } from '#lib/api/client.ts';
	import type { ImportOut } from '#lib/api/generated/types.gen.ts';
	import { notify } from '#lib/toasts.svelte.ts';

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

	// The chart: the last ten minutes.
	const WINDOW = 10 * 60_000;
	const W = 600;
	const H = 150;
	const chart = $derived.by(() => {
		const samples = history.samples;
		const end = samples.at(-1)?.at ?? Date.now();
		const shown = samples.filter((s) => s.at >= end - WINDOW);
		const top = Math.max(
			5,
			...shown.flatMap((s) =>
				QUEUES.map((q) => (s.waiting[q.queue] ?? 0) + (s.running[q.queue] ?? 0))
			)
		);
		const x = (at: number) => W - ((end - at) / WINDOW) * W;
		const y = (n: number) => H - (n / top) * (H - 10);
		const lines = QUEUES.map((q) => ({
			...q,
			points: shown
				.map(
					(s) =>
						`${x(s.at).toFixed(1)},${y((s.waiting[q.queue] ?? 0) + (s.running[q.queue] ?? 0)).toFixed(1)}`
				)
				.join(' ')
		}));
		const rates = shown.map((s) => ({ at: s.at, n: perMinute(samples, s.at) }));
		const rateTop = Math.max(10, ...rates.map((r) => r.n));
		const ratePoints = rates
			.map((r) => `${x(r.at).toFixed(1)},${(H - (r.n / rateTop) * (H - 10)).toFixed(1)}`)
			.join(' ');
		return { lines, top, ratePoints, rateTop, enough: shown.length > 1 };
	});

	async function run(job: 'text' | 'embeddings' | 'text-all' | 'text-failed') {
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

<section class="card chart">
	<div class="chart-head">
		<h2>Last ten minutes</h2>
		<ul class="legend">
			{#each QUEUES as q (q.queue)}<li><span style:background={q.color}></span>{q.title}</li>{/each}
			<li><span class="dashed"></span>Finished per minute</li>
		</ul>
	</div>
	{#if chart.enough}
		<svg
			viewBox="0 0 {W} {H}"
			preserveAspectRatio="none"
			role="img"
			aria-label="Waiting and running jobs per queue over the last ten minutes"
		>
			<line x1="0" x2={W} y1={H - 0.5} y2={H - 0.5} class="axis" />
			{#each chart.lines as line (line.queue)}
				<polyline points={line.points} style:stroke={line.color} />
			{/each}
			<polyline points={chart.ratePoints} class="rate" />
		</svg>
		<div class="scale muted">
			<span
				>Up to {chart.top} jobs waiting or running; up to {chart.rateTop} finished per minute</span
			>
			<span>now</span>
		</div>
	{:else}
		<p class="muted">
			Collecting… the chart starts after a few seconds and fills while this page is open.
		</p>
	{/if}
</section>

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
			<h2><span class="dot" style:background={q.color}></span>{q.title}</h2>
			<p class="muted">{q.description}</p>
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
						by themselves (a broken file would fail for ever); try once more after a fix.
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
	.chart {
		display: grid;
		gap: 10px;
	}
	.chart-head {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: 8px 16px;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 14px;
		margin: 0;
		padding: 0;
		list-style: none;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.legend li {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.legend span {
		width: 14px;
		height: 3px;
		border-radius: 2px;
	}
	.legend .dashed {
		background: none;
		border-top: 2px dashed var(--ink);
	}
	svg {
		width: 100%;
		height: 150px;
		overflow: visible;
	}
	polyline {
		fill: none;
		stroke-width: 2;
		stroke-linejoin: round;
		vector-effect: non-scaling-stroke;
	}
	polyline.rate {
		stroke: var(--ink);
		stroke-dasharray: 4 3;
		opacity: 0.6;
	}
	.axis {
		stroke: var(--rule);
		vector-effect: non-scaling-stroke;
	}
	.scale {
		display: flex;
		justify-content: space-between;
		font-size: var(--step--1);
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
