<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { login as apiLogin } from '#lib/api/client.ts';
	import { session } from '#lib/session.svelte.ts';

	let username = $state('');
	let password = $state('');
	let error = $state('');
	let busy = $state(false);

	async function login(event: SubmitEvent) {
		event.preventDefault();
		busy = true;
		error = '';
		const { data } = await apiLogin({ body: { username, password } });
		busy = false;
		if (!data) {
			error = 'Wrong username or password.';
			return;
		}
		session.user = data.user;
		session.checked = true;
		const next = page.url.searchParams.get('next');
		// Only paths on this site, never another origin.
		await goto(next?.startsWith('/') && !next.startsWith('//') ? next : resolve('/'));
	}
</script>

<div class="login">
	<h1><span class="highlight">paperus</span></h1>
	<p class="tagline">Papers, for us: the group's library, searchable by meaning.</p>
	<form onsubmit={login}>
		<label>Username <input bind:value={username} autocomplete="username" required /></label>
		<label>
			Password
			<input type="password" bind:value={password} autocomplete="current-password" required />
		</label>
		{#if error}<p class="error" role="alert">{error}</p>{/if}
		<button class="primary" disabled={busy}>{busy ? 'Logging in…' : 'Log in'}</button>
	</form>
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
	h1 .highlight {
		padding: 0 0.2em;
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
		margin: 0;
	}
</style>
