<script lang="ts">
	import { admin, formatSize, loadAdmin } from '#lib/admin/data.svelte.ts';
	import { deleteMlModel, errorMessage, runJob, setConfig } from '#lib/api/client.ts';

	let chosen = $state('');
	let message = $state('');
	let error = $state('');
	let saving = $state(false);

	const config = $derived(admin.config);
	const embeddingModels = $derived(admin.ml?.models.filter((m) => m.task === 'embedding') ?? []);

	$effect(() => {
		if (config && !chosen) chosen = config.embedding_model;
	});

	async function save() {
		if (!config || chosen === config.embedding_model) return;
		const ok = confirm(
			`Switch search by meaning to ${chosen}? The whole library is embedded again in the ` +
				'background. Until that is done, search by meaning only covers part of it; keyword ' +
				'search keeps working.'
		);
		if (!ok) return;
		saving = true;
		error = message = '';
		const { error: failure } = await setConfig({ body: { ...config, embedding_model: chosen } });
		saving = false;
		if (failure) error = errorMessage(failure);
		else message = `Now using ${chosen}; embedding the library in the background.`;
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
		The model that turns passages and queries into vectors. Changing it embeds the library again.
	</p>
	<div class="row">
		<select bind:value={chosen} disabled={!embeddingModels.length} aria-label="Embedding model">
			{#each embeddingModels as model (model.name)}
				<option value={model.name}>
					{model.name} ({model.dimensions} dimensions, {formatSize(model.cached_bytes)})
				</option>
			{:else}
				<option value={chosen}>{chosen} (service unreachable)</option>
			{/each}
		</select>
		<button
			class="primary"
			onclick={save}
			disabled={saving || !config || chosen === config.embedding_model}>Use this model</button
		>
		<button onclick={embedMissing}>Embed missing now</button>
	</div>
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
		Addresses are set with <code>PAPERUS_ML_URLS</code> for now; tried in order, so a GPU machine can
		come first.
	</p>
</section>

<section class="card">
	<h2>Models</h2>
	<ul>
		{#each admin.ml?.models ?? [] as model (model.name)}
			<li class="row">
				<span>{model.name}</span>
				<span class="badge">{model.task}</span>
				<span class="muted">{formatSize(model.cached_bytes)}</span>
				{#if model.loaded}<span class="badge">in memory</span>{/if}
				{#if model.cached_bytes != null && model.name !== config?.embedding_model}
					<button class="danger" onclick={() => remove(model.name)}>Delete</button>
				{/if}
			</li>
		{:else}
			<li class="muted">The service is not reachable.</li>
		{/each}
	</ul>
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
