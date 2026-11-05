<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { SETTINGS } from '#lib/admin/data.svelte.ts';
	import AuthSettings from '#lib/admin/AuthSettings.svelte';
	import UsersSettings from '#lib/admin/UsersSettings.svelte';
	import JobSettings from '#lib/admin/JobSettings.svelte';
	import IntegritySettings from '#lib/admin/IntegritySettings.svelte';
	import LoggingSettings from '#lib/admin/LoggingSettings.svelte';
	import MlSettings from '#lib/admin/MlSettings.svelte';
	import ServerSettings from '#lib/admin/ServerSettings.svelte';
	import TrashSettings from '#lib/admin/TrashSettings.svelte';
	import SettingSection from '#lib/admin/SettingSection.svelte';

	/** All settings on one page, all closed at first, each opened as needed;
	 * the open ones are in the address (?open=ml,trash). */
	const open = $derived((page.url.searchParams.get('open') ?? '').split(',').filter(Boolean));

	function toggle(slug: string, opened: boolean) {
		const next = opened ? [...open, slug] : open.filter((s) => s !== slug);
		const url = new URL(page.url.href);
		url.searchParams.set('open', next.join(','));
		goto(`${url.pathname}${url.search}`, { replaceState: true, reset: false });
	}

	// What each section is meant to hold, until it is built.
	const PLANNED: Record<string, string[]> = {
		integrity: [
			'Files in the database whose contents are missing from storage',
			'Stored contents that no file uses any more (to clean up)',
			'Verifying stored contents against their SHA-256'
		],
		logging: ['Log level of the server and worker', 'Where logs go (console, file)'],
		server: [
			'Public address of the server (for links and the browser extension)',
			'Contact email sent to Crossref and other metadata services',
			'Upload size limit'
		],
		'storage-template': [
			'An optional readable copy of the library on disk, e.g. {year}/{first author} - {title}.pdf',
			'Files themselves stay stored once by content (SHA-256)'
		],
		trash: ['Days until the trash is emptied automatically', 'Emptying the trash now']
	};
</script>

<svelte:head><title>Settings · paperus</title></svelte:head>

<h1>Settings</h1>
<p class="muted lead">
	Settings for the whole installation. Each person’s own settings are under their name (top right).
</p>

<div class="sections">
	{#each SETTINGS as [slug, title, subtitle, later] (slug)}
		<SettingSection
			id={slug}
			{title}
			{subtitle}
			{later}
			open={open.includes(slug)}
			ontoggle={(opened) => toggle(slug, opened)}
		>
			{#if slug === 'ml'}
				<MlSettings />
			{:else if slug === 'integrity'}
				<IntegritySettings />
			{:else if slug === 'users'}
				<UsersSettings />
			{:else if slug === 'authentication'}
				<AuthSettings />
			{:else if slug === 'jobs'}
				<JobSettings />
			{:else if slug === 'server'}
				<ServerSettings />
			{:else if slug === 'trash'}
				<TrashSettings />
			{:else if slug === 'logging'}
				<LoggingSettings />
			{:else}
				<p class="muted">Not available yet. Planned for this section:</p>
				<ul class="planned">
					{#each PLANNED[slug] ?? [] as item (item)}<li>{item}</li>{/each}
				</ul>
			{/if}
		</SettingSection>
	{/each}
</div>

<style>
	h1 {
		margin: 0 0 4px;
	}
	.lead {
		margin: 0 0 20px;
	}
	.sections {
		display: grid;
		gap: 12px;
		max-width: 900px;
	}
	.planned {
		margin: 0;
		padding-left: 20px;
		color: var(--muted);
	}
</style>
