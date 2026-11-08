<script lang="ts">
	import { mdiClose } from '@mdi/js';
	import { resolve } from '$app/paths';
	import { admin } from '#lib/admin/data.svelte.ts';
	import { saveConfig } from '#lib/admin/config.svelte.ts';
	import SectionButtons from '#lib/admin/SectionButtons.svelte';
	import { errorMessage, handOver, listGroups, listUsers, privateThings } from '#lib/api/client.ts';
	import { session } from '#lib/session.svelte.ts';
	import type { GroupOut, Joining, Private, UserRow } from '#lib/api/generated/types.gen.ts';
	import { ago } from '#lib/format.ts';
	import Icon from '#lib/Icon.svelte';
	import { notify } from '#lib/toasts.svelte.ts';

	const config = $derived(admin.config);
	let groups = $state<GroupOut[]>([]);
	let users = $state<UserRow[]>([]);
	let joining = $state<Joining[]>([]);
	let adding = $state('');
	let saving = $state(false);

	async function load() {
		const [g, u] = await Promise.all([listGroups(), listUsers()]);
		groups = g.data ?? [];
		users = u.data ?? [];
	}
	$effect(() => {
		load();
	});

	function reset() {
		joining = (config?.new_user_groups ?? []).map((j) => ({ ...j }));
	}
	// The page reloads its data every few seconds: start over only when the
	// saved values change (not while someone is choosing).
	let seen = '';
	$effect(() => {
		if (!config) return;
		const saved = JSON.stringify(config.new_user_groups ?? []);
		if (saved === seen) return;
		seen = saved;
		reset();
	});

	const changed = $derived(
		!!config && JSON.stringify(joining) !== JSON.stringify(config.new_user_groups ?? [])
	);
	const groupName = (id: string) => groups.find((g) => g.id === id)?.name ?? 'A deleted group';
	const addable = $derived(groups.filter((g) => !joining.some((j) => j.group_id === g.id)));

	function add() {
		if (!adding) return;
		joining = [...joining, { group_id: adding, role: 'member' }];
		adding = '';
	}

	async function save() {
		saving = true;
		await saveConfig({ new_user_groups: joining }, 'Users settings');
		saving = false;
	}

	// Handing over a departed person's things.
	const departed = $derived(users.filter((u) => u.deactivated_at));
	const active = $derived(users.filter((u) => !u.deactivated_at));
	// Being an administrator reads no library: never handed to oneself.
	const receivers = $derived(active.filter((u) => u.id !== session.user?.id));
	let open = $state<string | null>(null);
	let holds = $state<Private | null>(null);
	let target = $state('');
	let busy = $state(false);

	async function choose(user: UserRow) {
		open = open === user.id ? null : user.id;
		holds = null;
		target = '';
		if (open) holds = (await privateThings({ path: { user_id: user.id } })).data ?? null;
	}

	function summary(found: Private): string {
		const parts = [
			[found.items, 'paper', 'papers'],
			[found.notes, 'note', 'notes'],
			[found.collections, 'collection', 'collections'],
			[found.tags, 'tag', 'tags']
		] as const;
		const listed = parts
			.filter(([n]) => n > 0)
			.map(([n, one, many]) => `${n} ${n === 1 ? one : many}`);
		return listed.length ? listed.join(', ') : 'nothing';
	}

	async function give(user: UserRow) {
		const [kind, id] = target.split(':');
		const receiver =
			kind === 'group' ? groupName(id) : (users.find((u) => u.id === id)?.username ?? '');
		if (!confirm(`Give everything of ${user.username} to ${receiver}? This cannot be undone here.`))
			return;
		busy = true;
		const { data, error } = await handOver({
			path: { user_id: user.id },
			body: kind === 'group' ? { group_id: id } : { user_id: id }
		});
		busy = false;
		if (error) {
			notify({ kind: 'warning', title: 'Not handed over', text: errorMessage(error) });
			return;
		}
		notify({
			kind: 'success',
			title: `Handed over to ${receiver}`,
			text: data ? `${summary(data)}.` : undefined
		});
		open = null;
		await load();
	}
</script>

<p class="muted intro">
	Accounts themselves (adding people, passwords, administrators, deactivating) are under
	<a href={resolve('/admin/users')}>Administration → Users</a>.
</p>

