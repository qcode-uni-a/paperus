<script lang="ts">
	import '../app.css';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import DropZone from '#lib/DropZone.svelte';
	import { menu } from '#lib/menu.svelte.ts';
	import { loadUser, session } from '#lib/session.svelte.ts';
	import Sidebar from '#lib/Sidebar.svelte';
	import ThemeToggle from '#lib/ThemeToggle.svelte';
	import AddMenu from '#lib/AddMenu.svelte';
	import UploadTray from '#lib/UploadTray.svelte';
	import UserMenu from '#lib/UserMenu.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	const onLoginPage = $derived(page.url.pathname === resolve('/login'));

	$effect(() => {
		if (!session.checked && !onLoginPage) loadUser();
	});

	$effect(() => menu.watch());
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
			<a class="brand" href={resolve('/')}><span class="highlight">paperus</span></a>
		</div>
		<div class="row">
			{#if session.user}<AddMenu />{/if}
			<ThemeToggle />
			{#if session.user}<UserMenu />{/if}
		</div>
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
		position: sticky;
		top: 0;
		z-index: 30;
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: var(--gap);
		height: 56px;
		padding: 0 12px 0 8px;
		border-bottom: 1px solid var(--rule);
		background: color-mix(in srgb, var(--paper) 92%, transparent);
		backdrop-filter: blur(8px);
	}
	.brand {
		font-family: var(--serif);
		font-size: var(--step-2);
		font-weight: 650;
		letter-spacing: -0.02em;
		color: var(--ink);
		text-decoration: none;
	}
	.brand .highlight {
		padding: 0 0.25em;
	}
	.burger {
		display: grid;
		place-content: center;
		gap: 4px;
		width: 40px;
		height: 40px;
		padding: 0;
		border-color: transparent;
		background: none;
	}
	.burger:hover:not(:disabled) {
		background: var(--rail);
		border-color: transparent;
	}
	.burger span {
		display: block;
		width: 18px;
		height: 2px;
		border-radius: 1px;
		background: var(--ink);
	}
	.body {
		display: flex;
		gap: 24px;
		padding: 24px 16px;
		align-items: flex-start;
	}
	main {
		flex: 1;
		min-width: 0;
		max-width: 920px;
		margin: 0 auto;
	}
	main.login {
		padding: 16px;
	}
	@media (max-width: 720px) {
		.body {
			padding: 16px;
		}
	}
</style>
