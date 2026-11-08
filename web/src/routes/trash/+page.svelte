<script lang="ts">
	import { resolve } from '$app/paths';
	import {
		emptyTrash,
		listItems,
		listNotes,
		restoreItem,
		restoreNote,
		trashRules,
		type Item
	} from '#lib/api/client.ts';
	import { formatLongDate } from '#lib/dates.svelte.ts';
	import { session } from '#lib/session.svelte.ts';
	import { notify } from '#lib/toasts.svelte.ts';
	import type { NoteOut, TrashRules } from '#lib/api/generated/types.gen.ts';
	import ItemRow from '#lib/ItemRow.svelte';
	import NoteRow from '#lib/NoteRow.svelte';

	let items = $state<Item[] | null>(null);
	let notes = $state<NoteOut[]>([]);
	let rules = $state<TrashRules | null>(null);

	async function load() {
		const [papers, written] = await Promise.all([
			listItems({ query: { trashed: true, limit: 200 } }),
			listNotes({ query: { trashed: true, limit: 200 } })
		]);
		items = papers.data ?? [];
		notes = written.data ?? [];
	}

	$effect(() => {
		load();
		trashRules().then(({ data }) => (rules = data ?? null));
	});

	/** When the nightly emptying (half past the night hour, UTC) takes what
	 * went into the trash at `trashed`: the first one after the days set. */
	function goneOn(trashed: string, { days, night_hour }: TrashRules & { days: number }): Date {
		const due = new Date(new Date(trashed).getTime() + days * 24 * 3600 * 1000);
		const run = new Date(due);
		run.setUTCHours(night_hour, 30, 0, 0);
		if (run <= due) run.setUTCDate(run.getUTCDate() + 1);
		return run;
	}

	/** Everything here one may change, deleted for good (others' stays). */
	async function emptyAll() {
		const count = (items?.length ?? 0) + notes.length;
		if (
			!confirm(
				`Delete ${count} ${count === 1 ? 'thing' : 'things'} in the trash for good? ` +
					'This cannot be undone. (Things of groups where you only read stay.)'
			)
		)
			return;
		const { data } = await emptyTrash();
		if (data)
			notify({
				kind: 'success',
				title: 'Trash emptied',
				text: `${data.items} papers, ${data.notes} notes and ${data.files} files deleted for good.`
			});
		await load();
	}

	async function restore(id: string) {
		await restoreItem({ path: { item_id: id } });
		await load();
	}

	async function restoreWritten(id: string) {
		await restoreNote({ path: { note_id: id } });
		await load();
	}
</script>

<header class="head">
	<h1>Trash</h1>
	{#if (items?.length ?? 0) + notes.length > 0}
		<button class="danger-button" onclick={emptyAll}>Empty trash</button>
	{/if}
</header>
{#if rules}
	<p class="muted rules">
		{#if rules.days != null}
			Papers, files and notes are deleted for good {rules.days}
			{rules.days === 1 ? 'day' : 'days'} after they were moved to the trash. Until then you can restore
			them.
		{:else}
			Papers, files and notes stay in the trash until someone empties it.
		{/if}
		{#if session.user?.is_admin}
			<a href="{resolve('/admin/settings')}?open=trash">Change in Settings</a>
		{/if}
	</p>
{/if}
{#if items?.length === 0 && notes.length === 0}
	<p class="muted">The trash is empty.</p>
{/if}
{#snippet gone(trashed: string | null | undefined)}
	{#if trashed && rules?.days != null}
		{@const on = goneOn(trashed, { ...rules, days: rules.days })}
		<span class="muted gone">
			{on.getTime() > Date.now()
				? `Deleted for good on ${formatLongDate(on)}`
				: 'Deleted for good soon'}
		</span>
	{/if}
{/snippet}
<ul>
	{#each items ?? [] as item (item.id)}
		<ItemRow {item}>
			{#snippet actions()}<button onclick={() => restore(item.id)}>Restore</button>{@render gone(
					item.deleted_at
				)}{/snippet}
		</ItemRow>
	{/each}
	{#each notes as note (note.id)}
		<NoteRow {note}>
			{#snippet actions()}<button onclick={() => restoreWritten(note.id)}>Restore</button
				>{@render gone(note.deleted_at)}{/snippet}
		</NoteRow>
	{/each}
</ul>

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
	}
	.danger-button {
		border-color: var(--danger);
		color: var(--danger);
	}
	ul {
		padding: 0;
	}
	.rules {
		max-width: 44rem;
	}
	.gone {
		margin-left: 12px;
		font-size: 0.875rem;
	}
</style>
