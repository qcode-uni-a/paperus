<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { admin, SETTINGS } from '#lib/admin/data.svelte.ts';
	import AuthSettings from '#lib/admin/AuthSettings.svelte';
	import CopySettings from '#lib/admin/CopySettings.svelte';
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
</script>

<svelte:head><title>Settings · paperus</title></svelte:head>

<h1>Settings</h1>
<p class="muted lead">
	Settings for the whole installation. Each person’s own settings are under their name (top right).
</p>

<div class="sections">
	{#each SETTINGS as { slug, title, subtitle, icon, status } (slug)}
		<SettingSection
			id={slug}
			{title}
			{subtitle}
			{icon}
			status={admin.config ? status(admin.config) : null}
			open={open.includes(slug)}
			ontoggle={(opened) => toggle(slug, opened)}
		>
			{#if slug === 'ml'}
				<MlSettings />
			{:else if slug === 'integrity'}
				<IntegritySettings />
			{:else if slug === 'storage-template'}
				<CopySettings />
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
</style>
