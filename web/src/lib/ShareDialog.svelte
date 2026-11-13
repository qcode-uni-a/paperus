<script lang="ts">
	import Title from '#lib/Title.svelte';
	import { errorMessage, findUsers, groupOfPeople, setOwner } from '#lib/api/client.ts';
	import type { UserBrief } from '#lib/api/generated/types.gen.ts';
	import { isShared, libraryName, loadOrganize, writableLibraries } from '#lib/organize.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import { notify } from '#lib/toasts.svelte.ts';

	/** Share a paper with a group, or with people (#16): the group, or the
	 * people's own small group ("Anna & Ben", made the first time), becomes
	 * its owner, so everyone in it sees the paper (one copy for all). */
	let {
		item,
		onshared
	}: { item: { id: string; title: string; library_id: string }; onshared: () => void } = $props();

	let dialog = $state<HTMLDialogElement>();
	let mode = $state<'group' | 'people'>('group');
	let group = $state('');
	let saving = $state(false);
	let error = $state('');

	// Research groups here; groups of people are reached through their people.
	const groups = $derived(
		writableLibraries().filter((l) => isShared(l.id) && !l.people && l.id !== item.library_id)
	);

	// People, found by name.
	let search = $state('');
	let found = $state<UserBrief[]>([]);
	let people = $state<UserBrief[]>([]);
	const shown = (user: UserBrief) => user.display_name || user.username;
	$effect(() => {
		const words = search.trim();
		if (words.length < 2) {
			found = [];
			return;
		}
		const timer = setTimeout(async () => {
			const { data } = await findUsers({ query: { q: words } });
			if (words !== search.trim()) return;
			found = (data ?? []).filter(
				(u) => u.id !== session.user?.id && !people.some((p) => p.id === u.id)
			);
		}, 200);
		return () => clearTimeout(timer);
	});
	function pick(user: UserBrief) {
		people = [...people, user];
		search = '';
		found = [];
	}
	const withWhom = $derived(people.length === 1 ? shown(people[0]) : `${people.length} people`);

	export function open() {
		mode = groups.length ? 'group' : 'people';
		group = groups[0]?.id ?? '';
		people = [];
		search = '';
		error = '';
		dialog?.showModal();
	}

	async function share(event: SubmitEvent) {
		event.preventDefault();
		saving = true;
		error = '';
		let target = group;
		if (mode === 'people') {
			const { data, error: failure } = await groupOfPeople({
				body: { user_ids: people.map((p) => p.id) }
			});
			if (!data) {
				saving = false;
				error = errorMessage(failure);
				return;
			}
			target = data.library_id;
			await loadOrganize(); // a new group of people is among the owners now
		}
		if (target === item.library_id) {
			saving = false;
			dialog?.close();
			notify({ kind: 'info', title: `Already shared with ${libraryName(target)}` });
			return;
		}
		const { error: failure } = await setOwner({
			path: { item_id: item.id },
			body: { library_id: target }
		});
		saving = false;
		if (failure) {
			error = errorMessage(failure);
			return;
		}
		dialog?.close();
		notify({ kind: 'success', title: `Shared with ${libraryName(target)}` });
		onshared();
	}
</script>

<dialog bind:this={dialog} aria-labelledby="share-title">
	<form onsubmit={share}>
		<h2 id="share-title">Share</h2>
		<fieldset class="modes">
			<legend class="visually-hidden">Share with</legend>
			<label class="mode"><input type="radio" bind:group={mode} value="people" /> With people</label
			>
			<label class="mode"
				><input type="radio" bind:group={mode} value="group" disabled={!groups.length} /> With a group</label
			>
		</fieldset>

		{#if mode === 'people'}
			<div class="people">
				{#each people as user (user.id)}
					<span class="chip"
						>{shown(user)}<button
							type="button"
							aria-label="Remove {shown(user)}"
							onclick={() => (people = people.filter((p) => p.id !== user.id))}>×</button
						></span
					>
				{/each}
				<input
					type="search"
					bind:value={search}
					placeholder={people.length ? 'Someone else…' : 'Name…'}
					aria-label="Find a person"
					autocomplete="off"
				/>
			</div>
			{#if found.length}
				<div class="found">
					{#each found as user (user.id)}
						<button type="button" class="pick" onclick={() => pick(user)}
							>{shown(user)}
							{#if user.display_name}<span class="muted">{user.username}</span>{/if}</button
						>
					{/each}
				</div>
			{/if}
			<p class="note">
				{#if people.length}
					{people.length === 1 ? shown(people[0]) : 'They'} and you share “<Title
						text={item.title}
					/>” and its files, in a group of your own (under Groups, where you can add more people or
					rename it); your tags and notes on it stay yours.
				{:else}
					Find people by their name (from two letters on).
				{/if}
			</p>
		{:else}
			<label>
				Group
				<select bind:value={group}>
					{#each groups as option (option.id)}
						<option value={option.id}>{libraryName(option.id)}</option>
					{/each}
				</select>
			</label>
			<p class="note">
				Everyone in {libraryName(group)} sees “<Title text={item.title} />”, its files and the
				group's tags on it.
				{#if isShared(item.library_id)}
					{libraryName(item.library_id)} no longer sees it, and its collections let it go.
				{:else}
					Your own tags and notes on it stay yours.
				{/if}
			</p>
		{/if}
		{#if error}<p class="error">{error}</p>{/if}
		<div class="buttons">
			<button type="button" onclick={() => dialog?.close()}>Cancel</button>
			<button class="primary" disabled={saving || (mode === 'people' ? !people.length : !group)}
				>{mode === 'people' && people.length ? `Share with ${withWhom}` : 'Share'}</button
			>
		</div>
	</form>
</dialog>

<style>
	dialog {
		width: min(460px, calc(100vw - 32px));
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
		gap: 14px;
	}
	h2 {
		margin: 0;
		font-size: var(--step-2);
	}
	label {
		display: grid;
		gap: 6px;
		font-weight: 600;
	}
	label select {
		font-weight: 400;
	}
	p {
		margin: 0;
	}
	.note {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
	.modes {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 18px;
		margin: 0;
		padding: 0;
		border: none;
	}
	.mode {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-weight: 400;
	}
	.mode input {
		width: auto;
		margin: 0;
	}
	.people,
	.found {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
	}
	.people input {
		flex: 1 1 10rem;
		min-width: 0;
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		padding: 2px 4px 2px 10px;
		border-radius: 999px;
		background: var(--tag-blue-bg);
		color: var(--tag-blue-ink);
		font-size: var(--step--1);
	}
	.chip button {
		width: 22px;
		height: 22px;
		padding: 0;
		border: none;
		border-radius: 50%;
		background: none;
		color: inherit;
		line-height: 1;
	}
	.pick {
		padding: 2px 10px;
		border-radius: 14px;
	}
	.muted {
		color: var(--muted);
	}
</style>
