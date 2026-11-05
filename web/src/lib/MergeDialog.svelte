<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import {
		errorMessage,
		listDuplicates,
		listItems,
		mergeItem,
		type Item,
		type ItemDetail
	} from '#lib/api/client.ts';
	import { shortAuthors } from '#lib/format.ts';
	import { libraryById, libraryName, loadOrganize } from '#lib/organize.svelte.ts';

	/** Merge this paper into another one (the same paper twice). */
	let { item }: { item: ItemDetail } = $props();

	let dialog = $state<HTMLDialogElement>();
	let likely = $state<Item[]>([]);
	let words = $state('');
	let found = $state<Item[]>([]);
	let chosen = $state<Item | null>(null);
	let error = $state('');
	let merging = $state(false);
	let latest = 0;

	const writableTarget = $derived(
		chosen ? (libraryById(chosen.library_id)?.writable ?? false) : false
	);

	export async function open() {
		words = '';
		chosen = null;
		error = '';
		found = [];
		dialog?.showModal();
		const { data } = await listDuplicates({ path: { item_id: item.id } });
		likely = data ?? [];
	}

	$effect(() => {
		const query = words.trim();
		const request = ++latest;
		if (!query) {
			found = [];
			return;
		}
		const timer = setTimeout(async () => {
			const { data } = await listItems({ query: { title: query, limit: 20 } });
			if (request === latest) found = (data ?? []).filter((other) => other.id !== item.id);
		}, 200);
		return () => clearTimeout(timer);
	});

	/** "Huber and Koren (2026), Shared library", leaving out what is missing. */
	function meta(other: Item): string {
		const who = [shortAuthors(other.authors), other.year ? `(${other.year})` : '']
			.filter(Boolean)
			.join(' ');
		return [who, libraryName(other.library_id)].filter(Boolean).join(', ');
	}

	async function merge() {
		if (!chosen) return;
		merging = true;
		const { data, error: failure } = await mergeItem({
			path: { item_id: item.id },
			body: { into: chosen.id }
		});
		merging = false;
		if (!data) {
			error = errorMessage(failure);
			return;
		}
		dialog?.close();
		await loadOrganize();
		if (data.left_behind.length) {
			alert(`Merged. Stayed with the paper in the trash: ${data.left_behind.join(', ')}.`);
		}
		await goto(resolve('/items/[id]', { id: data.item.id }));
	}
</script>

{#snippet choice(other: Item)}
	<li>
		<button class="paper" class:chosen={chosen?.id === other.id} onclick={() => (chosen = other)}>
			<strong>{other.title}</strong>
			<small>{meta(other)}</small>
		</button>
	</li>
{/snippet}

<dialog bind:this={dialog} aria-labelledby="merge-title">
	<h2 id="merge-title">Merge into another paper</h2>
	<p class="muted">
		For the same paper twice. This one goes to the trash; the paper you choose keeps its details and
		takes over this one's versions, files, tags and collections.
	</p>

	{#if likely.length}
		<h3>Likely the same paper</h3>
		<ul>
			{#each likely as other (other.id)}{@render choice(other)}{/each}
		</ul>
	{/if}

	<input
		type="search"
		bind:value={words}
		placeholder="Search by title"
		aria-label="Search papers"
	/>
	{#if found.length}
		<ul>
			{#each found as other (other.id)}{@render choice(other)}{/each}
		</ul>
	{/if}

	{#if chosen}
		<p class="note">
			Merging into <em>{chosen.title}</em>{writableTarget
				? '.'
				: `: you may not change it, so only your private tags and collections move; versions and files stay with this paper in the trash.`}
		</p>
	{/if}
	{#if error}<p class="error">{error}</p>{/if}
	<div class="buttons">
		<button type="button" onclick={() => dialog?.close()}>Cancel</button>
		<button class="primary" disabled={!chosen || merging} onclick={merge}>Merge</button>
	</div>
</dialog>

<style>
	dialog {
		width: min(600px, calc(100vw - 32px));
		max-height: min(760px, calc(100dvh - 32px));
		padding: 22px 24px 20px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	dialog[open] {
		display: grid;
		gap: 10px;
		overflow-y: auto;
	}
	dialog::backdrop {
		background: rgb(10 14 30 / 0.4);
	}
	h2 {
		margin: 0;
		font-size: var(--step-2);
	}
	h3 {
		margin: 6px 0 0;
		font-size: var(--step-0);
	}
	p {
		margin: 0;
	}
	ul {
		margin: 0;
		padding: 0;
		list-style: none;
		display: grid;
		gap: 4px;
	}
	.paper {
		display: grid;
		gap: 2px;
		width: 100%;
		padding: 8px 10px;
		border: 1px solid var(--rule);
		border-radius: var(--radius);
		background: none;
		text-align: left;
		color: var(--ink);
	}
	.paper:hover:not(:disabled) {
		background: var(--rail);
	}
	.paper.chosen {
		border-color: var(--royal);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--royal) 25%, transparent);
	}
	.paper strong {
		font-family: var(--serif);
		font-weight: 600;
	}
	.paper small {
		color: var(--muted);
		font-size: var(--step--1);
	}
	.note {
		padding: 8px 12px;
		border-left: 3px solid var(--highlighter);
		background: var(--rail);
		font-size: var(--step--1);
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
</style>
