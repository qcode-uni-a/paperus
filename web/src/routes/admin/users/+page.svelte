<script lang="ts">
	import { resolve } from '$app/paths';
	import Avatar from '#lib/Avatar.svelte';
	import { changeUser, createUser, errorMessage, listUsers } from '#lib/api/client.ts';
	import type { UserRow } from '#lib/api/generated/types.gen.ts';
	import { ago } from '#lib/format.ts';
	import { session } from '#lib/session.svelte.ts';

	let users = $state<UserRow[]>([]);
	let error = $state('');
	let notice = $state('');

	async function load() {
		const { data, error: failure } = await listUsers();
		if (failure) error = errorMessage(failure);
		users = data ?? [];
	}

	$effect(() => {
		load();
	});

	// One dialog for a new user and for a new password.
	let dialog = $state<HTMLDialogElement>();
	let resetting = $state<UserRow | null>(null);
	let username = $state('');
	let password = $state('');
	let makeAdmin = $state(false);
	let dialogError = $state('');
	let saving = $state(false);

	function openNew() {
		resetting = null;
		username = password = dialogError = '';
		makeAdmin = false;
		dialog?.showModal();
	}

	function openReset(user: UserRow) {
		resetting = user;
		password = dialogError = '';
		dialog?.showModal();
	}

	async function save(event: SubmitEvent) {
		event.preventDefault();
		saving = true;
		const result = resetting
			? await changeUser({ path: { user_id: resetting.id }, body: { password } })
			: await createUser({ body: { username, password, is_admin: makeAdmin } });
		saving = false;
		if (result.error) {
			dialogError = errorMessage(result.error);
			return;
		}
		notice = resetting
			? `New password set for ${resetting.username}; they were logged out everywhere.`
			: `Created ${username}. Tell them their password, and add them to a group under Manage → Groups.`;
		dialog?.close();
		await load();
	}

	async function change(user: UserRow, body: { is_admin?: boolean; active?: boolean }) {
		error = notice = '';
		const { error: failure } = await changeUser({ path: { user_id: user.id }, body });
		if (failure) error = errorMessage(failure);
		await load();
	}

	function deactivate(user: UserRow) {
		if (
			confirm(
				`Deactivate ${user.username}? They can no longer log in; their papers and groups stay, and you can reactivate them.`
			)
		)
			change(user, { active: false });
	}
</script>

<svelte:head><title>Users · paperus</title></svelte:head>

<header class="head">
	<div>
		<h1>Users</h1>
		<p class="muted">
			{users.length}
			{users.length === 1 ? 'person' : 'people'}. Add people to groups under Manage → Groups.
		</p>
	</div>
	<button onclick={openNew}>New user</button>
</header>

