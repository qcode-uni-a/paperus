<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { SETTINGS } from '#lib/admin/data.svelte.ts';
	import { menu } from '#lib/menu.svelte.ts';
	import { session } from '#lib/session.svelte.ts';

	// Like Immich: inside the administration, its menu replaces the normal one.
	const adminPath = resolve('/admin');
	const settingsPath = resolve('/admin/settings');
	const inAdmin = $derived(active(adminPath));

	const MAIN = [
		[resolve('/'), 'Library'],
		[resolve('/trash'), 'Trash']
	] as const;
	const ADMIN = [
		[resolve('/admin/users'), 'Users'],
		[resolve('/admin/jobs'), 'Jobs'],
		[settingsPath, 'Settings'],
		[resolve('/admin/server'), 'Server stats']
	] as const;

	function active(path: string): boolean {
		const current = page.url.pathname;
		return current === path || (path !== '/' && current.startsWith(`${path}/`));
	}

	// Close the drawer after choosing an entry.
	$effect(() => {
		void page.url.pathname;
		menu.closeDrawer();
	});
</script>

<svelte:window
	onkeydown={(event) => {
		if (event.key === 'Escape') menu.closeDrawer();
	}}
/>

{#if menu.narrow && menu.open}
	<button class="backdrop" aria-label="Close menu" onclick={() => menu.closeDrawer()}></button>
{/if}

<nav id="menu" aria-label="Menu" class:drawer={menu.narrow} hidden={!menu.open}>
	{#if inAdmin}
		<a class="back" href={resolve('/')}>← Back to library</a>
		<span class="group muted">Administration</span>
		{#each ADMIN as [path, label] (path)}
			<a href={path} class:current={active(path)}>{label}</a>
			{#if path === settingsPath && active(settingsPath)}
				{#each SETTINGS as [slug, sublabel] (slug)}
					{@const href = resolve('/admin/settings/[section]', { section: slug })}
					<a {href} class="sub" class:current={page.url.pathname === href}>{sublabel}</a>
				{/each}
			{/if}
		{/each}
	{:else}
		{#each MAIN as [path, label] (path)}
			<a href={path} class:current={active(path)}>{label}</a>
		{/each}
		{#if session.user?.is_admin}
			<a href={adminPath}>Administration</a>
		{/if}
	{/if}
</nav>

<style>
	nav {
		display: grid;
		align-content: start;
		gap: 2px;
		position: sticky;
		top: 16px;
		width: 210px;
	}
	nav[hidden] {
		display: none;
	}
	a {
		padding: 7px 12px;
		border-radius: var(--radius);
		text-decoration: none;
		color: var(--text);
	}
	a:hover {
		background: var(--surface);
	}
	a.current {
		background: var(--surface);
		color: var(--accent);
		font-weight: 600;
	}
	a.current:not(.sub):has(+ .sub) {
		background: none;
	}
	a.sub {
		padding-left: 26px;
		font-size: 0.95em;
	}
	a.back {
		color: var(--muted);
		margin-bottom: 8px;
	}
	.group {
		margin: 4px 12px;
		font-size: 0.8em;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	/* Narrow screens: slides over the content from the left. */
	nav.drawer {
		position: fixed;
		inset: 0 auto 0 0;
		z-index: 40;
		width: min(280px, 85vw);
		padding: 16px;
		overflow-y: auto;
		background: var(--bg);
		border-right: 1px solid var(--border);
		box-shadow: 4px 0 24px rgb(0 0 0 / 0.2);
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
</style>
