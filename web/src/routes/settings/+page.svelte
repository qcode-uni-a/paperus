<script lang="ts">
	import {
		changePassword,
		errorMessage,
		loginMethods,
		setDefaultLibrary,
		setNameFormat,
		setProfile
	} from '#lib/api/client.ts';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import {
		mdiAccountCircleOutline,
		mdiDatabaseExportOutline,
		mdiFolderAccountOutline,
		mdiKeyChainVariant,
		mdiLockOutline,
		mdiPaletteOutline
	} from '@mdi/js';
	import SettingSection from '#lib/admin/SettingSection.svelte';
	import { NAME_FORMATS, nameFormat, shownName, type NameFormat } from '#lib/names.svelte.ts';
	import {
		defaultLibrary,
		libraryName,
		loadOrganize,
		writableLibraries
	} from '#lib/organize.svelte.ts';
	import AccessTokens from '#lib/AccessTokens.svelte';
	import ConnectedApps from '#lib/ConnectedApps.svelte';
	import ExportLibrary from '#lib/ExportLibrary.svelte';
	import { page } from '$app/state';
	import { session } from '#lib/session.svelte.ts';
	import { theme, type Theme } from '#lib/theme.svelte.ts';
	import OidcLink from '#lib/OidcLink.svelte';
	import ProfilePicture from '#lib/ProfilePicture.svelte';

	let oidcLabel = $state<string | null>(null);
	$effect(() => {
		loginMethods().then(({ data }) => (oidcLabel = data?.oidc_label ?? null));
	});

	$effect(() => {
		loadOrganize();
	});

	const THEMES: { value: Theme; label: string; help: string }[] = [
		{ value: 'system', label: 'Like the device', help: 'light or dark as the system is set' },
		{ value: 'light', label: 'Light', help: 'dark ink on light paper' },
		{ value: 'dark', label: 'Dark', help: 'light ink on deep blue' }
	];

	/** Sections, all closed at first; the open ones are in the address
	 * (?open=account,appearance). Old links to #export open that one. */
	const open = $derived.by(() => {
		const listed = (page.url.searchParams.get('open') ?? '').split(',').filter(Boolean);
		const exporting = page.url.searchParams.has('export') || page.url.hash === '#export';
		return exporting && !listed.includes('export') ? [...listed, 'export'] : listed;
	});
	function toggle(slug: string, opened: boolean) {
		const next = opened ? [...open, slug] : open.filter((s) => s !== slug);
		const url = new URL(page.url.href);
		url.searchParams.set('open', next.join(','));
		url.hash = '';
		goto(`${url.pathname}${url.search}`, { replaceState: true, reset: false });
	}

	// Account: the name others see, and one's ORCID iD.
	let displayName = $state(session.user?.display_name ?? '');
	let orcid = $state(session.user?.orcid ?? '');
	let profileMessage = $state('');
	let profileError = $state('');
	const profileChanged = $derived(
		displayName.trim() !== (session.user?.display_name ?? '') ||
			orcid.trim() !== (session.user?.orcid ?? '')
	);
	async function saveProfile(event: SubmitEvent) {
		event.preventDefault();
		profileMessage = profileError = '';
		const { data, error } = await setProfile({
			body: { display_name: displayName.trim(), orcid: orcid.trim() }
		});
		if (!data) {
			profileError = errorMessage(error);
			return;
		}
		session.user = data;
		displayName = data.display_name ?? '';
		orcid = data.orcid ?? '';
		profileMessage = 'Saved.';
	}

	let ownerMessage = $state('');

	let namesMessage = $state('');
	async function chooseNameFormat(value: NameFormat) {
		const { error } = await setNameFormat({ body: { name_format: value } });
		if (!error && session.user) session.user.name_format = value;
		namesMessage = error ? errorMessage(error) : 'Saved.';
	}
	async function chooseOwner(id: string) {
		const { error } = await setDefaultLibrary({ body: { library_id: id } });
		ownerMessage = error ? errorMessage(error) : 'Saved.';
		await loadOrganize();
	}

	let current = $state('');
	let next = $state('');
	let repeat = $state('');
	let passwordMessage = $state('');
	let passwordError = $state('');
	let saving = $state(false);

	async function savePassword(event: SubmitEvent) {
		event.preventDefault();
		passwordMessage = passwordError = '';
		if (next !== repeat) {
			passwordError = 'The two new passwords differ.';
			return;
		}
		saving = true;
		const { error } = await changePassword({ body: { current, new: next } });
		saving = false;
		if (error) {
			passwordError = errorMessage(error);
			return;
		}
		current = next = repeat = '';
		passwordMessage = 'Password changed. Other devices have been logged out.';
	}
