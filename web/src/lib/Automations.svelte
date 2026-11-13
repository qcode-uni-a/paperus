<script lang="ts">
	import { resolve } from '$app/paths';
	import { getAutomations } from '#lib/api/client.ts';
	import type { Automations } from '#lib/api/generated/types.gen.ts';
	import LibraryAutomations from '#lib/LibraryAutomations.svelte';
	import { libraryById, libraryName } from '#lib/organize.svelte.ts';
	import { session } from '#lib/session.svelte.ts';

	/** Settings → Automations: what paperus does by itself, for one's own
	 * library (switched here), one's groups' (on their pages) and the whole
	 * server (the administrator's). */
	let found = $state<Automations | null>(null);
	$effect(() => {
		getAutomations().then(({ data }) => (found = data ?? null));
	});
	const own = $derived(
		found?.libraries.find((l) => libraryById(l.library_id)?.kind === 'personal')
	);
	const groups = $derived(
		found?.libraries.filter((l) => libraryById(l.library_id)?.kind === 'group') ?? []
	);
	const onOff = (on: boolean) => (on ? 'on' : 'off');

	/** What the server does by itself, as people know it. */
	const SERVER = [
		['find_published', 'Published versions of preprints are looked for (where wanted)'],
		['find_errata', 'Corrections (errata) to papers are looked for'],
		['find_references', 'Papers’ reference lists are looked for'],
		['find_authors', 'Authors are recognised by their ORCID iDs (OpenAlex)'],
		['open_access', 'Free PDFs are fetched (where a library wants them)'],
		['ocr', 'Scanned pages are read (OCR)']
	] as const;
</script>

{#if found}
	<p class="muted">What paperus does by itself, for your papers.</p>
	{#if own}
		<h3>Your library</h3>
		<LibraryAutomations
			bind:automations={found.libraries[found.libraries.indexOf(own)]}
			server={found.server}
			orcid={session.user?.orcid ?? null}
		/>
	{/if}

	{#if groups.length}
		<h3>Your groups</h3>
		<ul class="groups">
			{#each groups as group (group.library_id)}
				{@const library = libraryById(group.library_id)}
				<li>
					<a href="{resolve('/manage/groups')}?group={library?.group_id}"
						>{libraryName(group.library_id)}</a
					>
					<span class="muted"
						>published versions {onOff(group.published)}, free PDFs {onOff(group.open_access)}</span
					>
				</li>
			{/each}
		</ul>
		<p class="muted small">Each group’s admins switch these on the group’s page.</p>
	{/if}

	<h3>On this server</h3>
	<ul class="server">
		{#each SERVER as [key, label] (key)}
			<li class:off={!found.server[key]}>
				<span class="state">{found.server[key] ? 'On' : 'Off'}</span>{label}
			</li>
		{/each}
	</ul>
	{#if session.user?.is_admin}
		<p class="small"><a href={resolve('/admin/settings')}>Change them under Administration</a></p>
	{:else}
		<p class="muted small">The administrator decides these, for everyone.</p>
	{/if}
{/if}

<style>
	h3 {
		margin: 18px 0 8px;
		font-size: var(--step-0);
	}
	p {
		margin: 0 0 10px;
		max-width: 60ch;
	}
	.small {
		font-size: var(--step--1);
	}
	ul {
		margin: 0 0 8px;
		padding: 0;
		list-style: none;
		display: grid;
		gap: 6px;
	}
	.groups li {
		display: flex;
		flex-wrap: wrap;
		gap: 2px 12px;
		align-items: baseline;
	}
	.groups span {
		font-size: var(--step--1);
	}
	.server li {
		display: flex;
		gap: 10px;
		align-items: baseline;
		font-size: var(--step--1);
	}
	.state {
		flex: none;
		width: 2.6em;
		font-weight: 650;
		color: var(--success);
	}
	.off .state {
		color: var(--muted);
	}
	.off {
		color: var(--muted);
	}
</style>
