<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import {
		mdiAccountEditOutline,
		mdiAccountGroupOutline,
		mdiAccountMultipleOutline,
		mdiArchiveOutline,
		mdiArrowLeft,
		mdiBackupRestore,
		mdiBookshelf,
		mdiBriefcaseOutline,
		mdiCogOutline,
		mdiContentDuplicate,
		mdiFileDownloadOutline,
		mdiFileQuestionOutline,
		mdiFolderCogOutline,
		mdiFolderMultipleOutline,
		mdiHistory,
		mdiNoteTextOutline,
		mdiServer,
		mdiStarOutline,
		mdiTagMultipleOutline,
		mdiTrashCanOutline
	} from '@mdi/js';
	import { manageCounts } from '#lib/api/client.ts';
	import type { ManageCounts } from '#lib/api/generated/types.gen.ts';
	import Icon from '#lib/Icon.svelte';
	import StorageMeter from '#lib/StorageMeter.svelte';
	import { menu } from '#lib/menu.svelte.ts';
	import { loadOrganize, organize } from '#lib/organize.svelte.ts';
	import { session } from '#lib/session.svelte.ts';

	// Inside the administration, its menu replaces the normal one.
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
		[resolve('/manage/authors'), 'Authors', mdiAccountEditOutline],
		[resolve('/manage/groups'), 'Groups', mdiAccountGroupOutline],
		[resolve('/manage/duplicates'), 'Duplicates', mdiContentDuplicate],
		[resolve('/manage/unsorted'), 'Unsorted', mdiFileQuestionOutline],
		[resolve('/manage/missing'), 'Missing', mdiFileDownloadOutline],
		[resolve('/archive'), 'Archive', mdiArchiveOutline],
		[resolve('/trash'), 'Trash', mdiTrashCanOutline]
	] as const;

	// How many duplicates, unsorted papers (or unreadable files), papers
	// without a file and authors to look at wait:
	// after each change of page (one may just have resolved some) and every
	// minute.
	let counts = $state<ManageCounts | null>(null);
	const refreshCounts = () => manageCounts().then(({ data }) => (counts = data ?? counts));
	$effect(() => {
		void page.url.pathname;
		if (session.user && !inAdmin) refreshCounts();
	});
	$effect(() => {
		if (!session.user) return;
		const timer = setInterval(refreshCounts, 60_000);
		return () => clearInterval(timer);
	});
	const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
	const badges = $derived<Record<string, { count: number; title: string }>>({
		[resolve('/manage/duplicates')]: {
			count: counts?.duplicates ?? 0,
			title: count(counts?.duplicates ?? 0, 'possible duplicate', 'possible duplicates')
		},
		[resolve('/manage/unsorted')]: {
			count: (counts?.unsorted ?? 0) + (counts?.unreadable ?? 0),
			title: [
				counts?.unsorted
					? count(counts.unsorted, 'paper without details', 'papers without details')
					: '',
				counts?.unreadable ? count(counts.unreadable, 'unreadable file', 'unreadable files') : ''
			]
				.filter(Boolean)
				.join(', ')
		},
		[resolve('/manage/missing')]: {
			count: (counts?.missing ?? 0) + (counts?.missing_journal ?? 0),
			title: [
				counts?.missing
					? count(counts.missing, 'paper without a file', 'papers without a file')
					: '',
				counts?.missing_journal
					? count(
							counts.missing_journal,
							'paper with only its preprint',
							'papers with only their preprint'
						)
					: ''
			]
				.filter(Boolean)
				.join(', ')
		},
		[resolve('/manage/authors')]: {
			count: (counts?.authors_to_check ?? 0) + (counts?.authors_likely ?? 0),
			title: [
				counts?.authors_to_check
					? count(counts.authors_to_check, 'author to check', 'authors to check')
					: '',
				counts?.authors_likely
					? count(counts.authors_likely, 'pair probably the same', 'pairs probably the same')
					: ''
			]
				.filter(Boolean)
				.join(', ')
		}
	});

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
			<a href={path} class:current={active(path)}><Icon path={icon} /><span>{label}</span></a>
		{/each}
	{:else}
		<div class="part">
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
		</div>

		<!-- At the bottom of the window, below what is used every day. -->
		<div class="part bottom">
			<span class="group">Manage</span>
			{#each MANAGE as [path, label, icon] (path)}
				{@const badge = badges[path]}
				<a href={path} class:current={active(path)}
					><Icon path={icon} /><span>{label}</span>
					{#if badge?.count}<span class="count" title={badge.title}
							>{badge.count}<span class="visually-hidden">: {badge.title}</span></span
						>{/if}</a
				>
			{/each}
			{#if session.user}<StorageMeter />{/if}
		</div>
	{/if}
</nav>

<style>
	/* Icons and labels, the current entry a rounded pill in the
	   accent colour, flush with the left edge. */
	nav {
		display: flex;
		flex-direction: column;
		gap: 2px;
		position: sticky;
		top: var(--header-height, 72px);
		/* The window's height below the header, so Manage sits at the
		   bottom; scrolls when the window is too short for all. */
		height: calc(100dvh - var(--header-height, 72px));
		overflow-y: auto;
		padding-bottom: 16px;
		width: 248px;
		flex-shrink: 0;
		margin-left: -16px;
		padding-right: 12px;
	}
	nav[hidden] {
		display: none;
	}
	.part {
		display: grid;
		gap: 2px;
	}
	.bottom {
		margin-top: auto;
		padding-top: 12px;
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
	/* How many wait there, at the right end of the entry. */
	a .count {
		margin-left: auto;
		min-width: 22px;
		padding: 1px 7px;
		border-radius: 999px;
		background: var(--accent-soft);
		color: var(--royal);
		font-size: var(--step--1);
		font-weight: 650;
		text-align: center;
		font-variant-numeric: tabular-nums;
	}
	a.current .count {
		background: var(--surface);
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
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
		height: auto;
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
