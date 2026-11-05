<script lang="ts">
	import { admin, formatSize, loadAdmin } from '#lib/admin/data.svelte.ts';
	import {
		deleteMlModel,
		errorMessage,
		measureMlSpeed,
		runJob,
		setConfig
	} from '#lib/api/client.ts';
	import type { MlModel, MlSpeed } from '#lib/api/generated/types.gen.ts';

	let message = $state('');
	let error = $state('');
	let saving = $state(false);
	let speeds = $state<Record<string, MlSpeed>>({});
	let measuring = $state<string | null>(null);

	const config = $derived(admin.config);
	const current = $derived(config?.embedding_model ?? '');
	const models = $derived(admin.ml?.models.filter((m) => m.task === 'embedding') ?? []);
	const passages = $derived(admin.stats?.chunks ?? 0);
	/** The score columns, from what the service says they mean. */
	const benchmarks = $derived(
		Object.entries(models.find((m) => Object.keys(m.benchmarks ?? {}).length)?.benchmarks ?? {})
	);

	function duration(seconds: number): string {
		if (seconds < 90) return 'about a minute';
		if (seconds < 3600 * 1.5) return `about ${Math.round(seconds / 60)} minutes`;
		if (seconds < 86400 * 1.5) return `about ${Math.round(seconds / 3600)} hours`;
		return `about ${Math.round(seconds / 86400)} days`;
	}

	/** How long the library would take, if the model's speed was measured. */
	function estimate(name: string): string | null {
		const speed = speeds[name];
		if (!speed || !passages) return null;
		return duration(passages / speed.passages_per_second);
	}

	async function measure(model: MlModel) {
		measuring = model.name;
		error = '';
		const { data, error: failure } = await measureMlSpeed({ path: { name: model.name } });
		measuring = null;
		if (data) speeds[model.name] = data;
		else error = errorMessage(failure);
		await loadAdmin();
	}

	async function use(model: MlModel) {
		if (!config) return;
		const time = estimate(model.name);
		const ok = confirm(
			`Use ${model.name} for search by meaning?\n\n` +
				`All ${passages.toLocaleString()} passages of the library get new vectors in the ` +
				`background${time ? ` (${time} on this server)` : ''}. Until then, search by meaning ` +
				'finds only what is done; search by words works as always.\n\n' +
				`The vectors of ${current} are kept: switching back is immediate.`
		);
		if (!ok) return;
		saving = true;
		error = message = '';
		const { error: failure } = await setConfig({
			body: { ...config, embedding_model: model.name }
		});
		saving = false;
		if (failure) error = errorMessage(failure);
		else message = `Now using ${model.name}; computing the vectors in the background.`;
		await loadAdmin();
	}

	// CPU cores for the ML service (0: all it sees).
	let threads = $state<number | null>(null);
	const cores = $derived(admin.ml?.service?.cores ?? null);
	$effect(() => {
		if (config && threads === null) threads = config.ml_threads ?? 0;
	});

	async function saveThreads() {
		if (!config || threads === null) return;
		error = message = '';
		const { error: failure } = await setConfig({ body: { ...config, ml_threads: threads } });
		if (failure) error = errorMessage(failure);
		else
			message =
				threads === 0
					? 'The ML service uses all its cores.'
					: `The ML service uses ${threads} ${threads === 1 ? 'core' : 'cores'} per model.`;
		await loadAdmin();
	}

	async function embedMissing() {
		await runJob({ path: { job: 'embeddings' } });
		message = 'Looking for missing embeddings…';
	}

	async function remove(name: string) {
		if (!confirm(`Delete the downloaded files of ${name}? It downloads again when used.`)) return;
		const { error: failure } = await deleteMlModel({ path: { name } });
		if (failure) error = errorMessage(failure);
		await loadAdmin();
	}
</script>