<h3>New accounts join</h3>
<p class="muted note">
	Groups everyone new becomes a member of: accounts an administrator adds and those made on a first
	OIDC login. Earlier accounts stay as they are.
</p>
{#if joining.length}
	<ul class="joining">
		{#each joining as join, index (join.group_id)}
			<li>
				<span class="group">{groupName(join.group_id)}</span>
				<select bind:value={joining[index].role} aria-label="Role in {groupName(join.group_id)}">
					<option value="reader">Reader</option>
					<option value="member">Member</option>
				</select>
				<button
					class="icon"
					aria-label="Remove {groupName(join.group_id)}"
					onclick={() => (joining = joining.filter((j) => j.group_id !== join.group_id))}
				>
					<Icon path={mdiClose} size={18} />
				</button>
			</li>
		{/each}
	</ul>
{:else}
	<p class="empty">No groups: new accounts start with only their own library.</p>
{/if}
{#if addable.length}
	<div class="add">
		<select bind:value={adding} aria-label="Group to add">
			<option value="">Add a group…</option>
			{#each addable as group (group.id)}<option value={group.id}>{group.name}</option>{/each}
		</select>
		<button onclick={add} disabled={!adding}>Add</button>
	</div>
{/if}
<SectionButtons {changed} {saving} onreset={reset} onsave={save} />

<h3>When someone leaves</h3>
<p class="muted note">
	Deactivating a person stops their logins; their own papers, notes, collections and tags stay,
	hidden from everyone, until they come back or someone gets them here. Tags merge with the new
	owner’s tags of the same name.
</p>
{#if departed.length}
	<ul class="departed">
		{#each departed as user (user.id)}
			<li>
				<div class="person">
					<span>
						<strong>{user.username}</strong>
						<small
							>deactivated {ago(user.deactivated_at ?? '')}, {user.papers}
							{user.papers === 1 ? 'paper' : 'papers'}</small
						>
					</span>
					<button onclick={() => choose(user)} aria-expanded={open === user.id}>
						{open === user.id ? 'Cancel' : 'Hand over…'}
					</button>
				</div>
				{#if open === user.id}
					<div class="give">
						<p>{holds ? `Holds ${summary(holds)}.` : 'Counting…'}</p>
						<select bind:value={target} aria-label="New owner">
							<option value="">To…</option>
							<optgroup label="A group">
								{#each groups as group (group.id)}<option value="group:{group.id}"
										>{group.name}</option
									>{/each}
							</optgroup>
							<optgroup label="A person">
								{#each receivers as person (person.id)}<option value="user:{person.id}"
										>{person.username}</option
									>{/each}
							</optgroup>
						</select>
						<button class="primary" disabled={!target || busy} onclick={() => give(user)}>
							Hand over
						</button>
					</div>
				{/if}
			</li>
		{/each}
	</ul>
{:else}
	<p class="empty">Nobody is deactivated.</p>
{/if}

<style>
	.intro {
		margin: 14px 0 0;
	}
	h3 {
		margin: 22px 0 4px;
		font-size: var(--step-0);
	}
	.note {
		margin: 0 0 10px;
		font-size: var(--step--1);
		max-width: 70ch;
	}
	ul {
		margin: 0;
		padding: 0;
		list-style: none;
		border: 1px solid var(--rule);
		border-radius: 12px;
	}
	li + li {
		border-top: 1px solid var(--rule);
	}
	.joining li {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 8px 8px 14px;
	}
	.group {
		flex: 1;
		font-weight: 600;
	}
	.joining select {
		width: auto;
	}
	.icon {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		padding: 0;
		border: none;
		background: none;
		color: var(--muted);
	}
	.icon:hover {
		color: var(--danger);
	}
	.add {
		display: flex;
		gap: 8px;
		margin-top: 10px;
		max-width: 420px;
	}
	.add select {
		flex: 1;
	}
	.empty {
		margin: 0;
		padding: 12px 14px;
		border: 1px dashed var(--rule);
		border-radius: 12px;
		color: var(--muted);
	}
	.departed li {
		padding: 10px 14px;
	}
	.person {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}
	.person small {
		display: block;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.give {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px 10px;
		margin-top: 10px;
		padding: 10px 12px;
		border-radius: 10px;
		background: var(--rail);
	}
	.give p {
		flex: 1 1 100%;
		margin: 0;
	}
	.give select {
		flex: 1 1 200px;
		width: auto;
	}
</style>
