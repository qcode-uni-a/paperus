<script lang="ts">
	import '../app.css';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import DropZone from '#lib/DropZone.svelte';
	import { menu } from '#lib/menu.svelte.ts';
	import { loadUser, logout, session } from '#lib/session.svelte.ts';
	import Sidebar from '#lib/Sidebar.svelte';
	import UploadTray from '#lib/UploadTray.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	const onLoginPage = $derived(page.url.pathname === resolve('/login'));

	$effect(() => {
		if (!session.checked && !onLoginPage) loadUser();
	});

	$effect(() => menu.watch());

	async function signOut() {
		await logout();
		await goto(resolve('/login'));
	}
</script>

<svelte:head>
	<title>paperus</title>
</svelte:head>

{#if onLoginPage}
	<main class="login">{@render children()}</main>
{:else}
	<header>
		<div class="row">
			<button
				class="burger"
				onclick={() => menu.toggle()}
				aria-expanded={menu.open}
				aria-controls="menu"
				aria-label={menu.open ? 'Close menu' : 'Open menu'}
			>
				<span></span><span></span><span></span>
			</button>
			<a class="brand" href={resolve('/')}>paperus</a>
		</div>
		{#if session.user}
			<div class="row">
				<span class="muted">{session.user.username}</span>
				<button onclick={signOut}>Log out</button>
			</div>
		{/if}
	</header>

	<div class="body">
		<Sidebar />
		<main>{@render children()}</main>
	</div>
{/if}

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
		padding: 8px 16px;
		border-bottom: 1px solid var(--border);
		background: var(--surface);
	}
	.brand {
		color: var(--text);
		font-size: 1.15em;
		text-decoration: none;
	}
	.burger {
		display: grid;
		gap: 4px;
		padding: 9px 8px;
		border-color: transparent;
		background: none;
	}
	.burger:hover {
		background: var(--bg);
	}
	.burger span {
		display: block;
		width: 18px;
		height: 2px;
		border-radius: 1px;
		background: var(--text);
	}
	.body {
		display: flex;
		gap: 16px;
		padding: 16px;
		align-items: flex-start;
	}
	main {
		flex: 1;
		min-width: 0;
		max-width: 960px;
		margin: 0 auto;
	}
	main.login {
		padding: 16px;
	}
</style>
