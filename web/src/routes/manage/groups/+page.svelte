<script lang="ts">
	import { enterSubmits } from '#lib/enterSubmits.ts';
	import Avatar from '#lib/Avatar.svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import {
		deleteGroup,
		errorMessage,
		findUsers,
		getAutomations,
		getLibraryAutomations,
		leaveGroup,
		listGroups,
		listMembers,
		removeMember,
		setMember
	} from '#lib/api/client.ts';
	import type {
		LibraryAutomations as Switches,
		ServerAutomations,
		GroupOut,
		MemberOut,
		Role,
		UserBrief
	} from '#lib/api/generated/types.gen.ts';
	import LibraryAutomations from '#lib/LibraryAutomations.svelte';
	import GroupDialog from '#lib/GroupDialog.svelte';
	import IconButton from '#lib/IconButton.svelte';
	import { loadOrganize } from '#lib/organize.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import { shownName } from '#lib/names.svelte.ts';

	const ROLES: { value: Role; label: string; help: string }[] = [
		{ value: 'reader', label: 'Reader', help: 'reads and searches' },
		{ value: 'member', label: 'Member', help: 'also adds and edits papers' },
		{ value: 'admin', label: 'Admin', help: 'also manages people and groups' }
	];

	let groups = $state<GroupOut[]>([]);
	let loaded = $state(false);
	let members = $state<MemberOut[]>([]);
	let people = $state<UserBrief[]>([]);
	let newPerson = $state('');
	let newRole = $state<Role>('member');
	let error = $state('');
	let dialog = $state<GroupDialog>();

	const selectedId = $derived(page.url.searchParams.get('group'));
	const selected = $derived(groups.find((g) => g.id === selectedId) ?? groups[0]);
	const childrenOf = (id: string | null) => groups.filter((g) => g.parent_id === id);
	// Groups whose parent the person cannot see show at the top; groups of
	// people (shared with single people) in a section of their own.
	const roots = $derived(
		groups.filter(
			(g) => !g.people && (g.parent_id === null || !groups.some((p) => p.id === g.parent_id))
		)
	);
	const peopleGroups = $derived(groups.filter((g) => g.people));

	async function load() {
		const { data } = await listGroups();
		groups = data ?? [];
		loaded = true;
	}

	// The group's automations (its members see them; its admins, and site
	// administrators also without being members, switch them).
	let server = $state<ServerAutomations | null>(null);
	let switches = $state<Switches | null>(null);
	$effect(() => {
		getAutomations().then(({ data }) => (server = data?.server ?? null));
	});
	$effect(() => {
		const library_id = selected?.library_id;
		switches = null;
		if (!library_id) return;
		getLibraryAutomations({ path: { library_id } }).then(({ data }) => {
			if (selected?.library_id === library_id) switches = data ?? null;
		});
	});

	$effect(() => {
		load();
	});

	$effect(() => {
		const id = selected?.id;
		members = [];
		error = '';
		if (!id) return;
		listMembers({ path: { group_id: id } }).then(({ data }) => {
			if (selected?.id === id) members = data ?? [];
		});
	});

	function select(id: string) {
		goto(`${resolve('/manage/groups')}?group=${id}`, { replace: true, reset: false });
	}

	async function changed(result: { data?: MemberOut[]; error?: unknown }) {
		error = result.error ? errorMessage(result.error) : '';
		if (result.data) members = result.data;
		await Promise.all([load(), loadOrganize()]);
	}

	// People to add, found by name or username as one types (from two
	// letters on), without those in the group already.
	let picked = $state<UserBrief | null>(null);
	$effect(() => {
		const words = newPerson.trim();
		if (words.length < 2 || (picked && words === shownName(picked))) {
			people = [];
			return;
		}
		picked = null;
		const timer = setTimeout(async () => {
			const { data } = await findUsers({ query: { q: words } });
			if (words !== newPerson.trim()) return;
			people = (data ?? []).filter(
				(p) => !members.some((m) => m.user_id === p.id && m.direct_role)
			);
		}, 200);
		return () => clearTimeout(timer);
	});
	function pick(person: UserBrief) {
		picked = person;
		newPerson = shownName(person);
		people = [];
	}

	async function addPerson(event: SubmitEvent) {
		event.preventDefault();
		if (!selected) return;
		const typed = newPerson.trim();
		let person = picked;
		if (!person) {
			// A username typed whole, picked or not.
			const { data } = await findUsers({ query: { q: typed } });
			person = (data ?? []).find((p) => p.username === typed) ?? null;
		}
		if (!person) {
			error = `No user “${typed}”: pick one of those found as you type.`;
			return;
		}
		newPerson = '';
		picked = null;
		await changed(
			await setMember({
				path: { group_id: selected.id, user_id: person.id },
				body: { role: selected.can_rescue ? 'admin' : newRole }
			})
		);
	}

	async function remove(group: GroupOut) {
		if (!confirm(`Delete the group “${group.name}”? It has no papers, so nothing is lost.`)) return;
		const result = await deleteGroup({ path: { group_id: group.id } });
		if (result.error) {
			error = errorMessage(result.error);
			return;
		}
		await Promise.all([load(), loadOrganize()]);
		select(groups[0]?.id ?? '');
	}

	async function leave(group: GroupOut) {
		if (!confirm(`Leave ${group.name}? You will no longer see its papers.`)) return;
		const result = await leaveGroup({ path: { group_id: group.id } });
		if (result.error) {
			error = errorMessage(result.error);
			return;
		}
		await Promise.all([load(), loadOrganize()]);
		select(groups[0]?.id ?? '');
	}

	function roleLabel(role: Role): string {
		return ROLES.find((r) => r.value === role)?.label ?? role;
	}
