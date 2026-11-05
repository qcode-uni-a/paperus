<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { SETTINGS } from '#lib/admin/data.svelte.ts';
	import { menu } from '#lib/menu.svelte.ts';
	import { loadOrganize, organize } from '#lib/organize.svelte.ts';
	import { session } from '#lib/session.svelte.ts';

	// Like Immich: inside the administration, its menu replaces the normal one.
	const adminPath = resolve('/admin');
	const settingsPath = resolve('/admin/settings');
	// Only admins see the administration menu, even when opening its address.
	const inAdmin = $derived(active(adminPath) && Boolean(session.user?.is_admin));

	const library = resolve('/');
	const collectionsPath = resolve('/collections');
	const params = $derived(page.url.searchParams);
	const filtered = $derived(params.has('collection') || params.has('tag'));
	const onLibrary = $derived(page.url.pathname === library);

	// Collections and tags, reloaded when other pages change them.
	$effect(() => {
		if (session.user && !inAdmin) loadOrganize();
	});

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
		<span class="group">Administration</span>
		{#each ADMIN as [path, label] (path)}
			<a href={path} class:current={active(path)}><span>{label}</span></a>
			{#if path === settingsPath && active(settingsPath)}
				{#each SETTINGS as [slug, sublabel] (slug)}
					{@const href = resolve('/admin/settings/[section]', { section: slug })}
					<a {href} class="sub" class:current={page.url.pathname === href}
						><span>{sublabel}</span></a
					>
				{/each}
			{/if}
		{/each}
	{:else}
		<a href={library} class:current={onLibrary && !filtered}><span>Library</span></a>

		<a href={collectionsPath} class:current={active(collectionsPath)}><span>Collections</span></a>

		{#if organize.tags.length}
			<span class="group section">Tags</span>
			<div class="tags">
				{#each organize.tags as tag (tag.id)}
					<a
						class="tag"
						href="{library}?tag={tag.id}"
						class:current={onLibrary && params.getAll('tag').includes(tag.id)}
						>{tag.name}<small>{tag.count}</small></a
					>
				{/each}
			</div>
		{/if}

		<div class="bottom">
			<a href={resolve('/trash')} class:current={active(resolve('/trash'))}><span>Trash</span></a>
			{#if session.user?.is_admin}
				<a href={adminPath}><span>Administration</span></a>
			{/if}
		</div>
	{/if}
</nav>

<style>
	nav {
		display: grid;
		align-content: start;
		gap: 2px;
		position: sticky;
		top: 80px;
		width: 200px;
		flex-shrink: 0;
	}
	nav[hidden] {
		display: none;
	}
	a {
		padding: 7px 10px;
		border-radius: var(--radius);
		text-decoration: none;
		color: var(--ink);
	}
	a:hover {
		background: var(--rail);
		color: var(--ink);
	}
	/* The current entry gets the highlighter, like a marked line in a paper. */
	a.current span {
		font-weight: 650;
		color: var(--on-highlighter);
		background: linear-gradient(
			100deg,
			transparent 0.15em,
			var(--highlighter) 0.3em,
			var(--highlighter) calc(100% - 0.3em),
			transparent calc(100% - 0.1em)
		);
		background-size: 100% 70%;
		background-position: 0 75%;
		background-repeat: no-repeat;
		padding: 0 0.3em;
		margin: 0 -0.3em;
		border-radius: 0.4em 0.2em 0.5em 0.25em;
	}
	a.current:not(.sub):has(+ .sub) span {
		background: none;
		color: var(--ink);
	}
	a.sub {
		padding-left: 24px;
		font-size: 0.95em;
		color: var(--muted);
	}
	.section {
		margin-top: 14px;
	}
	small {
		color: var(--faint);
		font-size: var(--step--1);
	}
	.tags {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 6px;
		padding: 4px 6px 0;
	}
	a.tag {
		display: inline-flex;
		gap: 5px;
		align-items: baseline;
		padding: 2px 9px;
		border-radius: 999px;
		background: var(--rail);
		font-size: 0.9em;
	}
	a.tag.current {
		background: var(--highlighter);
		color: var(--on-highlighter);
	}
	.bottom {
		display: grid;
		gap: 2px;
		margin-top: 16px;
		padding-top: 10px;
		border-top: 1px solid var(--rule);
	}
	a.back {
		color: var(--royal);
		margin-bottom: 12px;
	}
	.group {
		margin: 4px 10px 2px;
		font-family: var(--serif);
		font-weight: 600;
		color: var(--muted);
	}

	/* Narrow screens: slides over the content from the left. */
	nav.drawer {
		position: fixed;
		inset: 0 auto 0 0;
		z-index: 40;
		width: min(280px, 85vw);
		padding: 20px 16px;
		overflow-y: auto;
		background: var(--paper);
		border-right: 1px solid var(--rule);
		box-shadow: var(--shadow);
	}
	.backdrop {
		position: fixed;
		inset: 0;
		z-index: 39;
		border: none;
		border-radius: 0;
		padding: 0;
		background: rgb(10 14 30 / 0.4);
	}
</style>
