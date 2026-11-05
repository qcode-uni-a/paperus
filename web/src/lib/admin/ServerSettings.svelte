<script lang="ts">
	import { admin } from '#lib/admin/data.svelte.ts';
	import { saveConfig } from '#lib/admin/config.svelte.ts';
	import SectionButtons from '#lib/admin/SectionButtons.svelte';
	import SettingRow from '#lib/admin/SettingRow.svelte';

	const config = $derived(admin.config);
	let publicUrl = $state('');
	let email = $state('');
	let uploadMb = $state(512);
	let saving = $state(false);

	function reset() {
		publicUrl = config?.public_url ?? '';
		email = config?.contact_email ?? '';
		uploadMb = config?.max_upload_mb ?? 512;
	}
	// The page reloads its data every few seconds: start over only when the
	// saved values change (not while someone is typing).
	let seen = '';
	$effect(() => {
		if (!config) return;
		const saved = JSON.stringify([config.public_url, config.contact_email, config.max_upload_mb]);
		if (saved === seen) return;
		seen = saved;
		reset();
	});

	const changed = $derived(
		!!config &&
			(publicUrl !== (config.public_url ?? '') ||
				email !== (config.contact_email ?? '') ||
				uploadMb !== config.max_upload_mb)
	);

	async function save() {
		saving = true;
		await saveConfig(
			{
				public_url: publicUrl.trim() || null,
				contact_email: email.trim() || null,
				max_upload_mb: uploadMb
			},
			'Server settings'
		);
		saving = false;
	}
</script>

<SettingRow
	id="public-url"
	title="Public address"
	description="The address people use, e.g. https://papers.uni-example.de. For links the server makes (for AI assistants); empty: the address each request came to."
>
	<input id="public-url" type="url" bind:value={publicUrl} placeholder="https://…" />
</SettingRow>
<SettingRow
	id="contact-email"
	title="Contact email"
	description="Sent to Crossref and other services when looking up details; they ask for one, to reach whoever runs this installation."
>
	<input id="contact-email" type="email" bind:value={email} placeholder="library@uni-example.de" />
</SettingRow>
<SettingRow
	id="upload-limit"
	title="Largest upload"
	description="In MB, for each uploaded file (also each file of an import). A reverse proxy may have its own limit."
>
	<input id="upload-limit" type="number" min="1" max="100000" bind:value={uploadMb} />
</SettingRow>
<SectionButtons {changed} {saving} onreset={reset} onsave={save} />
