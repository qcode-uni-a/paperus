<script lang="ts">
	import { errorMessage, setAutomations } from '#lib/api/client.ts';
	import type { LibraryAutomations, ServerAutomations } from '#lib/api/generated/types.gen.ts';

	/** One library's automations (server: paperus.automations): a person's
	 * own (Settings → Automations) or a group's (on its page under Groups);
	 * switched by its owner, shown to the others. */
	let {
		automations = $bindable(),
		server,
		personal,
		orcid = null
	}: {
		automations: LibraryAutomations;
		server: ServerAutomations;
		personal: boolean;
		orcid?: string | null;
	} = $props();

	let saving = $state(false);
	let message = $state('');
	let error = $state('');

	async function change(key: 'own_papers' | 'open_access', on: boolean) {
		saving = true;
		message = error = '';
		const { data, error: failure } = await setAutomations({
			path: { library_id: automations.library_id },
			body: { [key]: on }
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
	<label class="option">
		<input
			type="checkbox"
			checked={automations.own_papers}
			disabled={!automations.can_change || saving}
			onchange={(event) => change('own_papers', event.currentTarget.checked)}
		/>
		<span>
			<strong>{personal ? 'Add my papers' : 'Add our members’ papers'}</strong>
			<small
				>{personal
					? 'Each morning, your papers that OpenAlex lists under your ORCID iD come into your library; new ones are celebrated. One you remove stays out.'
					: 'Each morning, the papers of the members who may add papers (by their ORCID iDs) come into the group’s library: a list of the group’s work. One removed stays out.'}</small
			>
			{#if personal && !orcid && automations.own_papers}<small class="note"
					>Needs your ORCID iD (under Account, above).</small
				>{/if}
		</span>
	</label>
	<label class="option">
		<input
			type="checkbox"
			checked={automations.open_access}
			disabled={!automations.can_change || saving}
			onchange={(event) => change('open_access', event.currentTarget.checked)}
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
{#if !automations.can_change}<p class="muted small">
		{personal ? '' : 'The group’s admins switch these.'}
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
	.option input:disabled + span {
		cursor: default;
	}
	.option span {
		display: grid;
		gap: 2px;
	}
	.option small {
		color: var(--muted);
		font-size: var(--step--1);
		max-width: 60ch;
	}
	.option small.note {
		color: var(--tag-amber-ink);
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
