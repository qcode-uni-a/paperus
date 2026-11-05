<script lang="ts">
	import { admin } from '#lib/admin/data.svelte.ts';
	import { saveConfig } from '#lib/admin/config.svelte.ts';
	import SectionButtons from '#lib/admin/SectionButtons.svelte';
	import SettingRow from '#lib/admin/SettingRow.svelte';
	import Stepper from '#lib/admin/Stepper.svelte';
	import Switch from '#lib/admin/Switch.svelte';
	import {
		authentication,
		checkProvider,
		endAllSessions,
		errorMessage,
		setOidcSecret
	} from '#lib/api/client.ts';
	import type { Authentication, ProviderFound } from '#lib/api/generated/types.gen.ts';
	import { notify } from '#lib/toasts.svelte.ts';
	import UniversityLink from '#lib/UniversityLink.svelte';

	const config = $derived(admin.config);
	let info = $state<Authentication | null>(null);
	let days = $state(30);
	let minLength = $state(8);
	let oidc = $state(false);
	let issuer = $state('');
	let clientId = $state('');
	let secret = $state('');
	let label = $state('University login');
	let claim = $state('preferred_username');
	let create = $state(true);
	let passwordLogin = $state(true);
	let saving = $state(false);
	let found = $state<ProviderFound | null>(null);
	let checking = $state(false);

	async function loadInfo() {
		const { data } = await authentication();
		info = data ?? null;
	}
	$effect(() => {
		loadInfo();
	});

	function reset() {
		days = config?.session_days ?? 30;
		minLength = config?.password_min_length ?? 8;
		oidc = config?.oidc_enabled ?? false;
		issuer = config?.oidc_issuer ?? '';
		clientId = config?.oidc_client_id ?? '';
		label = config?.oidc_label ?? 'University login';
		claim = config?.oidc_username_claim ?? 'preferred_username';
		create = config?.oidc_create_accounts ?? true;
		passwordLogin = config?.password_login ?? true;
		secret = '';
	}
	// The page reloads its data every few seconds: start over only when the
	// saved values change (not while someone is typing).
	let seen = '';
	$effect(() => {
		if (!config) return;
		const saved = JSON.stringify([
			config.session_days,
			config.password_min_length,
			config.oidc_enabled,
			config.oidc_issuer,
			config.oidc_client_id,
			config.oidc_label,
			config.oidc_username_claim,
			config.oidc_create_accounts,
			config.password_login
		]);
		if (saved === seen) return;
		seen = saved;
		reset();
	});

	const changed = $derived(
		!!config &&
			(days !== (config.session_days ?? 30) ||
				minLength !== (config.password_min_length ?? 8) ||
				oidc !== (config.oidc_enabled ?? false) ||
				issuer !== (config.oidc_issuer ?? '') ||
				clientId !== (config.oidc_client_id ?? '') ||
				label !== (config.oidc_label ?? 'University login') ||
				claim !== (config.oidc_username_claim ?? 'preferred_username') ||
				create !== (config.oidc_create_accounts ?? true) ||
				passwordLogin !== (config.password_login ?? true) ||
				secret !== '')
	);
	// Password login can only be off with the university login.
	$effect(() => {
		if (!oidc) passwordLogin = true;
	});

	async function save() {
		saving = true;
		if (secret) {
			const { error } = await setOidcSecret({ body: { secret } });
			if (error) {
				notify({ kind: 'warning', title: 'Secret not saved', text: errorMessage(error) });
				saving = false;
				return;
			}
			secret = '';
		}
		await saveConfig(
			{
				session_days: days,
				password_min_length: minLength,
				oidc_enabled: oidc,
				oidc_issuer: issuer.trim() || null,
				oidc_client_id: clientId.trim() || null,
				oidc_label: label.trim() || 'University login',
				oidc_username_claim: claim.trim() || 'preferred_username',
				oidc_create_accounts: create,
				password_login: passwordLogin
			},
			'Authentication settings'
		);
		await loadInfo();
		saving = false;
	}

	async function removeSecret() {
		await setOidcSecret({ body: { secret: null } });
		await loadInfo();
		notify({ kind: 'success', title: 'Client secret removed' });
	}

	async function check() {
		checking = true;
		const { data, error } = await checkProvider({ body: { issuer: issuer.trim() } });
		checking = false;
		found = data ?? { ok: false, error: errorMessage(error) };
	}

	async function copyRedirect() {
		if (!info) return;
		await navigator.clipboard.writeText(info.redirect_uri);
		notify({ kind: 'success', title: 'Redirect address copied' });
	}

	async function logEveryoneOut() {
		if (!confirm('Log everyone out on every device (except you, here)?')) return;
		const { data } = await endAllSessions();
		notify({
			kind: 'success',
			title: 'Logged everyone out',
			text: `${data?.ended ?? 0} sessions ended.`
		});
		await loadInfo();
	}
</script>

<SettingRow
	id="session-days"
	title="Stay logged in for"
	description="Days until one has to log in again on a device. Applies to new logins."
>
	<Stepper id="session-days" label="Days logged in" bind:value={days} min={1} max={365} />
	<span class="unit">days</span>
</SettingRow>
<SettingRow
	id="password-length"
	title="Shortest password"
	description="Characters, for new and changed passwords."
>
	<Stepper
		id="password-length"
		label="Shortest password"
		bind:value={minLength}
		min={8}
		max={128}
	/>
</SettingRow>

<h3>University login</h3>
<p class="muted note">
	Single sign-on with OpenID Connect: Keycloak, Microsoft Entra, Shibboleth’s OIDC provider and
	others. For SAML only, put a bridge in front (e.g. Keycloak or SATOSA).
