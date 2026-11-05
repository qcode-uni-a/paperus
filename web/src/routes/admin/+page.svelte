<script lang="ts">
	import {
		deleteMlModel,
		errorMessage,
		getConfig,
		mlStatus,
		runJob,
		setConfig,
		stats as getStats
	} from '#lib/api/client.ts';
	import type { MlStatus, Stats, SystemConfig } from '#lib/api/generated/types.gen.ts';
	import { session } from '#lib/session.svelte.ts';

	let config = $state<SystemConfig | null>(null);
	let ml = $state<MlStatus | null>(null);
	let stats = $state<Stats | null>(null);
	let chosenModel = $state('');
	let message = $state('');
	let error = $state('');
	let saving = $state(false);

	const embeddingModels = $derived(ml?.models.filter((m) => m.task === 'embedding') ?? []);
	const progress = $derived(
		stats && stats.chunks ? Math.round((stats.embedded / stats.chunks) * 100) : 0
	);

	async function load() {
		const [c, m, s] = await Promise.all([getConfig(), mlStatus(), getStats()]);
		if (c.data && !config) chosenModel = c.data.embedding_model;
		config = c.data ?? null;
		ml = m.data ?? null;
		stats = s.data ?? null;
	}

	$effect(() => {
		if (!session.user?.is_admin) return;
		load();
		const timer = setInterval(load, 3000);
		return () => clearInterval(timer);
	});

	async function saveModel() {
		if (!config || chosenModel === config.embedding_model) return;
		const ok = confirm(
			`Switch search by meaning to ${chosenModel}? The whole library is embedded again in ` +
				'the background. Until that is done, search by meaning only covers part of it; ' +
				'keyword search keeps working.'
		);
		if (!ok) return;
		saving = true;
		error = message = '';
		const { error: failure } = await setConfig({
			body: { ...config, embedding_model: chosenModel }
		});
		saving = false;
		if (failure) error = errorMessage(failure);
		else message = `Now using ${chosenModel}; embedding the library in the background.`;
		config = null;
		await load();
	}

	async function start(job: 'embeddings' | 'text') {
		await runJob({ path: { job } });
		message = job === 'embeddings' ? 'Looking for missing embeddings…' : 'Reading pending files…';
		await load();
	}

	async function removeModel(name: string) {
		if (!confirm(`Delete the downloaded files of ${name}? It downloads again when used.`)) return;
		const { error: failure } = await deleteMlModel({ path: { name } });
		if (failure) error = errorMessage(failure);
		await load();
	}

	function size(bytes: number | null | undefined): string {
		if (bytes == null) return 'not downloaded';
		if (bytes < 1024 ** 3) return `${Math.round(bytes / 1024 ** 2)} MB`;
		return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
	}
</script>

<h1>Administration</h1>

{#if !session.user?.is_admin}
	<p class="muted">Only administrators can see this page.</p>
{:else}
	{#if message}<p class="muted">{message}</p>{/if}
	{#if error}<p class="error">{error}</p>{/if}

	<section class="card">
		<h2>Library</h2>
		{#if stats}
			<div class="numbers">
				<div><strong>{stats.items}</strong><span class="muted">items</span></div>
				<div><strong>{stats.files}</strong><span class="muted">files</span></div>
				<div>
					<strong>{stats.files_pending}</strong><span class="muted">files being read</span>
				</div>
				<div><strong>{stats.chunks}</strong><span class="muted">passages</span></div>
			</div>
			<div class="row">
				<button onclick={() => start('text')}>Read pending files now</button>
			</div>
		{/if}
	</section>

	<section class="card">
		<h2>Search by meaning</h2>
		{#if stats}
			<p>
				{stats.embedded} of {stats.chunks} passages embedded with
				<strong>{stats.embedding_model}</strong> ({progress}%).
			</p>
			<div class="bar"><div style:width="{progress}%"></div></div>
		{/if}
		<div class="row">
			<label class="row">
				Model
				<select bind:value={chosenModel} disabled={!embeddingModels.length}>
					{#each embeddingModels as model (model.name)}
						<option value={model.name}>
							{model.name} ({model.dimensions} dimensions, {size(model.cached_bytes)})
						</option>
					{:else}
						<option value={chosenModel}>{chosenModel} (ML service unreachable)</option>
					{/each}
				</select>
			</label>
			<button
				class="primary"
				onclick={saveModel}
				disabled={saving || !config || chosenModel === config.embedding_model}
				>Use this model</button
			>
			<button onclick={() => start('embeddings')}>Embed missing now</button>
		</div>
	</section>

	<section class="card">
		<h2>Machine learning service</h2>
		<ul>
			{#each ml?.services ?? [] as service (service.url)}
				<li class="row">
					<span class="dot" class:ok={service.ok}></span>
					<code>{service.url}</code>
					<span class="muted">{service.ok ? 'reachable' : service.error}</span>
				</li>
			{/each}
		</ul>
		{#if ml?.models.length}
			<h3>Models</h3>
			<ul>
				{#each ml.models as model (model.name)}
					<li class="row">
						<span>{model.name}</span>
						<span class="badge">{model.task}</span>
						<span class="muted">{size(model.cached_bytes)}</span>
						{#if model.loaded}<span class="badge">in memory</span>{/if}
						{#if model.cached_bytes != null && model.name !== config?.embedding_model}
							<button class="danger" onclick={() => removeModel(model.name)}>Delete</button>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<section class="card">
		<h2>Background jobs</h2>
		{#if stats && Object.keys(stats.jobs).length}
			<table>
				<thead><tr><th>Queue</th><th>Status</th><th>Jobs</th></tr></thead>
				<tbody>
					{#each Object.entries(stats.jobs) as [queue, statuses] (queue)}
						{#each Object.entries(statuses) as [status, count] (status)}
							<tr><td>{queue}</td><td>{status}</td><td>{count}</td></tr>
						{/each}
					{/each}
				</tbody>
			</table>
		{:else}
			<p class="muted">No jobs.</p>
		{/if}
	</section>
{/if}

<style>
	section {
		display: grid;
		gap: 12px;
		margin-bottom: 16px;
	}
	h2,
	h3 {
		margin: 0;
	}
	.numbers {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
		gap: 12px;
	}
	.numbers div {
		display: grid;
	}
	.numbers strong {
		font-size: 1.6em;
	}
	select {
		width: auto;
		max-width: 100%;
	}
	ul {
		margin: 0;
		padding: 0;
		display: grid;
		gap: 6px;
	}
	li {
		list-style: none;
	}
	.bar {
		height: 6px;
		border-radius: 3px;
		background: var(--border);
		overflow: hidden;
	}
	.bar div {
		height: 100%;
		background: var(--accent);
		transition: width 0.3s;
	}
	.dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--danger);
	}
	.dot.ok {
		background: #2e7d32;
	}
	table {
		border-collapse: collapse;
	}
	th,
	td {
		text-align: left;
		padding: 4px 16px 4px 0;
	}
</style>
