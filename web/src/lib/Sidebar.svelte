<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import {
		mdiAccountGroupOutline,
		mdiAccountMultipleOutline,
		mdiArrowLeft,
		mdiBackupRestore,
		mdiBookshelf,
		mdiBriefcaseOutline,
		mdiCogOutline,
		mdiContentDuplicate,
		mdiFileQuestionOutline,
		mdiFolderCogOutline,
		mdiFolderMultipleOutline,
		mdiHistory,
		mdiNoteTextOutline,
		mdiServer,
		mdiShieldAccountOutline,
		mdiStarOutline,
		mdiTagMultipleOutline,
		mdiTrashCanOutline
	} from '@mdi/js';
	import { SETTINGS } from '#lib/admin/data.svelte.ts';
	import Icon from '#lib/Icon.svelte';
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

	// Collections and tags for pickers, reloaded when pages change them.
	$effect(() => {
		if (session.user && !inAdmin) loadOrganize();
	});

	const ADMIN = [
		[resolve('/admin/users'), 'Users', mdiAccountMultipleOutline],
		[resolve('/admin/jobs'), 'Jobs', mdiBriefcaseOutline],
		[settingsPath, 'Settings', mdiCogOutline],
		[resolve('/admin/backups'), 'Backups', mdiBackupRestore],
		[resolve('/admin/server'), 'Server stats', mdiServer]
	] as const;
	const onSettingsPage = $derived(page.url.pathname.startsWith(`${settingsPath}/`));

	const MAIN = [
		[library, 'Library', mdiBookshelf],
		[resolve('/recent'), 'Recent', mdiHistory],
		[resolve('/favourites'), 'Favourites', mdiStarOutline],
		[collectionsPath, 'Collections', mdiFolderMultipleOutline],
		[resolve('/notes'), 'Notes', mdiNoteTextOutline]
	] as const;
	const MANAGE = [
		[resolve('/manage/collections'), 'Collections', mdiFolderCogOutline],
		[resolve('/manage/tags'), 'Tags', mdiTagMultipleOutline],
		[resolve('/manage/groups'), 'Groups', mdiAccountGroupOutline],
		[resolve('/manage/duplicates'), 'Duplicates', mdiContentDuplicate],
		[resolve('/manage/unsorted'), 'Unsorted', mdiFileQuestionOutline],
		[resolve('/trash'), 'Trash', mdiTrashCanOutline]
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
		<a class="back" href={resolve('/')}><Icon path={mdiArrowLeft} /><span>Back to library</span></a>
		<span class="group">Administration</span>
		{#each ADMIN as [path, label, icon] (path)}
			<a href={path} class:current={active(path) && !(path === settingsPath && onSettingsPage)}
				><Icon path={icon} /><span>{label}</span></a
			>
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
		{#each MAIN as [path, label, icon] (path)}
			<a href={path} class:current={path === library ? onLibrary && !filtered : active(path)}
				><Icon path={icon} /><span>{label}</span></a
			>
			{#if path === collectionsPath}
				{#each organize.collections.filter((c) => c.pinned) as pinned (pinned.id)}
					{@const href = resolve('/collections/[id]', { id: pinned.id })}
					<a {href} class="sub" class:current={page.url.pathname === href}
						><span>{pinned.name}</span></a
					>
				{/each}
			{/if}
		{/each}

		<span class="group">Manage</span>
		{#each MANAGE as [path, label, icon] (path)}
			<a href={path} class:current={active(path)}><Icon path={icon} /><span>{label}</span></a>
		{/each}
		{#if session.user?.is_admin}
			<a href={adminPath}><Icon path={mdiShieldAccountOutline} /><span>Administration</span></a>
		{/if}
	{/if}
</nav>

<style>
	/* Like Immich: icons and labels, the current entry a rounded pill in the
	   accent colour, flush with the left edge. */
	nav {
		display: grid;
		align-content: start;
		gap: 2px;
		position: sticky;
		top: 72px;
		width: 248px;
		flex-shrink: 0;
		margin-left: -16px;
		padding-right: 12px;
	}
	nav[hidden] {
		display: none;
	}
	a {
		display: flex;
		align-items: center;
		gap: 16px;
		min-height: 44px;
		padding: 0 16px 0 24px;
		border-radius: 0 999px 999px 0;
		text-decoration: none;
		color: var(--ink);
		font-weight: 500;
	}
	a :global(svg) {
		color: var(--muted);
	}
	a:hover {
		background: var(--rail);
		color: var(--ink);
	}
	a.current {
		background: var(--accent-soft);
		color: var(--royal);
		font-weight: 650;
	}
	a.current :global(svg) {
		color: var(--royal);
	}
	a span {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	a.sub {
		min-height: 36px;
		padding-left: 60px;
		font-size: 0.94em;
		font-weight: 450;
		color: var(--muted);
	}
	a.sub.current {
		color: var(--royal);
	}
	a.back {
		color: var(--royal);
		margin-bottom: 8px;
	}
	a.back :global(svg) {
		color: var(--royal);
	}
	.group {
		margin: 20px 0 6px 24px;
		font-size: var(--step--1);
		font-weight: 600;
		color: var(--muted);
	}

	/* Narrow screens: slides over the content from the left. */
	nav.drawer {
		position: fixed;
		inset: 0 auto 0 0;
		z-index: 40;
		width: min(300px, 85vw);
		margin-left: 0;
		padding: 16px 12px 16px 0;
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
