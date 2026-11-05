<script lang="ts">
	import { admin, loadAdmin } from '#lib/admin/data.svelte.ts';
	import { runJob } from '#lib/api/client.ts';

	let message = $state('');

	// Mirrors the periodic tasks in server/src/paperus/jobs.py.
	const QUEUES = [
		{
			queue: 'text',
			title: 'Reading files',
			description: 'Text extraction and, for uploads, metadata from the file.',
			schedule: 'Pending files are picked up every 5 minutes.',
			job: 'text' as const,
			action: 'Read pending files now',
			again: 'Read all files again'
		},
		{
			queue: 'ml',
			title: 'Search by meaning',
			description: 'Vectors for passages from the machine learning service.',
			schedule: 'Missing vectors are looked for every 10 minutes.',
			job: 'embeddings' as const,
			action: 'Embed missing now'
		}
	];

	async function run(job: 'text' | 'embeddings' | 'text-all') {
		if (
			job === 'text-all' &&
			!confirm(
				'Read every file again? Needed after improvements to text extraction. Items, files ' +
					'and your edits stay; unchanged passages keep their search vectors.'
			)
		)
			return;
		await runJob({ path: { job } });
		message = 'Started.';
		await loadAdmin();
	}
</script>

<h1>Jobs</h1>
{#if message}<p class="muted">{message}</p>{/if}

{#each QUEUES as q (q.queue)}
	{@const counts = admin.stats?.jobs[q.queue] ?? {}}
	<section class="card">
		<h2>{q.title}</h2>
		<p class="muted">{q.description} {q.schedule}</p>
		<div class="row">
			{#each Object.entries(counts) as [status, count] (status)}
				<span class="badge">{status}: {count}</span>
			{:else}
				<span class="muted">No jobs yet.</span>
			{/each}
		</div>
		<div class="row">
			<button onclick={() => run(q.job)}>{q.action}</button>
			{#if 'again' in q}<button onclick={() => run('text-all')}>{q.again}</button>{/if}
		</div>
	</section>
{/each}

<p class="muted">Concurrency and schedules will be in Settings › Job settings.</p>

<style>
	section {
		display: grid;
		gap: 10px;
		margin-bottom: 16px;
	}
	h2,
	p {
		margin: 0;
	}
</style>
