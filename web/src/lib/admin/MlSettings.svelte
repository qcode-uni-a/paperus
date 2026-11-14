<script lang="ts">
	import { admin, formatSize, loadAdmin } from '#lib/admin/data.svelte.ts';
	import {
		deleteMlModel,
		errorMessage,
		getMultimodal,
		measureMlSpeed,
		runJob,
		setConfig,
		setMultimodal
	} from '#lib/api/client.ts';
	import type { MlModel, MlSpeed, Multimodal } from '#lib/api/generated/types.gen.ts';

	let message = $state('');
	let error = $state('');
	let saving = $state(false);
	let speeds = $state<Record<string, MlSpeed>>({});
	let measuring = $state<string | null>(null);

	const config = $derived(admin.config);
	const current = $derived(config?.embedding_model ?? '');
	/** Models of the kind multimodal search asks for (images too, or text
	 * only): the other kind cannot be chosen. */
	const multimodalOn = $derived(config?.multimodal ?? false);
	const fits = (m: MlModel) => Boolean(m.images) === multimodalOn;
	const models = $derived(admin.ml?.models.filter((m) => m.task === 'embedding' && fits(m)) ?? []);
	const passages = $derived(admin.stats?.chunks ?? 0);
	const rerankers = $derived(admin.ml?.models.filter((m) => m.task === 'rerank' && fits(m)) ?? []);

	let multimodal = $state<Multimodal | null>(null);
	async function loadMultimodal() {
		const { data } = await getMultimodal();
		multimodal = data ?? null;
	}
	$effect(() => {
		void loadMultimodal();
	});
	const gigabytes = (bytes: number | null | undefined) =>
		bytes ? `${Math.round(bytes / 2 ** 30)} GB` : '';

	async function switchMultimodal(on: boolean) {
		if (!multimodal) return;
		const cpu = on && !multimodal.gpu;
		const ok = confirm(
			(on
				? `Turn on multimodal search with ${multimodal.embedding_model} and ${multimodal.rerank_model}?\n\n` +
					'Both models are downloaded (about 3 GB each). All ' +
					`${passages.toLocaleString()} passages get new vectors and every figure is drawn and ` +
					'embedded, in the background: on a GPU about an hour for a few hundred papers.'
				: 'Turn off multimodal search?\n\nSearch goes back to the text models it used before; ' +
					'their vectors are computed again where missing.') +
				'\n\nUntil then, search by meaning finds only what is done; search by words works as always.' +
				(cpu
					? '\n\nThe ML service runs on the CPU: every search would take several seconds, and ' +
						'reading the figures many hours.'
					: '')
		);
		if (!ok) return;
		saving = true;
		error = message = '';
		const { error: failure } = await setMultimodal({ body: { on } });
		saving = false;
		if (failure) error = errorMessage(failure);
		else
			message = on
				? 'Multimodal search is on; passages and figures get their vectors in the background.'
				: 'Multimodal search is off; back to the text models.';
		await loadAdmin();
		await loadMultimodal();
	}
	const onGpu = $derived(admin.ml?.service?.device === 'cuda');
	/** The machine's GPU the ML service can use (or could, with its -cuda image). */
	const gpuName = $derived(admin.ml?.service?.gpus?.find((gpu) => gpu.supported)?.name);

	// Reranking: chosen here, saved with the button.
	let rerank = $state<'auto' | 'on' | 'off' | null>(null);
	let rerankModel = $state<string | null>(null);
	$effect(() => {
		if (config && rerank === null) {
			rerank = config.rerank ?? 'auto';
			rerankModel = config.rerank_model ?? 'bge-reranker-v2-m3';
		}
	});
	const reranking = $derived(rerank === 'on' || (rerank === 'auto' && onGpu));
	/** Per search, from a measured speed: the best 40 hits are reranked. */
	function perSearch(name: string): string | null {
		const speed = speeds[name]?.passages_per_second;
		if (!speed) return null;
		const seconds = 40 / speed;
		return seconds < 1 ? `${Math.round(seconds * 1000)} ms` : `${seconds.toFixed(1)} s`;
	}

	async function saveRerank() {
		if (!config || !rerank || !rerankModel) return;
		error = message = '';
		saving = true;
		const { error: failure } = await setConfig({
			body: { ...config, rerank, rerank_model: rerankModel }
		});
		saving = false;
		if (failure) error = errorMessage(failure);
		else message = 'Reranking saved.';
		await loadAdmin();
	}
	// OCR: chosen here, saved with the button.
	const ocrModels = $derived(admin.ml?.models.filter((m) => m.task === 'ocr') ?? []);
	// The saved settings until changed here.
	let ocrChoice = $state<boolean | null>(null);
	let ocrModelChoice = $state<string | null>(null);
	const ocr = $derived(ocrChoice ?? config?.ocr ?? true);
	const ocrModel = $derived(ocrModelChoice ?? config?.ocr_model ?? 'pp-ocrv6-small');
	/** Seconds per page, from a measured speed (pages per second). */
	function perPage(name: string): string | null {
		const speed = speeds[name]?.passages_per_second;
		if (!speed) return null;
		const seconds = 1 / speed;
		return seconds < 1 ? `${Math.round(seconds * 1000)} ms` : `${seconds.toFixed(1)} s`;
	}

	async function saveOcr() {
		if (!config) return;
		error = message = '';
		saving = true;
		const { error: failure } = await setConfig({
			body: { ...config, ocr, ocr_model: ocrModel }
		});
		saving = false;
		if (failure) error = errorMessage(failure);
		else message = 'OCR saved.';
		await loadAdmin();
		ocrChoice = ocrModelChoice = null;
	}

	/** The score columns, from what the service says they mean: English
	 * and multilingual (German ones are published for few models). */
	const SHOWN_SCORES = ['en', 'multilingual'];
	const benchmarks = $derived(
		Object.entries(
			models.find((m) => Object.keys(m.benchmarks ?? {}).length)?.benchmarks ?? {}
		).filter(([key]) => SHOWN_SCORES.includes(key))
	);

	/** What a model takes once loaded: as measured on this server, else a
	 * guess from its download (twice that: its working memory). */
	function needs(model: MlModel): { bytes: number; measured: boolean } | null {
		if (model.memory_bytes != null) return { bytes: model.memory_bytes, measured: true };
		if (model.download_mb) return { bytes: model.download_mb * 2 * 1024 ** 2, measured: false };
		return null;
	}
	/** The models in use together (the choices on this page, saved or not),
	 * and whether they fit in the GPU's memory (or the RAM) at once. */
	const together = $derived.by(() => {
		const service = admin.ml?.service;
		const space = onGpu ? service?.gpu_memory : service?.ram;
		const chosen = [
			{ what: 'search', model: models.find((m) => m.name === current) },
			{ what: 'reranker', model: reranking ? rerankers.find((m) => m.name === rerankModel) : null },
			{ what: 'OCR', model: ocr ? ocrModels.find((m) => m.name === ocrModel) : null }
		].flatMap(({ what, model }) => {
			const need = model ? needs(model) : null;
			return model && need ? [{ what, model, need }] : [];
		});
		if (!space || !chosen.length) return null;
		// Those loaded already are in the memory used now.
		const loaded = new Set(service?.loaded ?? []);
		const more = chosen
			.filter((c) => !loaded.has(c.model.name))
			.reduce((sum, c) => sum + c.need.bytes, 0);
		// Their runs need about a quarter more for a moment.
		const left = space.free - more * 1.25;
		return {
			chosen,
			total: chosen.reduce((sum, c) => sum + c.need.bytes, 0),
			space,
			fits: left > 0,
			tight: left > 0 && left < space.total * 0.1,
			guessed: chosen.some((c) => !c.need.measured)
		};
	});

	/** "568M parameters · January 2024 · MIT": what is known of it. */
	function facts(model: MlModel): string {
		const size = model.parameters
			? model.parameters >= 1e9
				? `${(model.parameters / 1e9).toFixed(1)}B parameters`
				: `${Number((model.parameters / 1e6).toPrecision(3))}M parameters`
			: '';
		const [year, month] = (model.released ?? '').split('-').map(Number);
		const released =
			year && month
				? new Date(year, month - 1).toLocaleDateString('en', { month: 'long', year: 'numeric' })
				: '';
		return [size, released, model.licence].filter(Boolean).join(' · ');
	}

	/** "Retrieval, multilingual (MMTEB v2)" → "Multilingual". */
	function shortLabel(label: string): string {
		const name = label.replace(/^Retrieval, /, '').replace(/\s*\(.*\)$/, '');
		return name.charAt(0).toUpperCase() + name.slice(1);
	}

	function duration(seconds: number): string {
		if (seconds < 90) return 'about a minute';
		if (seconds < 3600 * 1.5) return `about ${Math.round(seconds / 60)} minutes`;
		if (seconds < 86400 * 1.5) return `about ${Math.round(seconds / 3600)} hours`;
		return `about ${Math.round(seconds / 86400)} days`;
	}

	/** How long the library would take, if the model's speed was measured. */
	function estimate(name: string): string | null {
		const speed = speeds[name];
		if (!speed?.passages_per_second || !passages) return null;
		return duration(passages / speed.passages_per_second);
	}

	let alive = true;
	$effect(() => () => (alive = false));

	/** Measure; a model still downloading or loading is asked again until
	 * it is ready (the page may be left meanwhile). */
	async function measure(model: MlModel) {
		measuring = model.name;
		error = '';
		while (alive) {
			const { data, error: failure } = await measureMlSpeed({ path: { name: model.name } });
			if (data?.loading) {
				await new Promise((done) => setTimeout(done, 5000));
				continue;
			}
			if (data) speeds[model.name] = data;
			else error = errorMessage(failure);
			break;
		}
		measuring = null;
		if (alive) await loadAdmin();
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

	// CPU cores for the ML service (0: all it sees). Unset until an admin
	// chooses: the ML service's own setting applies.
	let threads = $state<number | null>(null);
	const cores = $derived(admin.ml?.service?.cores ?? null);
	$effect(() => {
		if (config && threads === null) threads = config.ml_threads ?? admin.ml?.service?.threads ?? 0;
	});

	async function saveThreads() {
		if (!config || threads === null) return;
		error = message = '';
		saving = true;
		const { error: failure } = await setConfig({ body: { ...config, ml_threads: threads } });
		saving = false;
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

{#if message}<p class="muted">{message}</p>{/if}
{#if error}<p class="error">{error}</p>{/if}

<section class="part">
	<h3>Multimodal search</h3>
	<p class="muted">
		Finds figures by what they show (“a heatmap with a white ring”, “two stacked panels of
		spectra”), not only by their captions: one model reads passages and figures alike, another
		reranks both. On our test questions it put the right figure first for 62 % of descriptions
		instead of 9 %, and text search did a little better too.
	</p>
	{#if multimodal && !multimodal.available}
		<p class="muted">The ML service offers no models for it (paperus-ml 0.2 or newer has them).</p>
	{:else if multimodal}
		<p class="device">
			{#if multimodal.on}
				On: {multimodal.embedding_model} and {multimodal.rerank_model}.
			{:else if multimodal.recommended}
				Recommended here: the GPU has {gigabytes(multimodal.gpu_memory)}, both models need about 4
				GB.
			{:else if multimodal.gpu}
				The GPU has {gigabytes(multimodal.gpu_memory)}; both models need about 4 GB, and some more
				while searching.
			{:else}
				Off. It needs the ML service on a GPU.
			{/if}
		</p>
		{#if !multimodal.on && !multimodal.gpu}
			<p class="warning" role="note">
				The ML service runs on the CPU: with multimodal search every search would take several
				seconds, and reading the library's figures many hours.
			</p>
		{/if}
		<div>
			<button onclick={() => switchMultimodal(!multimodal?.on)} disabled={saving}
				>{multimodal.on ? 'Turn off' : 'Turn on'}</button
			>
		</div>
	{/if}
</section>

<section class="part">
	<h3>Search by meaning</h3>
	<p class="muted">
		The model turns passages and queries into vectors. Better models find more of what is meant;
		faster ones get a large library ready sooner.
	</p>
	{#if admin.ml?.service}
		<p class="device">
			Runs on {admin.ml.service.device === 'cuda'
				? `the GPU${gpuName ? ` (${gpuName})` : ''}: models take seconds where a CPU takes minutes.`
				: `the CPU (${admin.ml.service.cores} cores).`}
			{#if admin.ml.service.device !== 'cuda' && gpuName}
				This machine has a GPU, the {gpuName}: the ML service's -cuda image would use it (see
				<a
					href="https://github.com/qcode-uni-a/paperus/blob/main/docs/operations.md#on-an-nvidia-gpu"
					target="_blank"
					rel="noopener">On an NVIDIA GPU</a
				>).
			{:else if admin.ml.service.device !== 'cuda'}
				The ML service can also run on another machine, such as a workstation with an NVIDIA GPU
				(see
				<a
					href="https://github.com/qcode-uni-a/paperus/blob/main/docs/operations.md#on-another-machine"
					target="_blank"
					rel="noopener">On another machine</a
				>).
			{/if}
		</p>
	{/if}
	<p class="warning" role="note">
		<strong>Changing the model computes new vectors for the whole library</strong>
		({passages.toLocaleString()} passages), which can take hours on a CPU. Until it is done, search by
		meaning finds only part of the library; search by words is not affected. The old vectors are kept,
		so switching back is immediate. Measure a model's speed first to see how long it would take.
	</p>

	<div class="table">
		<table class="models">
			<thead>
				<tr>
					<th scope="col">Model</th>
					{#each benchmarks as [key, label] (key)}
						<th scope="col" class="num" title="{label}, nDCG@10">{shortLabel(label)}</th>
					{/each}
					<th scope="col">Size</th>
					<th scope="col" class="num">Speed here</th>
					<th scope="col" class="num" title="Once loaded, as measured on this server">
						Memory here
					</th>
					<th scope="col"><span class="visually-hidden">Actions</span></th>
				</tr>
			</thead>
			<tbody>
				{#each models as model (model.name)}
					{@const inUse = model.name === current}
					{@const speed = speeds[model.name]}
					<tr class:in-use={inUse}>
						<th scope="row">
							<span class="name">{model.name}</span>
							{#if inUse}<span class="badge current">In use</span>{/if}
							{#if model.recommended}<span class="badge">Recommended</span>{/if}
							<small>{facts(model)}</small>
							{#if model.description}<small>{model.description}</small>{/if}
						</th>
						{#each benchmarks as [key, label] (key)}
							<td class="num" data-label={shortLabel(label)}>
								{model.scores?.[key] != null ? model.scores[key].toFixed(1) : '–'}
							</td>
						{/each}
						<td data-label="Size">
							{model.cached_bytes != null
								? formatSize(model.cached_bytes)
								: model.download_mb
									? `${model.download_mb} MB`
									: '–'}
							<small
								>{model.dimensions}-dim.{model.cached_bytes == null
									? ', not downloaded'
									: ''}</small
							>
						</td>
						<td class="num" data-label="Speed here">
							{#if speed}
								{speed.passages_per_second}/s
								{#if estimate(model.name)}<small>library: {estimate(model.name)}</small>{/if}
							{:else}
								<button class="link" onclick={() => measure(model)} disabled={measuring !== null}
									>{measuring === model.name
										? admin.ml?.service?.loading?.includes(model.name) || model.cached_bytes == null
											? 'Loading…'
											: 'Measuring…'
										: 'Measure'}</button
								>
							{/if}
						</td>
						<td class="num" data-label="Memory here">
							{model.memory_bytes != null ? formatSize(model.memory_bytes) : '–'}
						</td>
						<td class="actions">
							{#if !inUse}
								<button class="small" onclick={() => use(model)} disabled={saving || !config}
									>Use</button
								>
								{#if model.cached_bytes != null}
									<button
										class="link danger"
										title="Delete the downloaded files; they download again when used"
										onclick={() => remove(model.name)}>Delete</button
									>
								{/if}
							{/if}
						</td>
					</tr>
				{:else}
					<tr
						><td colspan="7" class="muted">The ML service is not reachable; using {current}.</td
						></tr
					>
				{/each}
			</tbody>
		</table>
	</div>
	<p class="muted small">
		Scores: published retrieval results (nDCG@10, out of 100) of the full-precision models from the
		MTEB leaderboard and the MMTEB paper; int8 versions lose about a point. They compare models on
		general search tasks, not on your library. Speed and memory: measured on this server (“Measure”;
		memory once a model has loaded).
	</p>
	<div><button onclick={embedMissing}>Embed missing now</button></div>
</section>

<section class="part">
	<h3>Reranking</h3>
	<p class="muted">
		A reranker reads the question together with each of the best 40 hits and puts the best answers
		first. On our 200 test questions it helps weaker search models most (the right paper first 181
		instead of 158 times) and the recommended one little (184 instead of 181). It takes about half a
		second per search on a GPU, but many seconds on a CPU.
	</p>
	<fieldset class="choice">
		<legend class="visually-hidden">Reranking</legend>
		<label
			><input type="radio" bind:group={rerank} value="auto" /> Automatic: on when the ML service runs
			on a GPU</label
		>
		<label
			><input type="radio" bind:group={rerank} value="on" /> Always (slow searches on a CPU)</label
		>
		<label><input type="radio" bind:group={rerank} value="off" /> Off</label>
	</fieldset>
	<p class="device">
		{reranking ? 'Search results are reranked.' : 'Search results are not reranked.'}
	</p>
	{#if rerankers.length}
		<label class="model"
			>Reranker
			<select bind:value={rerankModel}>
				{#each rerankers as model (model.name)}
					<option value={model.name}>{model.name}{model.recommended ? ' (recommended)' : ''}</option
					>
				{/each}
			</select>
		</label>
		{@const chosen = rerankers.find((m) => m.name === rerankModel)}
		{#if chosen}
			<p class="muted">
				{chosen.description}
				{facts(chosen) ? `${facts(chosen)}.` : ''}
				{chosen.cached_bytes != null
					? `Downloaded, ${formatSize(chosen.cached_bytes)}.`
					: chosen.download_mb
						? `${chosen.download_mb} MB to download.`
						: ''}
				{#if chosen.memory_bytes != null}
					{formatSize(chosen.memory_bytes)} in memory here.
				{/if}
				{#if perSearch(chosen.name)}
					About {perSearch(chosen.name)} per search on this server.
				{/if}
			</p>
			<div class="buttons">
				<button onclick={() => measure(chosen)} disabled={measuring !== null}>
					{measuring === chosen.name ? 'Measuring…' : 'Measure speed'}
				</button>
				<button
					class="primary"
					onclick={saveRerank}
					disabled={saving ||
						!config ||
						(rerank === config.rerank && rerankModel === config.rerank_model)}>Save</button
				>
			</div>
		{/if}
	{:else}
		<p class="muted">The ML service is not reachable or offers no reranker.</p>
	{/if}
</section>

<section class="part">
	<h3>Reading scans (OCR)</h3>
	<p class="muted">
		Pages without text, such as scanned PDFs, scanned pages inside a PDF and images (photos of
		notes, scans), are read in the background, so they can be searched and AI assistants can read
		them. Text the PDF has is used as it is. Handwriting is read poorly.
	</p>
	<label class="check"
		><input type="checkbox" bind:checked={() => ocr, (on) => (ocrChoice = on)} /> Read scanned pages and
		images</label
	>
	{#if ocrModels.length}
		<label class="model"
			>OCR model
			<select bind:value={() => ocrModel, (name) => (ocrModelChoice = name)}>
				{#each ocrModels as model (model.name)}
					<option value={model.name}>{model.name}{model.recommended ? ' (recommended)' : ''}</option
					>
				{/each}
			</select>
		</label>
		{@const chosen = ocrModels.find((m) => m.name === ocrModel)}
		{#if chosen}
			<p class="muted">
				{chosen.description}
				{facts(chosen) ? `${facts(chosen)}.` : ''}
				{chosen.cached_bytes != null
					? `Downloaded, ${formatSize(chosen.cached_bytes)}.`
					: chosen.download_mb
						? `${chosen.download_mb} MB to download.`
						: ''}
				{#if chosen.memory_bytes != null}
					{formatSize(chosen.memory_bytes)} in memory here.
				{/if}
				{#if perPage(chosen.name)}
					About {perPage(chosen.name)} per page on this server.
				{/if}
			</p>
			<div class="buttons">
				<button onclick={() => measure(chosen)} disabled={measuring !== null}>
					{measuring === chosen.name ? 'Measuring…' : 'Measure speed'}
				</button>
				<button
					class="primary"
					onclick={saveOcr}
					disabled={saving || !config || (ocr === config.ocr && ocrModel === config.ocr_model)}
					>Save</button
				>
			</div>
		{/if}
	{:else}
		<p class="muted">The ML service is not reachable or offers no OCR model.</p>
	{/if}
</section>

<section class="part">
	<h3>Memory</h3>
	{#if together}
		<p>
			The models in use together take about <strong>{formatSize(together.total)}</strong>
			{onGpu ? 'of the GPU’s memory' : 'of RAM'}:
			{together.chosen
				.map(
					(c) =>
						`${c.model.name} (${c.what}) ${c.need.measured ? '' : '≈'}${formatSize(c.need.bytes)}`
				)
				.join(', ')}.
			{formatSize(together.space.free)} of {formatSize(together.space.total)} are free now.
		</p>
		{#if !together.fits}
			<p class="warning" role="note">
				<strong>They do not all fit at once.</strong> The ML service then unloads the idle ones and
				loads them again when needed{onGpu ? ', and runs the reranker or OCR on the CPU' : ''}:
				searches and reading scans get slower. A smaller model helps, or {onGpu
					? 'a GPU with more memory'
					: 'more RAM'}.
			</p>
		{:else if together.tight}
			<p class="warning" role="note">
				They fit, but only just: other programs on this machine may take the rest.
			</p>
		{/if}
		{#if together.guessed}
			<p class="muted small">
				≈: guessed from the download; measured once the model has loaded on this server.
			</p>
		{/if}
	{:else}
		<p class="muted">
			The ML service does not say how much memory there is (an older version), or no model is
			chosen.
		</p>
	{/if}
	{#each Object.entries(admin.ml?.service?.on_cpu ?? {}) as [name, why] (name)}
		<p class="warning" role="note">{name} runs on the CPU: {why}.</p>
	{/each}
</section>

<section class="part">
	<h3>CPU cores</h3>
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
		<button
			onclick={saveThreads}
			disabled={saving || !config || threads === (config?.ml_threads ?? admin.ml?.service?.threads)}
			>Save</button
		>
	</div>
	{#if config?.ml_threads == null}
		<p class="muted small">Not set here: the ML service uses its own setting.</p>
	{:else if admin.ml?.service && admin.ml.service.threads !== config.ml_threads}
		<p class="muted small">
			The ML service has not taken this setting yet; it gets it within minutes.
		</p>
	{/if}
</section>

<section class="part">
	<h3>Service</h3>
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
	/* Parts of the settings section, divided by lines. */
	.part {
		display: grid;
		gap: 12px;
		padding: 18px 0;
	}
	.part + .part {
		border-top: 1px solid var(--rule);
	}
	h3 {
		margin: 0;
		font-size: var(--step-0);
		font-weight: 650;
	}
	p {
		margin: 0;
	}
	.choice {
		display: grid;
		gap: 6px;
		margin: 0;
		padding: 0;
		border: none;
	}
	.choice label {
		display: flex;
		align-items: center;
		justify-content: flex-start;
		gap: 8px;
	}
	.choice input {
		width: auto;
		margin: 0;
	}
	.model {
		display: flex;
		align-items: center;
		gap: 10px;
		font-weight: 600;
	}
	.check {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.check input {
		width: auto;
		margin: 0;
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
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
	/* The models in a table: one line each, what decides at a glance. */
	.table {
		overflow-x: auto;
	}
	table.models {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--step--1);
	}
	.models th,
	.models td {
		padding: 7px 10px;
		border-bottom: 1px solid var(--rule);
		text-align: left;
		vertical-align: top;
	}
	.models thead th {
		color: var(--muted);
		font-weight: 600;
		white-space: nowrap;
	}
	.models tbody th {
		font-weight: 400;
		min-width: 18em;
	}
	.models .name {
		font-weight: 600;
		margin-right: 6px;
	}
	.models small {
		display: block;
		color: var(--muted);
	}
	.models .num {
		text-align: right;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.models tr.in-use {
		background: color-mix(in srgb, var(--royal) 6%, transparent);
	}
	.models .actions {
		white-space: nowrap;
		text-align: right;
	}
	.models button.small {
		padding: 3px 12px;
	}
	.current {
		color: var(--royal);
	}
	/* On a phone: each model a block, its values labelled. */
	@media (max-width: 720px) {
		.models thead {
			display: none;
		}
		.models tr {
			display: grid;
			grid-template-columns: repeat(3, minmax(0, 1fr));
			gap: 4px 12px;
			padding: 10px 0;
			border-bottom: 1px solid var(--rule);
		}
		.models th,
		.models td {
			padding: 0;
			border: none;
		}
		.models tbody th,
		.models .actions {
			grid-column: 1 / -1;
			text-align: left;
		}
		.models td.num {
			text-align: left;
		}
		.models td[data-label]::before {
			content: attr(data-label);
			display: block;
			color: var(--muted);
		}
	}
	.small {
		font-size: var(--step--1);
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
