<script lang="ts">
	import { goto } from '$app/navigation';
	import { asset, resolve } from '$app/paths';
	import {
		checkRestore,
		createFirstAdmin,
		errorMessage,
		restoreOnFirstStart,
		setupState
	} from '#lib/api/client.ts';
	import type { RestoreCheckOut, SetupState } from '#lib/api/generated/types.gen.ts';
	import { session } from '#lib/session.svelte.ts';

	/** First start: a new administrator, or a backup restored. */
	let setup = $state<SetupState | null>(null);
	let choice = $state<'new' | 'restore' | null>(null);
	let error = $state('');

	$effect(() => {
		setupState().then(({ data }) => {
			setup = data ?? null;
			// Set up already (e.g. someone else was faster): to the login.
			if (data && !data.needed) goto(resolve('/login'));
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
		await goto(resolve('/'));
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
								<strong>{new Date(backup.created_at).toLocaleString()}</strong>
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
	label input {
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
</style>
