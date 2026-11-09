<script lang="ts">
	import '../app.css';
	import { asset, resolve } from '$app/paths';
	import { page } from '$app/state';
	import DropZone from '#lib/DropZone.svelte';
	import OwnerHint from '#lib/OwnerHint.svelte';
	import { menu } from '#lib/menu.svelte.ts';
	import { loadUser, session } from '#lib/session.svelte.ts';
	import SearchBar from '#lib/SearchBar.svelte';
	import Sidebar from '#lib/Sidebar.svelte';
	import ThemeToggle from '#lib/ThemeToggle.svelte';
	import NotificationBell from '#lib/NotificationBell.svelte';
	import AddMenu from '#lib/AddMenu.svelte';
	import UploadTray from '#lib/UploadTray.svelte';
	import Toasts from '#lib/Toasts.svelte';
	import UserMenu from '#lib/UserMenu.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	// The login, first-start and app-connecting pages stand alone, without
	// menu or header.
	const onLoginPage = $derived(
		page.url.pathname === resolve('/login') ||
			page.url.pathname === resolve('/setup') ||
			page.url.pathname === resolve('/oauth/authorize')
	);

	$effect(() => {
		if (!session.checked && !onLoginPage) loadUser();
	});

	$effect(() => menu.watch());

	// The header's height (two rows on phones), for what sticks below it.
	let headerHeight = $state(72);
	$effect(() => {
		document.documentElement.style.setProperty('--header-height', `${headerHeight}px`);
	});

	// No search where it is not about finding papers: the administration (the
	// installation, not the library) and a paper being read.
	const noSearch = $derived(
		page.url.pathname.startsWith(resolve('/admin')) || page.route.id === '/items/[id]'
	);
</script>

<svelte:head>
	<title>paperus</title>
</svelte:head>

{#if onLoginPage}
	<main class="login">{@render children()}</main>
{:else}
	<header bind:offsetHeight={headerHeight}>
		<div class="start">
			<button
				class="burger"
				onclick={() => menu.toggle()}
				aria-expanded={menu.open}
				aria-controls="menu"
				aria-label={menu.open ? 'Close menu' : 'Open menu'}
			>
				<span></span><span></span><span></span>
			</button>
			<a class="brand" href={resolve('/')}
				><img src={asset('favicon.svg')} alt="" width="30" height="30" />paperus</a
			>
		</div>
		{#if session.user && !noSearch}<div class="find"><SearchBar /></div>{:else}<span class="spacer"
			></span>{/if}
		<div class="end">
			{#if session.user}<AddMenu /><NotificationBell />{/if}
			<span class="theme"><ThemeToggle /></span>
			{#if session.user}<UserMenu />{/if}
		</div>
	</header>

	<div class="body" class:menu-closed={!menu.narrow && !menu.open}>
		<Sidebar />
		<main>{@render children()}</main>
	</div>
{/if}

{#if session.user && !onLoginPage}
	<DropZone />
	<UploadTray />
	<Toasts />
	<OwnerHint />
{/if}

<style>
	/* The logo over the menu, a wide search in the middle,
	   actions at the end; on phones the search takes a row of its own. */
	header {
		position: sticky;
		top: 0;
		z-index: 30;
		display: grid;
		/* The search starts where the page does, next to the menu. */
		grid-template-columns: 248px minmax(0, 1fr) auto;
		align-items: center;
		gap: 8px 16px;
		min-height: 72px;
		padding: 0 16px 0 8px;
		border-bottom: 1px solid var(--rule);
		background: color-mix(in srgb, var(--paper) 92%, transparent);
		backdrop-filter: blur(8px);
	}
	.start,
	.end {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.end {
		justify-content: flex-end;
	}
	.find {
		max-width: 720px;
	}
	/* The menu is a drawer (lib/menu.svelte.ts): no sidebar to line up with. */
	@media (max-width: 900px) {
		header {
			grid-template-columns: auto minmax(0, 1fr) auto;
		}
	}
	/* On a phone the bell takes the theme button's place (the theme is in
	   Settings too). */
	@media (max-width: 520px) {
		.theme {
			display: none;
		}
	}
	@media (max-width: 720px) {
		header {
			grid-template-columns: 1fr auto;
			padding: 8px 12px 10px 4px;
		}
		.spacer {
			display: none;
		}
		.find {
			grid-column: 1 / -1;
			grid-row: 2;
			max-width: none;
			padding-left: 8px;
		}
	}
	.brand {
		font-family: var(--serif);
		font-size: var(--step-2);
		font-weight: 650;
		letter-spacing: -0.02em;
		color: var(--ink);
		text-decoration: none;
	}
	.brand {
		display: inline-flex;
		align-items: center;
		gap: 8px;
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
		padding: 20px 16px;
		align-items: flex-start;
	}
	main {
		flex: 1;
		min-width: 0;
		max-width: 1040px;
	}
	/* With the menu closed, the page takes its room (the menu's 248px and
	   the gap) instead of leaving it empty on the right. */
	.menu-closed main {
		max-width: calc(1040px + 248px + 24px);
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
