<script lang="ts">
	import { asset } from '$app/paths';
	import { page } from '$app/state';
	import { checkConsent, errorMessage, giveConsent } from '#lib/api/client.ts';
	import type { ConsentInfo, Scope } from '#lib/api/generated/types.gen.ts';

	/** An app (an AI assistant's connector) asks to act for the person:
	 * OAuth's authorization page. The app's parameters come in the address;
	 * the server checks them (see server/src/paperus/oauth.py). */
	const LABELS: Record<Scope, string> = {
		search: 'Search your library',
		'papers.read': 'Read papers, tags and collections',
		'files.read': 'Read files (PDFs, notes)',
		'groups.read': 'See your groups and their members',
		'papers.write': 'Add and change papers',
		'tags.write': 'Tag papers',
		'collections.write': 'Change collections',
		'notes.write': 'Write and change notes'
	};
	const WRITES: Scope[] = ['papers.write', 'tags.write', 'collections.write', 'notes.write'];

	const params = page.url.searchParams;
	const request = {
		client_id: params.get('client_id') ?? '',
		redirect_uri: params.get('redirect_uri') ?? '',
		response_type: params.get('response_type') ?? '',
		code_challenge: params.get('code_challenge') ?? '',
		code_challenge_method: params.get('code_challenge_method') ?? '',
		scope: params.get('scope'),
		state: params.get('state')
	};

	let info = $state<ConsentInfo | null>(null);
	let error = $state('');
	let chosen = $state<Scope[]>([]);
	let busy = $state(false);
	// Never inside another site's frame (a hidden "Allow" to click).
	const framed = typeof window !== 'undefined' && window.top !== window.self;

	$effect(() => {
		if (framed) return;
		checkConsent({ body: request }).then(({ data, error: failure, response }) => {
			if (data) {
				info = data;
				// Reading as asked; changes only when ticked.
				chosen = data.scopes.filter((s) => !WRITES.includes(s));
			} else if (response?.status !== 401) {
				error = errorMessage(failure);
			}
		});
	});

	// In the order above, not the server's (alphabetical).
	const ORDER = Object.keys(LABELS);
	const asked = $derived(
		[...(info?.scopes ?? [])].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b))
	);
	const reads = $derived(asked.filter((s) => !WRITES.includes(s)));
	const writes = $derived(asked.filter((s) => WRITES.includes(s)));

	function toggle(scope: Scope) {
		chosen = chosen.includes(scope) ? chosen.filter((s) => s !== scope) : [...chosen, scope];
	}

	async function answer(allow: boolean) {
		busy = true;
		const { data, error: failure } = await giveConsent({
			body: { ...request, allow, scopes: allow ? chosen : [] }
		});
		if (!data) {
			busy = false;
			error = errorMessage(failure);
			return;
		}
		// Back to the app, with its one-time code (or the refusal).
		window.location.href = data.redirect;
	}
</script>

<svelte:head><title>Connect an app · paperus</title></svelte:head>

<div class="consent">
	<img class="mark" src={asset('favicon.svg')} alt="" width="56" height="56" />
	{#if framed}
		<p class="error" role="alert">Open this page in its own window to connect an app.</p>
	{:else if error}
		<h1>This app cannot connect</h1>
		<p class="error" role="alert">{error}</p>
		<p class="muted">Start connecting again from the app.</p>
	{:else if info}
		<h1>Connect {info.client_name} to paperus?</h1>
		<p>
			It will act as <strong>{info.username}</strong> and see what you see. You will be sent back to
			<strong>{info.redirect_host}</strong>.
		</p>
		<fieldset>
			<legend>It may</legend>
			{#each reads as scope (scope)}
				<label
					><input
						type="checkbox"
						checked={chosen.includes(scope)}
						onchange={() => toggle(scope)}
					/>{LABELS[scope]}</label
				>
			{/each}
		</fieldset>
		{#if writes.length}
			<fieldset>
				<legend>It asks to change things too</legend>
				{#each writes as scope (scope)}
					<label
						><input
							type="checkbox"
							checked={chosen.includes(scope)}
							onchange={() => toggle(scope)}
						/>{LABELS[scope]}</label
					>
				{/each}
				<p class="hint">Off unless you tick it; AI assistants ask before changing anything.</p>
			</fieldset>
		{/if}
		<div class="actions">
			<button onclick={() => answer(false)} disabled={busy}>Cancel</button>
			<button class="primary" onclick={() => answer(true)} disabled={busy || !chosen.length}
				>Allow</button
			>
		</div>
		<p class="hint">
			Settings → Connected apps shows it, and disconnects it at any time. It never gets your
			password, and never manages your account, groups or the administration.
		</p>
	{:else}
		<p class="muted">Checking the app…</p>
	{/if}
</div>

<style>
	.consent {
		max-width: 440px;
		margin: 10vh auto 0;
	}
	.mark {
		display: block;
		margin: 0 0 12px -4px;
	}
	h1 {
		font-size: 1.6rem;
		margin: 0 0 12px;
		overflow-wrap: anywhere;
	}
	p strong {
		overflow-wrap: anywhere;
	}
	fieldset {
		display: grid;
		gap: 8px;
		margin: 20px 0 0;
		padding: 0;
		border: none;
	}
	legend {
		font-weight: 650;
		margin-bottom: 8px;
	}
	label {
		display: flex;
		gap: 10px;
		align-items: center;
	}
	label input {
		width: auto;
		flex: none;
		margin: 0;
	}
	.actions {
		display: flex;
		justify-content: flex-end;
		gap: 10px;
		margin: 28px 0 16px;
	}
	.actions button {
		padding: 10px 18px;
	}
	.hint {
		color: var(--muted);
		font-size: var(--step--1);
		margin: 4px 0 0;
	}
</style>
