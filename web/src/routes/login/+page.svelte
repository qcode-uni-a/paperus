<script lang="ts">
	import { goto } from '$app/navigation';
	import { asset, resolve } from '$app/paths';
	import { page } from '$app/state';
	import {
		login as apiLogin,
		errorMessage,
		loginMethods,
		me,
		setupState
	} from '#lib/api/client.ts';
	import type { LoginMethods } from '#lib/api/generated/types.gen.ts';
	import { session } from '#lib/session.svelte.ts';

	let username = $state('');
	let password = $state('');
	let error = $state('');
	let busy = $state(false);
	const restored = $derived(page.url.searchParams.has('restored'));
	/** From a failed OIDC login. */
	const failed = $derived(page.url.searchParams.get('error'));
	let methods = $state<LoginMethods | null>(null);
	/** With password login off: the administrators' way in. */
	let showPassword = $state(false);

	$effect(() => {
		loginMethods().then(({ data }) => (methods = data ?? null));
	});

	const next = $derived.by(() => {
		const wanted = page.url.searchParams.get('next');
		// Only paths on this site, never another origin.
		return wanted?.startsWith('/') && !wanted.startsWith('//') ? wanted : '/';
	});
	const oidcHref = $derived(`/api/auth/oidc/start?next=${encodeURIComponent(next)}`);
	const passwordForm = $derived(!methods || methods.password || showPassword);

	// A server without users yet starts with the setup.
	$effect(() => {
		setupState().then(({ data }) => {
			if (data?.needed) goto(resolve('/setup'));
		});
	});

	async function login(event: SubmitEvent) {
		event.preventDefault();
		busy = true;
		error = '';
		const { data, error: failure, response } = await apiLogin({ body: { username, password } });
		busy = false;
		if (!data) {
			error = response?.status === 403 ? errorMessage(failure) : 'Wrong username or password.';
			return;
		}
		// The login cookie is HTTPS-only by default: over plain HTTP the
		// browser drops it, and the next page would ask to log in again.
		if (location.protocol === 'http:' && !(await me()).data) {
			error =
				'The password was right, but this browser did not keep the login: paperus is set to log in over HTTPS only. Open it through its https:// address, or, to try it on a local network, set COOKIE_SECURE=false in the server’s .env.';
			return;
		}
		session.user = data.user;
		session.checked = true;
		await goto(next === '/' ? resolve('/') : next);
	}
</script>

<div class="login">
	<img class="mark" src={asset('favicon.svg')} alt="" width="72" height="72" />
	<h1>paperus</h1>
	<p class="tagline">Papers, for us: the group's library, searchable by meaning.</p>
	{#if restored}
		<p class="restored">Backup restored. Log in with your account from the backup.</p>
	{/if}
	{#if failed}<p class="error" role="alert">{failed}</p>{/if}
	{#if methods?.oidc_label}
		<!-- A full page load: the server sends the browser on to the identity provider. -->
		<a class="oidc" href={oidcHref} data-sveltekit-reload>{methods.oidc_label}</a>
		{#if passwordForm}<p class="or"><span>or with a password</span></p>{/if}
	{/if}
	{#if passwordForm}
		<form onsubmit={login}>
			<label>Username <input bind:value={username} autocomplete="username" required /></label>
			<label>
				Password
				<input type="password" bind:value={password} autocomplete="current-password" required />
			</label>
			{#if error}<p class="error" role="alert">{error}</p>{/if}
			<button class={methods?.oidc_label ? '' : 'primary'} disabled={busy}
				>{busy ? 'Logging in…' : 'Log in'}</button
			>
		</form>
	{:else}
		<button class="admin-login" onclick={() => (showPassword = true)}>
			Administrator login with a password
		</button>
	{/if}
</div>

<style>
	.login {
		max-width: 340px;
		margin: 14vh auto 0;
	}
	h1 {
		font-size: clamp(2.6rem, 9vw, 3.6rem);
		font-weight: 650;
		letter-spacing: -0.03em;
		margin: 0 0 8px;
	}
	.mark {
		display: block;
		margin: 0 0 8px -6px;
	}
	.tagline {
		color: var(--muted);
		margin: 0 0 32px;
	}
	form {
		display: grid;
		gap: 16px;
	}
	label {
		display: grid;
		gap: 6px;
		font-weight: 600;
	}
	label input {
		font-weight: 400;
	}
	button {
		padding: 10px 14px;
		margin-top: 4px;
	}
	.error {
		margin: 0 0 16px;
	}
	form .error {
		margin: 0;
	}
	.oidc {
		display: block;
		padding: 12px 16px;
		border-radius: 999px;
		background: var(--royal);
		color: var(--on-royal, #fff);
		font-weight: 650;
		text-align: center;
		text-decoration: none;
	}
	.oidc:hover {
		filter: brightness(1.08);
	}
	.oidc:focus-visible {
		outline: 2px solid var(--royal);
		outline-offset: 3px;
	}
	.or {
		display: flex;
		align-items: center;
		gap: 12px;
		margin: 24px 0 16px;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.or::before,
	.or::after {
		content: '';
		flex: 1;
		border-top: 1px solid var(--rule);
	}
	.admin-login {
		margin-top: 20px;
		padding: 0;
		border: none;
		background: none;
		color: var(--muted);
		font-size: var(--step--1);
		text-decoration: underline;
	}
	.restored {
		margin: -16px 0 20px;
		padding: 8px 12px;
		border-left: 3px solid var(--success);
		background: var(--rail);
	}
</style>