<h1>Machine learning</h1>
{#if message}<p class="muted">{message}</p>{/if}
{#if error}<p class="error">{error}</p>{/if}

<section class="card">
	<h2>Search by meaning</h2>
	<p class="muted">
		The model turns passages and queries into vectors. Better models find more of what is meant;
		faster ones get a large library ready sooner.
	</p>
	<p class="warning" role="note">
		<strong>Changing the model computes new vectors for the whole library</strong>
		({passages.toLocaleString()} passages), which can take hours on a CPU. Until it is done, search by
		meaning finds only part of the library; search by words is not affected. The old vectors are kept,
		so switching back is immediate. Measure a model's speed first to see how long it would take.
	</p>

	<div class="models">
		{#each models as model (model.name)}
			{@const inUse = model.name === current}
			<article class:in-use={inUse}>
				<div class="head">
					<strong>{model.name}</strong>
					{#if inUse}<span class="badge current">In use</span>{/if}
					{#if model.loaded}<span class="badge">In memory</span>{/if}
				</div>
				{#if model.description}<p>{model.description}</p>{/if}
				{#if Object.keys(model.scores ?? {}).length}
					<dl class="scores">
						{#each benchmarks as [key, label] (key)}
							<div>
								<dt>{label.replace(/^Retrieval, /, '')}</dt>
								<dd>
									{#if model.scores?.[key] != null}
										<span class="bar" style:--score="{model.scores[key]}%"></span>
										{model.scores[key].toFixed(1)}
									{:else}
										<span class="muted">not published</span>
									{/if}
								</dd>
							</div>
						{/each}
					</dl>
				{/if}
				<p class="facts muted">
					{model.dimensions} dimensions · inputs up to {model.max_tokens.toLocaleString()} tokens ·
					{model.licence || 'licence: see the model'} ·
					{model.cached_bytes != null
						? `downloaded, ${formatSize(model.cached_bytes)}`
						: `${model.download_mb ? `${model.download_mb} MB to download` : 'not downloaded'}`}
				</p>
				{#if speeds[model.name]}
					{@const speed = speeds[model.name]}
					<p class="speed">
						{speed.passages_per_second} passages per second on this server{estimate(model.name)
							? `: the library in ${estimate(model.name)}`
							: ''}.
					</p>
				{/if}
				<div class="buttons">
					<button onclick={() => measure(model)} disabled={measuring !== null}>
						{measuring === model.name
							? model.cached_bytes == null
								? 'Downloading and measuring…'
								: 'Measuring…'
							: 'Measure speed'}
					</button>
					{#if !inUse}
						<button class="primary" onclick={() => use(model)} disabled={saving || !config}
							>Use this model</button
						>
						{#if model.cached_bytes != null}
							<button class="link danger" onclick={() => remove(model.name)}>Delete download</button
							>
						{/if}
					{/if}
				</div>
			</article>
		{:else}
			<p class="muted">The ML service is not reachable; using {current}.</p>
		{/each}
	</div>
	<p class="muted small">
		Scores: published retrieval results (nDCG@10, out of 100) of the full-precision models from the
		MTEB leaderboard and the MMTEB paper; int8 versions lose about a point. They compare models on
		general search tasks, not on your library.
	</p>
	<div><button onclick={embedMissing}>Embed missing now</button></div>
</section>

<section class="card">
	<h2>CPU cores</h2>
	<p class="muted">
		How many cores the ML service uses for each model. Fewer keep the database and the website quick
		while a large library is being embedded; more get it done sooner.
	</p>
	<div class="row">
		<label class="cores">
			<input
				type="range"
				min="0"
				max={cores ?? 32}
				bind:value={threads}
				aria-label="CPU cores"
				disabled={!config}
			/>
			<span
				>{threads === 0 || threads === null
					? `All${cores ? ` (${cores})` : ''}`
					: `${threads}${cores ? ` of ${cores}` : ''}`}</span
			>
		</label>
		<button onclick={saveThreads} disabled={!config || threads === (config?.ml_threads ?? 0)}
			>Save</button
		>
	</div>
	{#if admin.ml?.service && admin.ml.service.threads !== (config?.ml_threads ?? 0)}
		<p class="muted small">
			The ML service has not taken this setting yet; it gets it within minutes.
		</p>
	{/if}
</section>

<section class="card">
	<h2>Service</h2>
	<ul>
		{#each admin.ml?.services ?? [] as service (service.url)}
			<li class="row">
				<span class="dot" class:ok={service.ok}></span>
				<code>{service.url}</code>
				<span class="muted">{service.ok ? 'reachable' : service.error}</span>
			</li>
		{/each}
	</ul>
	<p class="muted">
		Addresses are set with <code>PAPERUS_ML_URLS</code> for now; tried in order, so a GPU machine
		can come first. The CPU cores it uses: <code>ML_THREADS</code> in <code>.env</code>.
	</p>
</section>

<style>
	section {
		display: grid;
		gap: 12px;
		margin-bottom: 16px;
	}
	h2,
	p {
		margin: 0;
	}
	.cores {
		display: flex;
		align-items: center;
		gap: 12px;
	}
	.cores input {
		width: min(320px, 60vw);
	}
	.cores span {
		min-width: 6ch;
		font-variant-numeric: tabular-nums;
	}
	.warning {
		padding: 10px 14px;
		border-radius: 8px;
		background: color-mix(in srgb, var(--highlighter) 18%, var(--surface));
	}
	.models {
		display: grid;
		gap: 10px;
	}
	article {
		display: grid;
		gap: 6px;
		padding: 12px 14px;
		border: 1px solid var(--rule);
		border-radius: 10px;
	}
	article.in-use {
		border-color: var(--royal);
	}
	.head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
	}
	.current {
		color: var(--royal);
	}
	.scores {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
		gap: 4px 16px;
		margin: 2px 0;
	}
	.scores dt {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.scores dd {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 0;
		font-variant-numeric: tabular-nums;
	}
	/* Scores are drawn from 40 to 65, where these models differ. */
	.bar {
		width: 80px;
		height: 6px;
		border-radius: 3px;
		background: linear-gradient(
			to right,
			var(--royal) clamp(0%, calc((var(--score) - 40%) * 4), 100%),
			var(--rail) 0
		);
	}
	.facts,
	.small {
		font-size: var(--step--1);
	}
	.speed {
		color: var(--ink);
	}
	.buttons {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
	}
	.link {
		border: none;
		background: none;
		padding: 4px 6px;
	}
	.link.danger {
		color: var(--danger);
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
	.dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--danger);
	}
	.dot.ok {
		background: #2e7d32;
	}
</style>
