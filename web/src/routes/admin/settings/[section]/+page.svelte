<script lang="ts">
	import MlSettings from '#lib/admin/MlSettings.svelte';
	import Planned from '#lib/admin/Planned.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	// What each section is meant to hold, until it is built.
	const PLANNED: Record<string, string[]> = {
		integrity: [
			'Files in the database whose contents are missing from storage',
			'Stored contents that no file uses any more (to clean up)',
			'Verifying stored contents against their SHA-256'
		],
		jobs: [
			'How many jobs of each kind run at the same time',
			'When the periodic checks run (pending files, missing vectors)'
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
		trash: ['Days until the trash is emptied automatically', 'Emptying the trash now'],
		users: [
			'Creating users and resetting passwords (now: paperus user create)',
			'Making users administrators',
			'What happens to a removed user’s items and notes'
		],
		authentication: [
			'Password login on or off',
			'University login (OIDC / SAML via an identity provider)',
			'Session length'
		]
	};
</script>

{#if data.section === 'ml'}
	<MlSettings />
{:else}
	<Planned title={data.title} items={PLANNED[data.section] ?? []} />
{/if}
