<script lang="ts">
	import { admin } from '#lib/admin/data.svelte.ts';
	import { saveConfig } from '#lib/admin/config.svelte.ts';
	import SectionButtons from '#lib/admin/SectionButtons.svelte';
	import SettingRow from '#lib/admin/SettingRow.svelte';
	import {
		DATE_FORMATS,
		formatDateTime,
		formatLongDate,
		type DateFormat
	} from '#lib/dates.svelte.ts';
	import { session } from '#lib/session.svelte.ts';

	const config = $derived(admin.config);
	let publicUrl = $state('');
	let email = $state('');
	let uploadMb = $state(512);
	let openAccess = $state(false);
	let findPublished = $state(true);
	let findReferences = $state(true);
	let findAuthors = $state(true);
	let dates = $state<DateFormat>('browser');
	const now = new Date();
	let saving = $state(false);

	function reset() {
		publicUrl = config?.public_url ?? '';
		email = config?.contact_email ?? '';
		uploadMb = config?.max_upload_mb ?? 512;
		openAccess = config?.open_access_auto ?? false;
		findPublished = config?.find_published ?? true;
		findReferences = config?.find_references ?? true;
		findAuthors = config?.find_authors ?? true;
		dates = config?.date_format ?? 'browser';
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
			config.open_access_auto,
			config.find_published,
			config.find_references,
			config.find_authors,
			config.date_format
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
				openAccess !== (config.open_access_auto ?? false) ||
				findPublished !== (config.find_published ?? true) ||
				findReferences !== (config.find_references ?? true) ||
				findAuthors !== (config.find_authors ?? true) ||
				dates !== (config.date_format ?? 'browser'))
	);

	async function save() {
		saving = true;
		const saved = await saveConfig(
			{
				public_url: publicUrl.trim() || null,
				contact_email: email.trim() || null,
				max_upload_mb: uploadMb,
				open_access_auto: openAccess,
				find_published: findPublished,
				find_references: findReferences,
				find_authors: findAuthors,
				date_format: dates
			},
			'Server settings'
		);
		// One's own pages follow right away; others' on their next visit.
		if (saved && session.user) session.user.date_format = dates;
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
	id="find-published"
	title="Published versions"
	description="Preprints get their published version by themselves: paperus asks arXiv (the DOI the authors entered) and OpenAlex, a few dozen papers an hour, each at most once a month, and adds a version only if its title matches. It is then the one shown and cited; its PDF comes with the open-access copies below, or under Manage → Missing."
>
	<label class="check"
		><input id="find-published" type="checkbox" bind:checked={findPublished} /> Look for them</label
	>
</SettingRow>
<SettingRow
	id="find-references"
	title="Reference lists"
	description="Each paper's reference list, shown on its page with links to the papers in the library (and which papers here cite it): from arXiv's LaTeX source for arXiv papers, else from Crossref by the DOI, else read from the PDF. A few dozen papers an hour, and each paper once its file is read. Only DOIs and arXiv IDs are sent; looking a single reference up on Crossref is left to the person."
>
	<label class="check"
		><input id="find-references" type="checkbox" bind:checked={findReferences} /> Look for them</label
	>
</SettingRow>
<SettingRow
	id="find-authors"
	title="Authors"
	description="Who the papers' authors are: OpenAlex gives each author's id, ORCID iD and affiliation on the paper, so people with the same name are told apart and their papers come together (Manage → Authors). About a thousand papers an hour, each once; only the papers' DOIs are sent."
>
	<label class="check"
		><input id="find-authors" type="checkbox" bind:checked={findAuthors} /> Look them up</label
	>
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
	title="Dates and times"
	description="How the website shows dates and times, for everyone. Times are in each person's own time zone."
>
	<fieldset class="choice">
		<legend class="visually-hidden">Dates and times</legend>
		{#each DATE_FORMATS as [format, name] (format)}
			<label
				><input type="radio" bind:group={dates} value={format} />
				<span
					>{name}<small>{formatDateTime(now, format)} · {formatLongDate(now, format)}</small></span
				></label
			>
		{/each}
	</fieldset>
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
	.choice {
		display: grid;
		gap: 6px;
		margin: 0;
		padding: 0;
		border: none;
	}
	.choice label {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.choice input {
		width: auto;
		margin: 0;
	}
	.choice small {
		display: block;
		color: var(--muted);
		font-size: var(--step--1);
	}
</style>
