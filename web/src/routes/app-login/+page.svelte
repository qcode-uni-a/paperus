<script lang="ts">
	import { asset } from '$app/paths';
	import { page } from '$app/state';
	import { appLogin, checkAppLogin, errorMessage } from '#lib/api/client.ts';
	import type { AppLoginInfo } from '#lib/api/generated/types.gen.ts';

	/** The paperus app on this computer asks to be logged in (its "Log in
	 * in your browser", app/src-tauri/src/login.rs): the person, logged in
	 * here, confirms; the app gets a one-time code on its loopback address
	 * and trades it for a session (server/src/paperus/oauth.py). */
	const params = page.url.searchParams;
	const request = {
		client_id: params.get('client_id') ?? '',
		redirect_uri: params.get('redirect_uri') ?? '',
		code_challenge: params.get('code_challenge') ?? '',
		state: params.get('state')
	};

	let info = $state<AppLoginInfo | null>(null);
	let error = $state('');
	let busy = $state(false);
	// Never inside another site's frame (a hidden button to click).
	const framed = typeof window !== 'undefined' && window.top !== window.self;

	$effect(() => {
		if (framed) return;
		checkAppLogin({ body: request }).then(({ data, error: failure, response }) => {
			if (data) info = data;
			else if (response?.status !== 401) error = errorMessage(failure);
		});
	});

	async function answer(allow: boolean) {
		busy = true;
		const { data, error: failure } = await appLogin({ body: { ...request, allow } });
		if (!data) {
			busy = false;
			error = errorMessage(failure);
			return;
		}
		// Back to the app, with its one-time code (or the refusal).
		window.location.href = data.redirect;
	}
</script>

<svelte:head><title>Log in to the app · paperus</title></svelte:head>

<div class="app-login">
	<img class="mark" src={asset('favicon.svg')} alt="" width="56" height="56" />
	{#if framed}
		<p class="error" role="alert">Open this page in its own window to log in to the app.</p>
	{:else if error}
		<h1>The app cannot log in</h1>
		<p class="error" role="alert">{error}</p>
		<p class="muted">Start logging in again from the app.</p>
	{:else if info}
		<h1>Log in to the paperus app?</h1>
		<p>
			The paperus app on this computer will be logged in as <strong>{info.username}</strong>, and
			see and do what you can here.
		</p>
		<div class="actions">
			<button onclick={() => answer(false)} disabled={busy}>Cancel</button>
			<button class="primary" onclick={() => answer(true)} disabled={busy}>Log in to the app</button
			>
		</div>
		<p class="hint">
			Only if you just asked for it in the app. Logging out in the app ends this login.
		</p>
	{:else}
		<p class="muted">Checking the app…</p>
	{/if}
</div>

<style>
	.app-login {
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
	}
	p strong {
		overflow-wrap: anywhere;
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
