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

<div class="login card">
	<h1>paperus</h1>
	<p class="muted">Papers, for us.</p>
	<form onsubmit={login}>
		<label>Username <input bind:value={username} autocomplete="username" required /></label>
		<label>
			Password
			<input type="password" bind:value={password} autocomplete="current-password" required />
		</label>
		{#if error}<p class="error">{error}</p>{/if}
		<button class="primary" disabled={busy}>Log in</button>
	</form>
</div>

<style>
	.login {
		max-width: 360px;
		margin: 12vh auto 0;
	}
	h1 {
		margin: 0;
	}
	form {
		display: grid;
		gap: 12px;
	}
	label {
		display: grid;
		gap: 4px;
	}
</style>