</script>

<svelte:head><title>Settings · paperus</title></svelte:head>

<h1>Settings</h1>
<p class="muted lead">
	Your own settings. Those for the whole installation are under Administration.
</p>

<div class="sections">
	<SettingSection
		id="account"
		title="Account"
		subtitle="Your name, picture and ORCID iD"
		icon={mdiAccountCircleOutline}
		status={session.user ? shownName(session.user) : null}
		open={open.includes('account')}
		ontoggle={(opened) => toggle('account', opened)}
	>
		<form class="form" onsubmit={saveProfile}>
			<label
				>Display name <input
					bind:value={displayName}
					maxlength="100"
					placeholder={session.user?.username}
					autocomplete="name"
				/><small
					>What others see, e.g. in groups and as who added a paper. Empty: your username ({session
						.user?.username}).</small
				></label
			>
			<label
				>ORCID iD <input
					bind:value={orcid}
					placeholder="0000-0002-1825-0097"
					autocomplete="off"
					spellcheck="false"
				/><small
					>Finds you among the authors. Only you see it.{#if session.user?.author_id}{' '}<a
							href={resolve('/authors/[id]', { id: session.user.author_id })}>Your author page</a
						>{:else if session.user?.orcid}{' '}No paper of yours with it is here yet.{/if}</small
				></label
			>
			{#if profileError}<p class="error">{profileError}</p>{/if}
			{#if profileMessage}<p class="saved" aria-live="polite">{profileMessage}</p>{/if}
			<div><button class="primary" disabled={!profileChanged}>Save</button></div>
		</form>
		<h3>Profile picture</h3>
		<ProfilePicture />
	</SettingSection>

	<SettingSection
		id="login"
		title="Login"
		subtitle="Your password, and the OIDC login"
		icon={mdiLockOutline}
		status={session.user?.oidc_linked ? 'OIDC linked' : null}
		open={open.includes('login')}
		ontoggle={(opened) => toggle('login', opened)}
	>
		<p class="muted">
			Logged in as <strong>{session.user?.username}</strong>{session.user?.is_admin
				? ', site administrator'
				: ''}.
		</p>
		{#if oidcLabel}
			<h3>OIDC login</h3>
			<OidcLink label={oidcLabel} next="/settings?open=login" />
		{/if}
		<h3>Password</h3>
		<form class="form" onsubmit={savePassword}>
			<label
				>Current password <input
					type="password"
					bind:value={current}
					autocomplete="current-password"
					required
				/></label
			>
			<label
				>New password <input
					type="password"
					bind:value={next}
					autocomplete="new-password"
					minlength="8"
					required
				/></label
			>
			<label
				>New password again <input
					type="password"
					bind:value={repeat}
					autocomplete="new-password"
					minlength="8"
					required
				/></label
			>
			{#if passwordError}<p class="error">{passwordError}</p>{/if}
			{#if passwordMessage}<p class="saved" aria-live="polite">{passwordMessage}</p>{/if}
			<div><button disabled={saving}>Change password</button></div>
		</form>
	</SettingSection>

	<SettingSection
		id="owner"
		title="New papers"
		subtitle="Who owns what you add: you or a group"
		icon={mdiFolderAccountOutline}
		status={defaultLibrary() ? libraryName(defaultLibrary()!.id) : null}
		open={open.includes('owner')}
		ontoggle={(opened) => toggle('owner', opened)}
	>
		<p class="muted">
			New papers, tags and collections belong to this owner, unless you choose another when adding
			them. Group members see what belongs to their group.
		</p>
		<fieldset>
			<legend class="visually-hidden">Owner of new papers, tags and collections</legend>
			{#each writableLibraries() as library (library.id)}
				<label class="option">
					<input
						type="radio"
						name="owner"
						value={library.id}
						checked={defaultLibrary()?.id === library.id}
						onchange={() => chooseOwner(library.id)}
					/>
					<span>
						<strong>{libraryName(library.id)}</strong>
						<small
							>{library.kind === 'personal'
								? 'Private: only you see them, until you share them'
								: 'Shared with the group'}</small
						>
					</span>
				</label>
			{/each}
		</fieldset>
		{#if ownerMessage}<p class="saved" aria-live="polite">{ownerMessage}</p>{/if}
	</SettingSection>

	<SettingSection
		id="appearance"
		title="Appearance"
		subtitle="Light or dark, and how names are written"
		icon={mdiPaletteOutline}
		status={THEMES.find((t) => t.value === theme.current)?.label ?? null}
		open={open.includes('appearance')}
		ontoggle={(opened) => toggle('appearance', opened)}
	>
		<h3>Theme</h3>
		<p class="muted">Remembered on this device; the button at the top switches it too.</p>
		<fieldset>
			<legend class="visually-hidden">Theme</legend>
			{#each THEMES as option (option.value)}
				<label class="option">
					<input
						type="radio"
						name="theme"
						value={option.value}
						checked={theme.current === option.value}
						onchange={() => theme.set(option.value)}
					/>
					<span>
						<strong>{option.label}</strong>
						<small>{option.help}</small>
					</span>
				</label>
			{/each}
		</fieldset>
		<h3>Names</h3>
		<p class="muted">How people’s names are written, on all your devices.</p>
		<fieldset>
			<legend class="visually-hidden">Names</legend>
			{#each NAME_FORMATS as option (option.value)}
				<label class="option">
					<input
						type="radio"
						name="name-format"
						value={option.value}
						checked={nameFormat() === option.value}
						onchange={() => chooseNameFormat(option.value)}
					/>
					<span>
						<strong>{option.label}</strong>
						<small>{option.example}</small>
					</span>
				</label>
			{/each}
		</fieldset>
		{#if namesMessage}<p class="saved" aria-live="polite">{namesMessage}</p>{/if}
	</SettingSection>

	<SettingSection
		id="tokens"
		title="Access tokens and apps"
		subtitle="For scripts, AI assistants and the browser extension"
		icon={mdiKeyChainVariant}
		open={open.includes('tokens')}
		ontoggle={(opened) => toggle('tokens', opened)}
	>
		<h3>Access tokens</h3>
		<AccessTokens />
		<h3>Connected apps</h3>
		<ConnectedApps />
	</SettingSection>

	<SettingSection
		id="export"
		title="Export"
		subtitle="Your papers, files and notes, to download"
		icon={mdiDatabaseExportOutline}
		open={open.includes('export')}
		ontoggle={(opened) => toggle('export', opened)}
	>
		<ExportLibrary collection={page.url.searchParams.get('export') ?? ''} />
	</SettingSection>
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
		max-width: 760px;
	}
	h3 {
		margin: 18px 0 8px;
		font-size: var(--step-0);
	}
	p {
		margin: 0 0 14px;
		max-width: 60ch;
	}
	fieldset {
		margin: 0;
		padding: 0;
		border: none;
		display: grid;
		gap: 4px;
	}
	.option {
		display: flex;
		align-items: flex-start;
		gap: 12px;
		padding: 8px 10px;
		border-radius: var(--radius);
		cursor: pointer;
	}
	.option:hover {
		background: var(--rail);
	}
	.option input {
		width: auto;
		margin-top: 4px;
	}
	.option span {
		display: grid;
	}
	.option small {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.form {
		display: grid;
		gap: 12px;
		max-width: 480px;
		margin-top: 12px;
	}
	.form label {
		display: grid;
		gap: 6px;
		font-weight: 600;
	}
	.form input {
		font-weight: 400;
	}
	.form small {
		color: var(--muted);
		font-size: var(--step--1);
		font-weight: 400;
	}
	.saved {
		margin: 8px 0 0;
		color: var(--success);
		font-size: var(--step--1);
	}
	.error {
		margin: 0;
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
	}
</style>