</script>

<svelte:head><title>Groups · paperus</title></svelte:head>

<header class="head">
	<div>
		<h1>Groups</h1>
		<p class="muted">
			Papers and collections given to a group are shared with its members. Everyone in a group is
			also in the groups inside it.
		</p>
	</div>
	{#if session.user?.is_admin}
		<button onclick={() => dialog?.open()}>New group</button>
	{/if}
</header>

{#if loaded && groups.length === 0}
	<p class="muted">
		You are in no group yet. {session.user?.is_admin
			? 'Create the first one with New group.'
			: 'An administrator can add you to one.'}
	</p>
{:else if selected}
	<div class="layout">
		<nav class="groups" aria-label="Groups">
			<ul>
				{#each roots as group (group.id)}{@render node(group)}{/each}
			</ul>
			{#if peopleGroups.length}
				<h3 class="people-head">Shared with people</h3>
				<ul>
					{#each peopleGroups as group (group.id)}{@render node(group)}{/each}
				</ul>
			{/if}
		</nav>

		<section class="detail" aria-labelledby="group-name">
			<div class="title">
				<div>
					<h2 id="group-name">{selected.name}</h2>
					{#if selected.description}<p class="description">{selected.description}</p>{/if}
					<p class="muted facts">
						{#if selected.people}Shared with people: everyone in it may share papers in it, add
							people and rename it.
						{:else if selected.role}You are {selected.role === 'admin' ? 'an' : 'a'}
							{roleLabel(selected.role).toLowerCase()}.{:else}You see this group as the server’s
							administrator; its admins run it.{/if}
						{#if selected.items !== null}
							{selected.items}
							{selected.items === 1 ? 'paper' : 'papers'}.{/if}
					</p>
				</div>
				{#if selected.can_manage}
					<div class="actions">
						<IconButton
							icon="edit"
							label="Edit {selected.name}"
							onclick={() => dialog?.open({ group: selected })}
						/>
						<IconButton
							icon="delete"
							label="Delete {selected.name}"
							onclick={() => remove(selected)}
						/>
					</div>
				{/if}
			</div>
			{#if error}<p class="error">{error}</p>{/if}

			<h3>People</h3>
			{#if members.find((m) => m.user_id === session.user?.id)?.direct_role}
				<button class="leave" onclick={() => leave(selected)}>Leave {selected.name}</button>
			{/if}
			<ul class="members">
				{#each members as member (member.user_id)}
					<li>
						<Avatar name={shownName(member)} url={member.avatar_url} size={30} tone="desk" />
						<span class="who">
							<strong>{shownName(member)}</strong>{#if member.display_name}<span class="muted"
									>{member.username}</span
								>{/if}
							{#if member.inherited_from}
								<small>{roleLabel(member.role)} through {member.inherited_from}</small>
							{/if}
						</span>
						{#if selected.can_manage}
							{#if !selected.people}<select
									value={member.direct_role ?? ''}
									aria-label="Role of {shownName(member)}"
									onchange={async (event) => {
										const role = event.currentTarget.value as Role | '';
										await changed(
											role
												? await setMember({
														path: { group_id: selected.id, user_id: member.user_id },
														body: { role }
													})
												: await removeMember({
														path: { group_id: selected.id, user_id: member.user_id }
													})
										);
									}}
								>
									{#if member.inherited_from}
										<option value="">Inherited</option>
									{/if}
									{#each ROLES as role (role.value)}
										<option value={role.value}>{role.label}</option>
									{/each}
								</select>{/if}
							{#if member.direct_role}
								<IconButton
									icon="delete"
									label="Remove {shownName(member)} from {selected.name}"
									onclick={async () =>
										changed(
											await removeMember({
												path: { group_id: selected.id, user_id: member.user_id }
											})
										)}
								/>
							{:else}
								<span class="spacer"></span>
							{/if}
						{:else}
							<span class="role">{roleLabel(member.role)}</span>
						{/if}
					</li>
				{/each}
			</ul>

			{#if selected.can_rescue}
				<p class="licence">
					This group has no admin left (they left or were deactivated). Name one: they then run it,
					as its admins do.
				</p>
			{/if}
			{#if selected.can_manage || selected.can_rescue}
				<form class="add" onsubmit={addPerson}>
					<input
						bind:value={newPerson}
						{@attach enterSubmits}
						placeholder="Name or username"
						role="combobox"
						aria-label="Person to add"
						aria-expanded={people.length > 0}
						aria-controls="group-people"
						autocomplete="off"
						required
					/>
					{#if !selected.people && !selected.can_rescue}
						<select bind:value={newRole} aria-label="Role">
							{#each ROLES as role (role.value)}
								<option value={role.value}>{role.label}: {role.help}</option>
							{/each}
						</select>
					{/if}
					<button>{selected.can_rescue ? 'Name as admin' : 'Add'}</button>
				</form>
				{#if people.length}
					<div class="found" id="group-people" role="listbox" aria-label="People found">
						{#each people as person (person.id)}
							<button
								type="button"
								role="option"
								aria-selected="false"
								class="pick"
								onclick={() => pick(person)}
								>{shownName(person)}{#if person.display_name}
									<span class="muted">{person.username}</span>{/if}</button
							>
						{/each}
					</div>
				{/if}
				<p class="licence">
					Everyone you add can open the PDFs of this group's papers{selected.people
						? ''
						: ' and those of the groups inside it'}. Make sure the licences of these papers allow
					sharing them with these people.
				</p>
			{/if}
			{#if selected.can_manage}
				{#if !selected.people}<h3>Groups inside</h3>{/if}
				{#if childrenOf(selected.id).length}
					<ul class="subgroups">
						{#each childrenOf(selected.id) as child (child.id)}
							<li><button class="link" onclick={() => select(child.id)}>{child.name}</button></li>
						{/each}
					</ul>
				{/if}
				{#if !selected.people}
					<button class="new-inside" onclick={() => dialog?.open({ parent: selected })}>
						New group in {selected.name}
					</button>
				{/if}
			{/if}

			{#if switches && server}
				<h3>Automations</h3>
				<LibraryAutomations bind:automations={switches} {server} />
			{/if}
		</section>
	</div>
{/if}

<GroupDialog
	{groups}
	siteAdmin={session.user?.is_admin ?? false}
	bind:this={dialog}
	onsaved={async (id) => {
		await Promise.all([load(), loadOrganize()]);
		select(id);
	}}
/>

{#snippet node(group: GroupOut)}
	<li>
		<button
			class="group"
			class:current={group.id === selected?.id}
			onclick={() => select(group.id)}
		>
			<span class="name">{group.name}</span>
			{#if group.role && !group.people}<span class="badge">{roleLabel(group.role)}</span>{/if}
		</button>
		{#if childrenOf(group.id).length}
			<ul>
				{#each childrenOf(group.id) as child (child.id)}{@render node(child)}{/each}
			</ul>
		{/if}
	</li>
{/snippet}

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		gap: 16px;
		margin-bottom: 24px;
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
	.layout {
		display: grid;
		grid-template-columns: minmax(180px, 240px) minmax(0, 1fr);
		gap: 32px;
		align-items: start;
	}
	ul {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.people-head {
		margin: 18px 0 6px;
		color: var(--muted);
		font-size: var(--step--1);
		font-weight: 600;
	}
	.groups ul ul {
		margin-left: 14px;
		padding-left: 8px;
		border-left: 2px solid var(--rule);
	}
	.group {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 7px 10px;
		border: none;
		border-radius: var(--radius);
		background: none;
		text-align: left;
		color: var(--ink);
	}
	.group:hover:not(:disabled) {
		background: var(--rail);
	}
	.group.current {
		background: var(--rail);
		font-weight: 650;
	}
	.group .name {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.detail {
		min-width: 0;
	}
	.title {
		display: flex;
		justify-content: space-between;
		gap: 12px;
	}
	/* A long name (one long word, as German has) wraps, the buttons stay. */
	.title > div:first-child {
		min-width: 0;
	}
	h2 {
		margin: 0;
		font-size: var(--step-3);
		overflow-wrap: anywhere;
	}
	.description {
		margin: 4px 0 0;
		font-family: var(--serif);
		color: var(--muted);
	}
	.facts {
		margin: 6px 0 0;
		font-size: var(--step--1);
	}
	.actions {
		display: flex;
		flex: none;
	}
	h3 {
		margin: 28px 0 10px;
		font-size: var(--step-1);
	}
	.members li {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 0;
		border-bottom: 1px solid var(--rule);
	}
	.who {
		flex: 1;
		min-width: 0;
		display: grid;
	}
	.who small {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.members select {
		width: auto;
	}
	.role {
		color: var(--muted);
	}
	.spacer {
		width: 34px;
	}
	.leave {
		margin: -4px 0 8px;
		font-size: var(--step--1);
	}
	.add {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-top: 14px;
	}
	.add input {
		flex: 1;
		min-width: 160px;
	}
	.add select {
		width: auto;
		max-width: 100%;
	}
	.found {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-top: 8px;
	}
	.pick {
		padding: 3px 12px;
		border-radius: 999px;
		font-size: var(--step--1);
	}
	.licence {
		margin: 8px 0 0;
		padding: 8px 12px;
		border-left: 3px solid var(--highlighter);
		color: var(--muted);
		font-size: var(--step--1);
		max-width: 70ch;
	}
	.subgroups {
		display: grid;
		gap: 4px;
		margin-bottom: 10px;
	}
	.link {
		padding: 0;
		border: none;
		background: none;
		color: var(--royal);
		text-decoration: underline;
	}
	.link:hover:not(:disabled) {
		background: none;
	}
	@media (max-width: 720px) {
		.layout {
			grid-template-columns: minmax(0, 1fr);
			gap: 16px;
		}
	}
</style>
