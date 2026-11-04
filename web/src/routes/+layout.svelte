<script lang="ts">
	import '../app.css';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import DropZone from '#lib/DropZone.svelte';
	import { loadUser, logout, session } from '#lib/session.svelte.ts';
	import UploadTray from '#lib/UploadTray.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	const onLoginPage = $derived(page.url.pathname === resolve('/login'));

	$effect(() => {
		if (!session.checked && !onLoginPage) loadUser();
	});

	async function signOut() {
		await logout();
		await goto(resolve('/login'));
	}
</script>

<svelte:head>
	<title>paperus</title>
</svelte:head>

{#if !onLoginPage}
	<header>
		<nav>
			<a class="brand" href={resolve('/')}>paperus</a>
			<a href={resolve('/')}>Library</a>
			<a href={resolve('/trash')}>Trash</a>
		</nav>
		{#if session.user}
			<div class="row">
				<span class="muted">{session.user.username}</span>
				<button onclick={signOut}>Log out</button>
			</div>
		{/if}
	</header>
{/if}

<main>
	{@render children()}
</main>

{#if session.user && !onLoginPage}
	<DropZone />
	<UploadTray />
{/if}

<style>
	header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: var(--gap);
		flex-wrap: wrap;
		padding: 10px 16px;
		border-bottom: 1px solid var(--border);
		background: var(--surface);
	}
	nav {
		display: flex;
		gap: 18px;
		align-items: center;
	}
	nav a {
		text-decoration: none;
	}
	.brand {
		color: var(--text);
		font-size: 1.15em;
	}
	main {
		max-width: 960px;
		margin: 0 auto;
		padding: 16px;
	}
</style>
