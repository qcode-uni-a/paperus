<script lang="ts">
	import {
		changePassword,
		errorMessage,
		loginMethods,
		setDefaultLibrary
	} from '#lib/api/client.ts';
	import {
		defaultLibrary,
		libraryName,
		loadOrganize,
		writableLibraries
	} from '#lib/organize.svelte.ts';
	import AccessTokens from '#lib/AccessTokens.svelte';
	import { session } from '#lib/session.svelte.ts';
	import { theme, type Theme } from '#lib/theme.svelte.ts';
	import OidcLink from '#lib/OidcLink.svelte';

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

	let ownerMessage = $state('');
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

<section>
	<h2>Owner of new things</h2>
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
</section>

<section>
	<h2>Appearance</h2>
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
</section>

<section>
	<h2>Access tokens</h2>
	<AccessTokens />
</section>

<section>
	<h2>Account</h2>
	<p class="muted">
		Logged in as <strong>{session.user?.username}</strong>{session.user?.is_admin
			? ', site administrator'
			: ''}.
	</p>
	{#if oidcLabel}
		<h3>OIDC login</h3>
		<OidcLink label={oidcLabel} next="/settings" />
		<h3>Password</h3>
	{/if}
	<form class="password" onsubmit={savePassword}>
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
</section>

<style>
	h1 {
		margin: 0 0 24px;
	}
	section {
		max-width: 560px;
		padding: 0 0 28px;
		margin-bottom: 28px;
		border-bottom: 1px solid var(--rule);
	}
	section:last-child {
		border-bottom: none;
	}
	h2 {
		margin: 0 0 6px;
		font-size: var(--step-1);
	}
	h3 {
		margin: 18px 0 8px;
		font-size: var(--step-0);
	}
	section > p {
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
	.password {
		display: grid;
		gap: 12px;
	}
	.password label {
		display: grid;
		gap: 6px;
		font-weight: 600;
	}
	.password input {
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
