<script lang="ts">
	import { goto } from '$app/navigation';
	import { asset, resolve } from '$app/paths';
	import { page } from '$app/state';
	import {
		authentication,
		checkProvider,
		checkRestore,
		createFirstAdmin,
		createGroup,
		errorMessage,
		getConfig,
		gettingStarted,
		mlStatus,
		restoreOnFirstStart,
		setConfig,
		setOidcSecret,
		setupState
	} from '#lib/api/client.ts';
	import type {
		GpuStep,
		MlModel,
		MlStatus,
		ProviderFound,
		RestoreCheckOut,
		SetupState,
		SystemConfig
	} from '#lib/api/generated/types.gen.ts';
	import { formatDateTime } from '#lib/dates.svelte.ts';
	import { ELSEWHERE_HELP, gpuAdvice } from '#lib/gpu.ts';
	import { session } from '#lib/session.svelte.ts';

	/** First start: a new administrator, or a backup restored. */
	let setup = $state<SetupState | null>(null);
	// Back from linking the OIDC login: on to the group.
	let choice = $state<'new' | 'restore' | 'ml' | 'oidc' | 'group' | null>(
		page.url.searchParams.get('step') === 'group' ? 'group' : null
	);
	let error = $state('');
	const linkError = page.url.searchParams.get('link_error');

	$effect(() => {
		setupState().then(({ data }) => {
			setup = data ?? null;
			// Set up already (e.g. someone else was faster): to the login.
			if (data && !data.needed && !['ml', 'oidc', 'group'].includes(choice ?? ''))
				goto(resolve('/login'));
		});
	});

	// Start new.
	let username = $state('');
	let password = $state('');
	let repeat = $state('');
	let busy = $state(false);

	async function startNew(event: SubmitEvent) {
		event.preventDefault();
		error = '';
		if (password !== repeat) {
			error = 'The two passwords differ.';
			return;
		}
		busy = true;
		const { data, error: failure } = await createFirstAdmin({ body: { username, password } });
		busy = false;
		if (!data) {
			error = errorMessage(failure);
			return;
		}
		session.user = data.user;
		session.checked = true;
		// Next: the machine learning service.
		choice = 'ml';
	}

	// The machine learning service: does it answer, where does it run, and
	// its basic settings (all also later, under Administration).
	let ml = $state<MlStatus | null>(null);
	let gpu = $state<GpuStep | null>(null);
	let config = $state<SystemConfig | null>(null);
	let embeddingModel = $state('');
	let rerank = $state<'auto' | 'on' | 'off'>('auto');
	let rerankModel = $state('');
	let ocr = $state(true);
	let ocrModel = $state('');
	const answers = $derived(ml?.services.some((s) => s.ok) ?? false);
	const embedders = $derived(ml?.models.filter((m) => m.task === 'embedding') ?? []);
	const rerankers = $derived(ml?.models.filter((m) => m.task === 'rerank') ?? []);
	const readers = $derived(ml?.models.filter((m) => m.task === 'ocr') ?? []);
	/** A model's name with its download size (or that it comes with the ML
	 * service) and whether it is recommended, for the lists. */
	const sized = (model: MlModel) =>
		`${model.name}${model.builtin ? '' : model.download_mb ? ` (${model.download_mb} MB)` : ''}${model.recommended ? ', recommended' : ''}`;
	const advice = $derived(gpu ? gpuAdvice(gpu) : null);

	async function checkMl() {
		const [status, steps] = await Promise.all([mlStatus(), gettingStarted()]);
		ml = status.data ?? null;
		gpu = steps.data?.server?.gpu ?? null;
	}

	$effect(() => {
		if (choice !== 'ml') return;
		getConfig().then(({ data }) => {
			config = data ?? null;
			if (data) {
				embeddingModel = data.embedding_model;
				rerank = data.rerank ?? 'auto';
				rerankModel = data.rerank_model ?? '';
				ocr = data.ocr ?? true;
				ocrModel = data.ocr_model ?? '';
			}
		});
		void checkMl();
		// Again while it starts (it may be downloading its first model).
		const timer = setInterval(() => {
			if (!answers || ml?.service?.loading?.length) void checkMl();
		}, 3000);
		return () => clearInterval(timer);
	});

	async function saveMl(event: SubmitEvent) {
		event.preventDefault();
		if (!config) return;
		error = '';
		busy = true;
		const { error: failure } = await setConfig({
			body: {
				...config,
				embedding_model: embeddingModel,
				rerank,
				rerank_model: rerankModel,
				ocr,
				ocr_model: ocrModel
			}
		});
		busy = false;
		if (failure) error = errorMessage(failure);
		else await toOidc();
	}

	// Next, optionally: the OIDC login.
	async function toOidc() {
		error = '';
		choice = 'oidc';
		const info = await authentication();
		redirectUri = info.data?.redirect_uri ?? '';
	}

	// The OIDC login (optional), linked to the new administrator.
	let redirectUri = $state('');
	let issuer = $state('');
	let clientId = $state('');
	let secret = $state('');
	let buttonText = $state('Log in with OIDC');
	let found = $state<ProviderFound | null>(null);

	async function checkIssuer() {
		const { data, error: failure } = await checkProvider({ body: { issuer: issuer.trim() } });
		found = data ?? { ok: false, error: errorMessage(failure) };
	}

	async function saveOidc(event: SubmitEvent) {
		event.preventDefault();
		error = '';
		busy = true;
		const current = await getConfig();
		if (!current.data) {
			busy = false;
			error = errorMessage(current.error);
			return;
		}
		const saved = await setConfig({
			body: {
				...current.data,
				oidc_enabled: true,
				oidc_issuer: issuer.trim(),
				oidc_client_id: clientId.trim(),
				oidc_label: buttonText.trim() || 'Log in with OIDC'
			}
		});
		if (!saved.error && secret) await setOidcSecret({ body: { secret } });
		busy = false;
		if (saved.error) {
			error = errorMessage(saved.error);
			return;
		}
		// One login there links it to this account; then the group.
		const next = '/setup?step=group';
		window.location.href = `/api/auth/oidc/start?link=true&next=${encodeURIComponent(next)}`;
	}

	// A first group (optional), its admin the new administrator.
	let groupName = $state('');
	let groupDescription = $state('');

	async function addGroup(event: SubmitEvent) {
		event.preventDefault();
		error = '';
		busy = true;
		const { data, error: failure } = await createGroup({
			body: {
				name: groupName.trim(),
				description: groupDescription.trim() || null
			}
		});
		busy = false;
		if (!data) {
			error = errorMessage(failure);
			return;
		}
		await goto(`${resolve('/manage/groups')}?group=${data.id}`);
	}

	// Restore.
	let chosen = $state<string | null>(null);
	let check = $state<RestoreCheckOut | null>(null);
	let restoring = $state(false);

	async function choose(name: string) {
		chosen = name;
		check = null;
		error = '';
		const { data, error: failure } = await checkRestore({ query: { name } });
		if (chosen !== name) return;
		if (failure) error = errorMessage(failure);
		check = data ?? null;
	}

	async function restore() {
		if (!chosen) return;
		restoring = true;
		error = '';
		const { error: failure } = await restoreOnFirstStart({ body: { name: chosen } });
		restoring = false;
		if (failure) {
			error = errorMessage(failure);
			return;
		}
		await goto(`${resolve('/login')}?restored=1`);
	}
