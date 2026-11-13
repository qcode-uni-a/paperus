<script lang="ts">
	import { errorMessage, setAutomations } from '#lib/api/client.ts';
	import type {
		AutomationsIn,
		LibraryAutomations,
		ServerAutomations
	} from '#lib/api/generated/types.gen.ts';
	import { defaultLibrary, libraryName, writableLibraries } from '#lib/organize.svelte.ts';

	/** One library's automations (server: paperus.automations): a person's
	 * own (Settings → Automations, with adding their own papers) or a
	 * group's (on its page under Groups); switched by its owner, shown to
	 * the others. */
	let {
		automations = $bindable(),
		server,
		orcid = null
	}: {
		automations: LibraryAutomations;
		server: ServerAutomations;
		orcid?: string | null;
	} = $props();

	const personal = $derived(
		automations.own_papers !== null && automations.own_papers !== undefined
	);
	const LIKE_NEW = 'new papers';
	// Where one's papers go: as chosen, else where new papers go.
	const into = $derived(automations.own_papers_to ?? LIKE_NEW);

	let saving = $state(false);
	let message = $state('');
	let error = $state('');

	async function change(body: AutomationsIn) {
		saving = true;
		message = error = '';
		const { data, error: failure } = await setAutomations({
			path: { library_id: automations.library_id },
			body
		});
		saving = false;
		if (!data) {
			error = errorMessage(failure);
			return;
		}
		automations = data;
		message = 'Saved.';
	}
</script>

<fieldset>
	<legend class="visually-hidden">Automations</legend>
	{#if personal}
		<div class="option">
			<input
				id="own-papers"
				type="checkbox"
				checked={automations.own_papers ?? false}
				disabled={!automations.can_change || saving}
				onchange={(event) => change({ own_papers: event.currentTarget.checked })}
			/>
			<span>
				<label for="own-papers"><strong>Add my papers</strong></label>
				<small
					>Each morning, your papers that OpenAlex lists under your ORCID iD and that are not in a
					library you can see yet are added; new ones are celebrated. One you remove stays out.</small
				>
				{#if automations.own_papers}
					<label class="into">
						<small>Into</small>
						<select
							value={into}
							disabled={!automations.can_change || saving}
							onchange={(event) => change({ own_papers_to: event.currentTarget.value })}
						>
							<option value={LIKE_NEW}
								>where your new papers go ({libraryName(defaultLibrary()?.id)})</option
							>
							{#each writableLibraries() as library (library.id)}
								<option value={library.id}>{libraryName(library.id)}</option>
							{/each}
						</select>
					</label>
				{/if}
				{#if !orcid && automations.own_papers}<small class="note"
						>Needs your ORCID iD (under Account, above).</small
					>{/if}
			</span>
		</div>
	{/if}
	<label class="option">
		<input
			type="checkbox"
			checked={automations.published}
			disabled={!automations.can_change || saving}
			onchange={(event) => change({ published: event.currentTarget.checked })}
		/>
		<span>
			<strong>Published versions</strong>
			<small
				>The journal versions of preprints here are looked for and added to them (where they are),
				to cite.</small
			>
			{#if !server.find_published}<small class="note"
					>Off on this server for now: the administrator decides.</small
				>{/if}
		</span>
	</label>
	<label class="option">
		<input
			type="checkbox"
			checked={automations.open_access}
			disabled={!automations.can_change || saving}
			onchange={(event) => change({ open_access: event.currentTarget.checked })}
		/>
		<span>
			<strong>Free PDFs</strong>
			<small
				>Papers here without a file get their open-access copy, where one exists (found through
				Unpaywall).</small
			>
			{#if !server.open_access}<small class="note"
					>Off on this server for now: the administrator decides.</small
				>{/if}
		</span>
	</label>
</fieldset>
{#if !automations.can_change && !personal}<p class="muted small">
		The group’s admins switch these.
	</p>{/if}
{#if message}<p class="saved" aria-live="polite">{message}</p>{/if}
{#if error}<p class="error">{error}</p>{/if}

<style>
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
		gap: 2px;
	}
	.option label {
		cursor: pointer;
	}
	.option small {
		color: var(--muted);
		font-size: var(--step--1);
		max-width: 60ch;
	}
	.option small.note {
		color: var(--tag-amber-ink);
	}
	.into {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 8px;
		margin-top: 4px;
	}
	.into select {
		width: auto;
		max-width: 100%;
		padding: 3px 8px;
		font-size: var(--step--1);
	}
	p {
		margin: 6px 0 0;
	}
	.small {
		font-size: var(--step--1);
	}
	.saved {
		color: var(--success);
		font-size: var(--step--1);
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
	}
</style>
