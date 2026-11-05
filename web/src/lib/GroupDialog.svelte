<script lang="ts">
	import { changeGroup, createGroup, errorMessage, findUsers } from '#lib/api/client.ts';
	import type { GroupOut, UserBrief } from '#lib/api/generated/types.gen.ts';

	/** Create a group (top-level with a first admin, or inside ``parent``), or
	 * rename one. */
	let { onsaved }: { onsaved?: (id: string) => void } = $props();

	let dialog = $state<HTMLDialogElement>();
	let group = $state<GroupOut | null>(null);
	let parent = $state<GroupOut | null>(null);
	let name = $state('');
	let description = $state('');
	let adminName = $state('');
	let people = $state<UserBrief[]>([]);
	let error = $state('');
	let saving = $state(false);

	const topLevel = $derived(!group && !parent);

	export function open(options: { group?: GroupOut; parent?: GroupOut } = {}) {
		group = options.group ?? null;
		parent = options.parent ?? null;
		name = group?.name ?? '';
		description = group?.description ?? '';
		adminName = '';
		error = '';
		if (topLevel) findUsers().then(({ data }) => (people = data ?? []));
		dialog?.showModal();
	}

	async function save(event: SubmitEvent) {
		event.preventDefault();
		saving = true;
		error = '';
		const admin = people.find((person) => person.username === adminName.trim());
		if (topLevel && adminName.trim() && !admin) {
			saving = false;
			error = `No user “${adminName.trim()}”.`;
			return;
		}
		const body = { name, description: description.trim() || null };
		const result = group
			? await changeGroup({ path: { group_id: group.id }, body })
			: await createGroup({
					body: { ...body, parent_id: parent?.id ?? null, admin_id: admin?.id ?? null }
				});
		saving = false;
		if (!result.data) {
			error = errorMessage(result.error);
			return;
		}
		dialog?.close();
		onsaved?.(result.data.id);
	}
</script>

<dialog bind:this={dialog} aria-labelledby="group-dialog-title">
	<form onsubmit={save}>
		<h2 id="group-dialog-title">
			{group ? 'Edit group' : parent ? `New group in ${parent.name}` : 'New group'}
		</h2>
		<label>Name <input bind:value={name} required maxlength="200" /></label>
		<label>
			Description <span class="optional">(optional)</span>
			<textarea bind:value={description} rows="2"></textarea>
		</label>
		{#if topLevel}
			<label>
				First admin <span class="optional">(you, if left empty)</span>
				<input bind:value={adminName} list="group-admins" autocomplete="off" />
				<datalist id="group-admins">
					{#each people as person (person.id)}<option value={person.username}></option>{/each}
				</datalist>
			</label>
		{:else if parent}
			<p class="note">
				Everyone in {parent.name} is in the new group too, with the same role. Add people who should see
				only this group's papers afterwards.
			</p>
		{/if}
		{#if error}<p class="error">{error}</p>{/if}
		<div class="buttons">
			<button type="button" onclick={() => dialog?.close()}>Cancel</button>
			<button class="primary" disabled={saving}>{group ? 'Save' : 'Create group'}</button>
		</div>
	</form>
</dialog>

<style>
	dialog {
		width: min(480px, calc(100vw - 32px));
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
	label :global(input),
	label :global(textarea) {
		font-weight: 400;
	}
	.optional {
		font-weight: 400;
		color: var(--muted);
	}
	.note {
		margin: 0;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
	.error {
		margin: 0;
	}
</style>