</script>

<svelte:head><title>Set up paperus</title></svelte:head>

<div class="setup">
	<img class="mark" src={asset('favicon.svg')} alt="" width="64" height="64" />
	<h1>Welcome to paperus</h1>

	{#if !choice}
		<p class="muted">This server has no users yet. How do you want to start?</p>
		<div class="choices">
			<button class="choice" onclick={() => (choice = 'new')}>
				<strong>Start new</strong>
				<span>Create the administrator account; add people and groups afterwards.</span>
			</button>
			<button class="choice" onclick={() => (choice = 'restore')} disabled={!setup}>
				<strong>Restore from a backup</strong>
				<span>
					{setup?.backups.length
						? `${setup.backups.length} ${setup.backups.length === 1 ? 'backup' : 'backups'} found.`
						: 'For moving to a new server, or after losing the old one.'}
				</span>
			</button>
		</div>
	{:else if choice === 'new'}
		<form onsubmit={startNew}>
			<h2>The administrator</h2>
			<p class="muted">
				Manages users, groups and settings. You can make others administrators later.
			</p>
			<label>Username <input bind:value={username} autocomplete="username" required /></label>
			<label
				>Password <input
					type="password"
					bind:value={password}
					autocomplete="new-password"
					minlength="8"
					required
				/></label
			>
			<label
				>Password again <input
					type="password"
					bind:value={repeat}
					autocomplete="new-password"
					minlength="8"
					required
				/></label
			>
			{#if error}<p class="error">{error}</p>{/if}
			<div class="buttons">
				<button type="button" onclick={() => (choice = null)}>Back</button>
				<button class="primary" disabled={busy}>Create and start</button>
			</div>
		</form>
	{:else if choice === 'ml'}
		<form onsubmit={saveMl}>
			<h2>Machine learning</h2>
			<p class="muted">
				The ML service finds papers by what is meant, reads scanned pages (OCR) and puts the best
				answers first. Without it, paperus searches by words. Also later, under Administration →
				Settings → Machine learning.
			</p>
			{#if !ml}
				<p class="muted">Asking the ML service…</p>
			{:else if !answers}
				<div class="check warn" role="status">
					<p><strong>The ML service does not answer.</strong></p>
					<ul class="services">
						{#each ml.services as service (service.url)}
							<li><code>{service.url}</code>: {service.error}</li>
						{/each}
					</ul>
					<p class="muted">
						Just started, it may still be getting ready; this page asks again every few seconds.
						Otherwise see <code>docker compose logs ml</code>: <code>ML_TOKEN</code> in
						<code>.env</code> must be the same for paperus and the ML service, and
						<code>ML_URLS</code> must name it if it runs on another machine.
					</p>
				</div>
			{:else}
				<div class="check" class:warn={advice && !advice.done} role="status">
					<p>
						<strong>The ML service answers</strong>{ml.service
							? ml.service.device === 'cuda'
								? ` and runs on the GPU${advice?.done ? ` (${gpu?.card})` : ''}.`
								: ` and runs on the CPU (${ml.service.cores} cores).`
							: '.'}
						{#if ml.service?.loading?.length}
							Loading {ml.service.loading.join(', ')}…
						{/if}
					</p>
					{#if advice && !advice.done}
						<p><strong>{advice.title}.</strong> {advice.text}</p>
						<p>
							{#each advice.links as [href, text], i (href)}{#if i}{' · '}{/if}<a
									{href}
									target="_blank"
									rel="noopener">{text}</a
								>{/each}
						</p>
					{:else if ml.service?.device !== 'cuda'}
						<p class="muted">
							On a CPU, search by meaning works, but reading a large library takes hours. The ML
							service can also run on another machine with an NVIDIA GPU (<a
								href={ELSEWHERE_HELP}
								target="_blank"
								rel="noopener">On another machine</a
							>).
						</p>
					{/if}
				</div>
				{#if config && embedders.length}
					<label
						>Model for search by meaning
						<select bind:value={embeddingModel}>
							{#each embedders as model (model.name)}
								<option value={model.name}>{sized(model)}</option>
							{/each}
						</select>
					</label>
					{@const described = embedders.find((m) => m.name === embeddingModel)}
					<p class="muted small">
						{described?.description ?? ''} Choose it now, while the library is empty: changing it later
						computes the vectors of the whole library again.
					</p>
					<label
						>Reranking
						<select bind:value={rerank}>
							<option value="auto">Automatic: on when the ML service runs on a GPU</option>
							<option value="on">Always (searches take seconds on a CPU)</option>
							<option value="off">Off</option>
						</select>
					</label>
					{#if rerank !== 'off' && rerankers.length}
						<label
							>Reranker
							<select bind:value={rerankModel}>
								{#each rerankers as model (model.name)}
									<option value={model.name}>{sized(model)}</option>
								{/each}
							</select>
						</label>
						<p class="muted small">
							{rerankers.find((m) => m.name === rerankModel)?.description ?? ''}
						</p>
					{/if}
					<label class="inline"
						><input type="checkbox" bind:checked={ocr} /> Read scanned pages (OCR)</label
					>
					{#if ocr && readers.length}
						<label
							>OCR model
							<select bind:value={ocrModel}>
								{#each readers as model (model.name)}
									<option value={model.name}>{sized(model)}</option>
								{/each}
							</select>
						</label>
						<p class="muted small">
							{readers.find((m) => m.name === ocrModel)?.description ?? ''}
						</p>
					{/if}
				{/if}
			{/if}
			{#if error}<p class="error">{error}</p>{/if}
			<div class="buttons">
				<button type="button" onclick={toOidc}>Skip</button>
				<button class="primary" disabled={busy || !answers || !config}>Save and continue</button>
			</div>
		</form>
	{:else if choice === 'oidc'}
		<form onsubmit={saveOidc}>
			<h2>OIDC login</h2>
			<p class="muted">
				Optional: people log in through an identity provider with OpenID Connect (OIDC), e.g. their
				university’s or company’s. Your account is linked to it right away; your password stays, as
				a way in if the OIDC login fails. Also later, under Administration → Settings →
				Authentication.
			</p>
			<div class="redirect">
				<span>Register this redirect address at the identity provider:</span>
				<code>{redirectUri || '…'}</code>
			</div>
			<label
				>Identity provider
				<span class="with-button">
					<input
						type="url"
						bind:value={issuer}
						placeholder="https://login.uni-example.de/realms/staff"
						oninput={() => (found = null)}
						required
					/>
					<button type="button" onclick={checkIssuer} disabled={!issuer.trim()}>Check</button>
				</span>
			</label>
			{#if found}
				<p class="check" class:warn={!found.ok}>
					{found.ok ? `Found: logins go to ${found.authorization_endpoint}` : found.error}
				</p>
			{/if}
			<label>Client ID <input bind:value={clientId} placeholder="paperus" required /></label>
			<label>Client secret <input type="password" bind:value={secret} autocomplete="off" /></label>
			<label>Button text <input bind:value={buttonText} maxlength="60" /></label>
			{#if error}<p class="error">{error}</p>{/if}
			<div class="buttons">
				<button type="button" onclick={() => ((choice = 'group'), (error = ''))}>Skip</button>
				<button class="primary" disabled={busy}>Save and link my account</button>
			</div>
		</form>
	{:else if choice === 'group'}
		<form onsubmit={addGroup}>
			<h2>A first group</h2>
			{#if linkError}
				<p class="check warn">
					{linkError} Your account is not linked yet; try again under Administration → Settings → Authentication.
				</p>
			{/if}
			<p class="muted">
				Optional: papers are shared in groups, e.g. a research group or a course. You are its admin;
				add people afterwards. Also later, under Manage → Groups.
			</p>
			<label>Name <input bind:value={groupName} required maxlength="200" /></label>
			<label>
				<span>Description <span class="optional">(optional)</span></span>
				<textarea bind:value={groupDescription} rows="2"></textarea>
			</label>
			{#if error}<p class="error">{error}</p>{/if}
			<div class="buttons">
				<button type="button" onclick={() => goto(resolve('/'))}>Skip</button>
				<button class="primary" disabled={busy}>Create group</button>
			</div>
		</form>
	{:else}
		<section class="restore">
			<h2>Restore from a backup</h2>
			{#if !setup?.backups.length}
				<p>
					No backups found in <code>{setup?.backup_path}</code>. Copy a backup there (its folder
					and, for files, the <code>files</code> folder next to it), then reload this page.
				</p>
			{:else}
				<p class="muted">Backups in <code>{setup.backup_path}</code>:</p>
				<ul>
					{#each setup.backups as backup (backup.name)}
						<li>
							<button
								class="backup"
								class:chosen={chosen === backup.name}
								onclick={() => choose(backup.name)}
							>
								<strong>{formatDateTime(backup.created_at)}</strong>
								<span
									>{backup.items} papers, {backup.with_files
										? `${backup.files} files`
										: 'database only'}, paperus {backup.paperus_version}</span
								>
							</button>
						</li>
					{/each}
				</ul>

				{#if chosen && !check && !error}
					<p class="muted">Checking the files…</p>
				{:else if check}
					<div class="check" class:warn={check.missing > 0}>
						{#if check.needed === 0}
							<p>The backup's papers have no files.</p>
						{:else if check.missing === 0}
							<p>
								<strong>All {check.needed} files are available</strong>: {check.in_storage} already in
								the file storage{check.from_backup
									? `, ${check.from_backup} copied back from the backup`
									: ''}.
							</p>
						{:else}
							<p>
								<strong
									>{check.missing} of {check.needed} files are neither in the backup nor in the file storage.</strong
								>
								{check.with_files
									? 'The backup is incomplete.'
									: 'This backup has no files, and the storage lacks them.'}
								{check.affected_count}
								{check.affected_count === 1 ? 'paper' : 'papers'} would open without its file:
							</p>
							<ul class="affected">
								{#each check.affected as title (title)}<li>{title}</li>{/each}
								{#if check.affected_count > check.affected.length}
									<li>and {check.affected_count - check.affected.length} more</li>
								{/if}
							</ul>
							<p class="muted">
								If you have the files elsewhere, put them into the file storage first, then check
								again.
							</p>
						{/if}
						{#if check.extra}
							<p class="muted">
								{check.extra} files in the storage are not in this backup (probably added after it); they
								stay on disk.
							</p>
						{/if}
						<p class="muted small">
							Files are stored by their fingerprint, so one already on disk is the very same file:
							nothing is overwritten.
						</p>
					</div>
				{/if}
			{/if}
			{#if error}<p class="error">{error}</p>{/if}
			<div class="buttons">
				<button type="button" onclick={() => ((choice = null), (chosen = null))}>Back</button>
				{#if setup?.backups.length}
					<button class="primary" disabled={!check || restoring} onclick={restore}>
						{restoring ? 'Restoring…' : check?.missing ? 'Restore anyway' : 'Restore'}
					</button>
				{/if}
			</div>
			{#if restoring}
				<p class="muted small">This can take a few minutes for a large library.</p>
			{/if}
		</section>
	{/if}
</div>

<style>
	.setup {
		max-width: 560px;
		margin: 10vh auto 40px;
		padding: 0 16px;
	}
	.mark {
		display: block;
		margin: 0 0 8px -6px;
	}
	h1 {
		margin: 0 0 8px;
		font-size: clamp(2rem, 7vw, 2.8rem);
		letter-spacing: -0.02em;
	}
	h2 {
		margin: 0 0 4px;
		font-size: var(--step-2);
	}
	p {
		margin: 0 0 12px;
	}
	.choices {
		display: grid;
		gap: 12px;
		margin-top: 20px;
	}
	.choice {
		display: grid;
		gap: 4px;
		padding: 16px 18px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		text-align: left;
		color: var(--ink);
	}
	.choice:hover:not(:disabled) {
		border-color: var(--royal);
		background: var(--surface);
	}
	.choice strong {
		font-family: var(--serif);
		font-size: var(--step-1);
	}
	.choice span {
		color: var(--muted);
	}
	form,
	.restore {
		display: grid;
		gap: 12px;
		margin-top: 16px;
	}
	label {
		display: grid;
		gap: 6px;
		font-weight: 600;
	}
	label input,
	label textarea,
	label select {
		font-weight: 400;
	}
	label.inline {
		display: flex;
		align-items: center;
		gap: 8px;
		font-weight: 400;
	}
	label.inline input {
		flex: none;
		width: auto;
		margin: 0;
	}
	.services {
		margin: 0 0 12px;
		gap: 2px;
	}
	.optional {
		color: var(--muted);
		font-weight: 400;
	}
	ul {
		margin: 0;
		padding: 0;
		list-style: none;
		display: grid;
		gap: 6px;
	}
	.backup {
		display: grid;
		gap: 2px;
		width: 100%;
		padding: 10px 12px;
		border: 1px solid var(--rule);
		border-radius: 8px;
		background: var(--surface);
		text-align: left;
		color: var(--ink);
	}
	.backup.chosen {
		border-color: var(--royal);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--royal) 25%, transparent);
	}
	.backup span {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.check {
		padding: 12px 14px;
		border-left: 3px solid var(--success);
		border-radius: 0 8px 8px 0;
		background: var(--rail);
	}
	.check.warn {
		border-left-color: var(--highlighter);
		background: color-mix(in srgb, var(--highlighter) 16%, var(--surface));
	}
	.check p:last-child {
		margin-bottom: 0;
	}
	.affected {
		margin: 0 0 12px 18px;
		list-style: disc;
		gap: 2px;
		font-family: var(--serif);
	}
	.small {
		font-size: var(--step--1);
	}
	code {
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
		font-size: 0.88em;
		overflow-wrap: anywhere;
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
	.redirect {
		display: grid;
		gap: 4px;
		padding: 10px 12px;
		border-radius: 8px;
		background: var(--rail);
		font-size: var(--step--1);
	}
	.with-button {
		display: flex;
		gap: 8px;
		font-weight: 400;
	}
	.with-button input {
		flex: 1;
		min-width: 0;
	}
</style>
