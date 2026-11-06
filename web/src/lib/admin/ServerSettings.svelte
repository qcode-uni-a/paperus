<script lang="ts">
	import { admin } from '#lib/admin/data.svelte.ts';
	import { saveConfig } from '#lib/admin/config.svelte.ts';
	import SectionButtons from '#lib/admin/SectionButtons.svelte';
	import SettingRow from '#lib/admin/SettingRow.svelte';

	const config = $derived(admin.config);
	let publicUrl = $state('');
	let email = $state('');
	let uploadMb = $state(512);
	let openAccess = $state(false);
	let saving = $state(false);

	function reset() {
		publicUrl = config?.public_url ?? '';
		email = config?.contact_email ?? '';
		uploadMb = config?.max_upload_mb ?? 512;
		openAccess = config?.open_access_auto ?? false;
	}
	// The page reloads its data every few seconds: start over only when the
	// saved values change (not while someone is typing).
	let seen = '';
	$effect(() => {
		if (!config) return;
		const saved = JSON.stringify([
			config.public_url,
			config.contact_email,
			config.max_upload_mb,
			config.open_access_auto
		]);
		if (saved === seen) return;
		seen = saved;
		reset();
	});

	const changed = $derived(
		!!config &&
			(publicUrl !== (config.public_url ?? '') ||
				email !== (config.contact_email ?? '') ||
				uploadMb !== config.max_upload_mb ||
				openAccess !== (config.open_access_auto ?? false))
	);

	async function save() {
		saving = true;
		await saveConfig(
			{
				public_url: publicUrl.trim() || null,
				contact_email: email.trim() || null,
				max_upload_mb: uploadMb,
				open_access_auto: openAccess
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
	description="Sent to Crossref and other services when looking up details; they ask for one, to reach whoever runs this installation. Unpaywall, which knows open-access copies of papers (Manage → Missing), answers only with one."
>
	<input id="contact-email" type="email" bind:value={email} placeholder="library@uni-example.de" />
</SettingRow>
<SettingRow
	id="open-access"
	title="Open-access copies"
	description="Papers added without a file (by hand, with the browser extension, by AI assistants or in an import) get an open-access copy by themselves, in the background: their arXiv version (found via OpenAlex), else one Unpaywall knows (needs the contact email). Their DOIs are sent there. Manage → Missing does the same on request."
>
	<label class="check"
		><input id="open-access" type="checkbox" bind:checked={openAccess} /> Download them by themselves</label
	>
</SettingRow>
<SettingRow
	id="upload-limit"
	title="Largest upload"
	description="In MB, for each uploaded file (also each file of an import). A reverse proxy may have its own limit."
>
	<input id="upload-limit" type="number" min="1" max="100000" bind:value={uploadMb} />
</SettingRow>
<SectionButtons {changed} {saving} onreset={reset} onsave={save} />

<style>
	.check {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.check input {
		width: auto;
		margin: 0;
	}
</style>
