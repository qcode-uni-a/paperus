<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { loadAdmin, SETTINGS } from '#lib/admin/data.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	const STORAGE_KEY = 'paperus.admin.menu';
	const NARROW = '(max-width: 720px)';

	// Wide screens: a sidebar, open unless the viewer collapsed it (remembered).
	// Narrow screens: a drawer over the content, closed until opened.
	let narrow = $state(matchMedia(NARROW).matches);
	let wideOpen = $state(readStoredOpen());
	let drawerOpen = $state(false);
	const open = $derived(narrow ? drawerOpen : wideOpen);

	function readStoredOpen(): boolean {
		try {
			return localStorage.getItem(STORAGE_KEY) !== 'closed';
		} catch {
			return true;
		}
	}

	function toggle() {
		if (narrow) {
			drawerOpen = !drawerOpen;
			return;
		}
		wideOpen = !wideOpen;
		try {
			localStorage.setItem(STORAGE_KEY, wideOpen ? 'open' : 'closed');
		} catch {
			// Storage may be blocked; the menu still works for this visit.
		}
	}

	$effect(() => {
		const query = matchMedia(NARROW);
		const update = () => (narrow = query.matches);
		query.addEventListener('change', update);
		return () => query.removeEventListener('change', update);
	});

	// Close the drawer after choosing an entry.
	$effect(() => {
		void page.url.pathname;
		drawerOpen = false;
	});

	$effect(() => {
		if (!session.user?.is_admin) return;
		loadAdmin();
		const timer = setInterval(loadAdmin, 3000);
		return () => clearInterval(timer);
	});

	const settingsPath = resolve('/admin/settings');
	const MAIN = [
		[resolve('/admin/users'), 'Users'],
		[resolve('/admin/jobs'), 'Jobs'],
		[settingsPath, 'Settings'],
		[resolve('/admin/server'), 'Server stats']
	] as const;

	function active(path: string): boolean {
		return page.url.pathname === path || page.url.pathname.startsWith(`${path}/`);
	}
</script>

<svelte:window
	onkeydown={(event) => {
		if (event.key === 'Escape' && narrow) drawerOpen = false;
	}}
/>

{#if !session.checked}
	<p class="muted">Loading…</p>
{:else if !session.user?.is_admin}
	<p class="muted">Only administrators can see this page.</p>
{:else}
	<div class="bar">
		<button
			class="burger"
			onclick={toggle}
			aria-expanded={open}
			aria-controls="admin-menu"
			aria-label={open ? 'Close menu' : 'Open menu'}
		>
			<span></span><span></span><span></span>
		</button>
		<span class="title">Administration</span>
	</div>

	<div class="admin" class:collapsed={!open}>
		{#if narrow && open}
			<button class="backdrop" aria-label="Close menu" onclick={() => (drawerOpen = false)}
			></button>
		{/if}
		<nav
			id="admin-menu"
			aria-label="Administration"
			class:drawer={narrow}
			class:open
			hidden={!open}
		>
			{#each MAIN as [path, label] (path)}
				<a href={path} class:current={active(path)}>{label}</a>
				{#if path === settingsPath && active(settingsPath)}
					{#each SETTINGS as [slug, sublabel] (slug)}
						{@const href = resolve('/admin/settings/[section]', { section: slug })}
						<a {href} class="sub" class:current={page.url.pathname === href}>{sublabel}</a>
					{/each}
				{/if}
			{/each}
		</nav>
		<div class="content">{@render children()}</div>
	</div>
{/if}

<style>
	.bar {
		display: flex;
		align-items: center;
		gap: 12px;
		margin-bottom: 16px;
	}
	.title {
		font-weight: 600;
	}
	.burger {
		display: grid;
		gap: 4px;
		padding: 9px 8px;
		border: 1px solid var(--border);
		background: var(--surface);
	}
	.burger span {
		display: block;
		width: 18px;
		height: 2px;
		border-radius: 1px;
		background: var(--text);
	}
	.admin {
		display: grid;
		grid-template-columns: 200px 1fr;
		gap: 24px;
		align-items: start;
	}
	.admin.collapsed {
		grid-template-columns: 1fr;
	}
	nav {
		display: grid;
		gap: 2px;
		position: sticky;
		top: 16px;
	}
	nav[hidden] {
		display: none;
	}
	nav a {
		padding: 6px 10px;
		border-radius: var(--radius);
		text-decoration: none;
		color: var(--text);
	}
	nav a:hover {
		background: var(--surface);
	}
	nav a.current {
		background: var(--surface);
		color: var(--accent);
		font-weight: 600;
	}
	nav a.sub {
		padding-left: 24px;
		font-size: 0.95em;
	}
	nav a.current:not(.sub):has(+ .sub) {
		background: none;
	}
	.content {
		min-width: 0;
	}
	.content :global(h1) {
		margin-top: 0;
	}

	/* Narrow screens: the menu slides over the content from the left. */
	nav.drawer {
		position: fixed;
		inset: 0 auto 0 0;
		z-index: 40;
		width: min(280px, 85vw);
		align-content: start;
		padding: 16px;
		overflow-y: auto;
		background: var(--bg);
		border-right: 1px solid var(--border);
		box-shadow: 4px 0 24px rgb(0 0 0 / 0.2);
	}
	nav.drawer a.current {
		background: var(--surface);
	}
	.backdrop {
		position: fixed;
		inset: 0;
		z-index: 39;
		border: none;
		border-radius: 0;
		padding: 0;
		background: rgb(0 0 0 / 0.35);
	}
	@media (max-width: 720px) {
		.admin {
			grid-template-columns: 1fr;
		}
	}
</style>