{#if error}<p class="error">{error}</p>{/if}
{#if notice}<p class="notice" aria-live="polite">{notice}</p>{/if}

<table>
	<thead>
		<tr>
			<th>Name</th>
			<th class="number wide">Groups</th>
			<th class="number wide">Own papers</th>
			<th class="wide">Last login</th>
			<th><span class="visually-hidden">Actions</span></th>
		</tr>
	</thead>
	<tbody>
		{#each users as user (user.id)}
			{@const me = user.id === session.user?.id}
			<tr class:inactive={user.deactivated_at}>
				<td class="person">
					<Avatar name={user.username} url={user.avatar_url} size={28} tone="desk" />
					<strong>{user.username}</strong>
					{#if user.is_admin}<span class="badge">Administrator</span>{/if}
					{#if user.deactivated_at}<span class="badge off">Deactivated</span>{/if}
					{#if me}<span class="muted">(you)</span>{/if}
				</td>
				<td class="number wide">{user.groups}</td>
				<td class="number wide">{user.papers}</td>
				<td class="wide muted">
					{user.last_login_at ? ago(user.last_login_at) : 'never'}
				</td>
				<td class="actions">
					<button class="link" onclick={() => openReset(user)}>New password</button>
					<button class="link" onclick={() => change(user, { is_admin: !user.is_admin })}>
						{user.is_admin ? 'Remove admin' : 'Make admin'}
					</button>
					{#if user.deactivated_at}
						<button class="link" onclick={() => change(user, { active: true })}>Reactivate</button>
						{#if user.papers}
							<a class="link" href="{resolve('/admin/settings')}?open=users#users">Hand over</a>
						{/if}
					{:else if !me}
						<button class="link danger" onclick={() => deactivate(user)}>Deactivate</button>
					{/if}
				</td>
			</tr>
		{/each}
	</tbody>
</table>

<dialog bind:this={dialog} aria-labelledby="user-dialog-title">
	<form onsubmit={save}>
		<h2 id="user-dialog-title">
			{resetting ? `New password for ${resetting.username}` : 'New user'}
		</h2>
		{#if !resetting}
			<label
				>Username <input
					bind:value={username}
					required
					maxlength="64"
					pattern={'[\\w.@+\\-]+'}
					autocomplete="off"
				/></label
			>
		{/if}
		<label
			>Password <input
				type="text"
				bind:value={password}
				required
				minlength="8"
				autocomplete="new-password"
			/></label
		>
		<p class="hint">
			At least 8 characters. Shown here so you can pass it on; they can change it in Settings.
		</p>
		{#if !resetting}
			<label class="check"
				><input type="checkbox" bind:checked={makeAdmin} /> Site administrator (manages users and groups)</label
			>
		{/if}
		{#if dialogError}<p class="error">{dialogError}</p>{/if}
		<div class="buttons">
			<button type="button" onclick={() => dialog?.close()}>Cancel</button>
			<button class="primary" disabled={saving}>{resetting ? 'Set password' : 'Create user'}</button
			>
		</div>
	</form>
</dialog>

<style>
	.person :global(.avatar) {
		margin-right: 8px;
		vertical-align: middle;
	}
	.head {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		gap: 16px;
		margin-bottom: 16px;
		flex-wrap: wrap;
	}
	/* Phones: the buttons below the text when it needs the width. */
	.head > div:first-child {
		flex: 1 1 18rem;
	}
	h1 {
		margin: 0 0 4px;
	}
	.head p {
		margin: 0;
	}
	.head button {
		white-space: nowrap;
	}
	.notice {
		padding: 8px 12px;
		border-left: 3px solid var(--success);
		background: var(--rail);
	}
	table {
		width: 100%;
		border-collapse: collapse;
	}
	th,
	td {
		padding: 9px 10px;
		border-bottom: 1px solid var(--rule);
		text-align: left;
		vertical-align: middle;
	}
	th {
		font-size: var(--step--1);
		color: var(--muted);
		font-weight: 600;
	}
	td .badge {
		margin-left: 6px;
	}
	.badge.off {
		color: var(--danger);
	}
	tr.inactive strong {
		color: var(--muted);
	}
	.number {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.actions {
		text-align: right;
		white-space: nowrap;
	}
	.link {
		padding: 2px 6px;
		border: none;
		background: none;
		color: var(--royal);
		font-size: var(--step--1);
	}
	.link:hover:not(:disabled) {
		background: var(--rail);
	}
	.link.danger {
		color: var(--danger);
	}
	dialog {
		width: min(440px, calc(100vw - 32px));
		padding: 22px 24px 24px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	dialog::backdrop {
		background: rgb(10 14 30 / 0.4);
	}
	form {
		display: grid;
		gap: 12px;
	}
	form h2 {
		margin: 0;
		font-size: var(--step-2);
	}
	form label {
		display: grid;
		gap: 6px;
		font-weight: 600;
	}
	form label input {
		font-weight: 400;
	}
	label.check {
		display: flex;
		align-items: center;
		gap: 8px;
		font-weight: 400;
	}
	label.check input {
		width: auto;
	}
	.hint {
		margin: -6px 0 0;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
	}
	@media (max-width: 720px) {
		.wide {
			display: none;
		}
		.actions {
			white-space: normal;
		}
	}
</style>
