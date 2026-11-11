<script lang="ts">
	import { resolve } from '$app/paths';
	import { addItem } from '#lib/api/client.ts';
	import type { WorkOut } from '#lib/api/generated/types.gen.ts';
	import { defaultLibrary, libraryName, writableLibraries } from '#lib/organize.svelte.ts';
	import { addByDoi } from '#lib/tasks.svelte.ts';

	/** Someone's works as OpenAlex knows them: those not in the library
	 * can be chosen and added, by their DOI (their details, open-access
	 * copy, authors and references follow as for any paper added so). */
	let {
		title,
		load,
		onadded
	}: {
		title: string;
		/** The works, or why there are none. */
		load: () => Promise<{ works: WorkOut[] } | { error: string }>;
		onadded?: () => void;
	} = $props();

	let dialog = $state<HTMLDialogElement>();
	let found = $state<WorkOut[] | null>(null);
	let error = $state('');
	let chosen = $state<string[]>([]);
	let owner = $state('');

	const missing = $derived((found ?? []).filter((w) => !w.item_id));
	const here = $derived((found ?? []).filter((w) => w.item_id));

	export async function open() {
		found = null;
		error = '';
		chosen = [];
		owner = defaultLibrary()?.id ?? writableLibraries()[0]?.id ?? '';
		dialog?.showModal();
		const result = await load();
		if ('error' in result) {
			error = result.error;
			return;
		}
		found = result.works;
		chosen = missing.map((w) => w.doi);
	}

	/** Added a few at a time, in the corner's task (one may move on). */
	function add() {
		const dois = [...chosen];
		dialog?.close();
		void addByDoi(
			`Adding ${dois.length} ${dois.length === 1 ? 'paper' : 'papers'}`,
			dois,
			owner || null,
			onadded
		);
	}
</script>

{#snippet work(item: WorkOut)}
	<span class="work">
		<span class="title">{item.title}</span>
		<small class="muted"
			>{[item.journal, item.year].filter(Boolean).join(', ') || `DOI ${item.doi}`}</small
		>
	</span>
{/snippet}

<dialog bind:this={dialog} aria-labelledby="works-title">
	<h2 id="works-title">{title}</h2>
	{#if error}
		<p class="error">{error}</p>
	{:else if found === null}
		<p class="muted">Asking OpenAlex…</p>
	{:else if found.length === 0}
		<p class="muted">OpenAlex knows no papers with a DOI for them.</p>
	{:else}
		<p class="muted">
			{found.length}
			{found.length === 1 ? 'paper' : 'papers'} at OpenAlex, {missing.length} not in your library.
		</p>
		{#if missing.length}
			<div class="choose">
				<button class="link" onclick={() => (chosen = missing.map((w) => w.doi))}>All</button>
				<button class="link" onclick={() => (chosen = [])}>None</button>
			</div>
			<ul class="scroll">
				{#each missing as item (item.doi)}
					<li>
						<label
							><input type="checkbox" bind:group={chosen} value={item.doi} />{@render work(
								item
							)}</label
						>
					</li>
				{/each}
			</ul>
		{/if}
		{#if here.length}
			<details>
				<summary>{here.length} in your library already</summary>
				<ul>
					{#each here as item (item.doi)}
						<li>
							<a href={resolve('/items/[id]', { id: item.item_id! })}>{@render work(item)}</a>
						</li>
					{/each}
				</ul>
			</details>
		{/if}
	{/if}
	<footer>
		{#if missing.length && writableLibraries().length > 1}
			<label class="owner"
				>Add to <select bind:value={owner}>
					{#each writableLibraries() as library (library.id)}
						<option value={library.id}>{libraryName(library.id)}</option>
					{/each}
				</select></label
			>
		{/if}
		<div class="buttons">
			<button onclick={() => dialog?.close()}>Close</button>
			{#if missing.length}
				<button class="primary" onclick={add} disabled={!chosen.length}>
					Add {chosen.length}
					{chosen.length === 1 ? 'paper' : 'papers'}
				</button>
			{/if}
		</div>
	</footer>
	{#if error === '' && found !== null}<p class="hint muted">
			Listed by OpenAlex, found by their ORCID iD or OpenAlex id.
		</p>{/if}
</dialog>

<style>
	dialog {
		width: min(720px, calc(100vw - 32px));
		max-height: calc(100vh - 32px);
		padding: 20px 24px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	dialog::backdrop {
		background: rgb(10 14 30 / 0.5);
	}
	h2 {
		margin: 0 0 6px;
		font-size: var(--step-2);
	}
	ul {
		display: grid;
		gap: 2px;
		margin: 8px 0;
		padding: 0;
		list-style: none;
	}
	li label,
	li a {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		padding: 6px 8px;
		border-radius: var(--radius);
		color: var(--ink);
		text-decoration: none;
		cursor: pointer;
	}
	li label:hover,
	li a:hover {
		background: var(--rail);
	}
	li input {
		width: auto;
		margin-top: 4px;
	}
	/* A long list scrolls; the buttons stay in sight. */
	.scroll {
		max-height: min(52vh, 560px);
		overflow-y: auto;
		overscroll-behavior: contain;
	}
	.work {
		display: grid;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.title {
		font-family: var(--serif);
	}
	.choose {
		display: flex;
		gap: 12px;
	}
	details summary {
		cursor: pointer;
		color: var(--muted);
	}
	footer {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: center;
		gap: 10px;
		margin-top: 12px;
		padding-top: 12px;
		border-top: 1px solid var(--rule);
	}
	.owner {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.owner select {
		width: auto;
	}
	.buttons {
		display: flex;
		gap: 8px;
		margin-left: auto;
	}
	.hint {
		margin: 8px 0 0;
		font-size: var(--step--1);
	}
</style>