</p>
<SettingRow
	id="oidc-on"
	title="Log in with the university account"
	description="A button on the login page; it takes people to the identity provider and back."
>
	<Switch id="oidc-on" label="University login" bind:checked={oidc} />
</SettingRow>
{#if oidc}
	<div class="provider">
		<SettingRow
			id="oidc-redirect"
			title="Redirect address"
			description="Register this at the identity provider (as the client’s redirect or callback URL)."
		>
			<code class="redirect">{info?.redirect_uri ?? '…'}</code>
			<button class="small" onclick={copyRedirect}>Copy</button>
		</SettingRow>
		<SettingRow
			id="oidc-issuer"
			title="Identity provider"
			description="Its address (issuer), e.g. https://login.uni-example.de/realms/staff."
		>
			<input
				id="oidc-issuer"
				type="url"
				bind:value={issuer}
				placeholder="https://…"
				oninput={() => (found = null)}
			/>
			<button class="small" onclick={check} disabled={!issuer.trim() || checking}>
				{checking ? 'Checking…' : 'Check'}
			</button>
		</SettingRow>
		{#if found}
			<p class="found" class:bad={!found.ok} role="status">
				{found.ok ? `Found: logins go to ${found.authorization_endpoint}` : found.error}
			</p>
		{/if}
		<SettingRow id="oidc-client" title="Client ID" description="As registered there.">
			<input id="oidc-client" bind:value={clientId} placeholder="paperus" />
		</SettingRow>
		<SettingRow
			id="oidc-secret"
			title="Client secret"
			description={info?.secret_from_environment
				? 'Set on the server (PAPERUS_OIDC_CLIENT_SECRET).'
				: info?.secret_set
					? 'Set; type a new one to replace it. Never shown again.'
					: 'From the identity provider; empty for a public client.'}
		>
			<input
				id="oidc-secret"
				type="password"
				autocomplete="off"
				bind:value={secret}
				disabled={info?.secret_from_environment}
				placeholder={info?.secret_set ? '••••••••' : ''}
			/>
			{#if info?.secret_set && !info.secret_from_environment}
				<button class="small" onclick={removeSecret}>Remove</button>
			{/if}
		</SettingRow>
		<SettingRow id="oidc-label" title="Button text" description="On the login page.">
			<input id="oidc-label" bind:value={label} maxlength="60" />
		</SettingRow>
		<SettingRow
			id="oidc-claim"
			title="Username from"
			description="The claim that becomes the username. An existing account of that name is linked on its first login."
		>
			<input id="oidc-claim" bind:value={claim} list="oidc-claims" />
			<datalist id="oidc-claims">
				<option value="preferred_username"></option>
				<option value="email"></option>
				<option value="uid"></option>
				<option value="sub"></option>
			</datalist>
		</SettingRow>
		<SettingRow
			id="oidc-create"
			title="Create accounts"
			description="On someone’s first university login. Off: only people added under Users beforehand."
		>
			<Switch id="oidc-create" label="Create accounts" bind:checked={create} />
		</SettingRow>
		<SettingRow
			id="password-login"
			title="Password login for everyone"
			description="Off: only administrators log in with a password (their way in if the university login fails); everyone else uses the university login."
		>
			<Switch
				id="password-login"
				label="Password login for everyone"
				bind:checked={passwordLogin}
			/>
		</SettingRow>
	</div>
{/if}
<SectionButtons {changed} {saving} onreset={reset} onsave={save} />

{#if config?.oidc_enabled}
	<h3>Your account</h3>
	<UniversityLink
		label={config.oidc_label ?? 'University login'}
		next="/admin/settings?open=authentication"
	/>
	{#if info}
		<p class="muted small">
			{info.linked}
			{info.linked === 1 ? 'account uses' : 'accounts use'} the university login.
		</p>
	{/if}
{/if}

<h3>Sessions</h3>
<div class="sessions">
	<p>
		{#if info}<strong>{info.sessions}</strong>
			{info.sessions === 1 ? 'device is' : 'devices are'} logged in now.{/if}
		Logging everyone out ends every session but yours; access tokens stay valid.
	</p>
	<button class="danger-button" onclick={logEveryoneOut}>Log everyone out</button>
</div>

<style>
	h3 {
		margin: 24px 0 4px;
		font-size: var(--step-0);
	}
	.note {
		margin: 0 0 4px;
		font-size: var(--step--1);
	}
	.unit {
		align-self: center;
		color: var(--muted);
	}
	.provider {
		margin: 0 0 0 4px;
		padding-left: 16px;
		border-left: 2px solid var(--rule);
	}
	.redirect {
		align-self: center;
		padding: 6px 10px;
		border-radius: 8px;
		background: var(--rail);
		font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
		font-size: 0.85em;
		overflow-wrap: anywhere;
	}
	.small {
		flex: none;
		padding: 6px 12px;
	}
	.found {
		margin: -6px 0 8px;
		padding: 6px 10px;
		border-left: 3px solid var(--success);
		background: var(--rail);
		font-size: var(--step--1);
		overflow-wrap: anywhere;
	}
	.found.bad {
		border-left-color: var(--danger);
		color: var(--danger);
	}
	.sessions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 10px 16px;
	}
	.sessions p {
		margin: 0;
		flex: 1 1 260px;
	}
	.danger-button {
		border-color: var(--danger);
		color: var(--danger);
	}
	.small:not(button) {
		margin: 8px 0 0;
		font-size: var(--step--1);
	}
</style>
