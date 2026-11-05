<script lang="ts">
	import { resolve } from '$app/paths';
	import { admin } from '#lib/admin/data.svelte.ts';
	import { saveConfig } from '#lib/admin/config.svelte.ts';
	import SectionButtons from '#lib/admin/SectionButtons.svelte';
	import SettingRow from '#lib/admin/SettingRow.svelte';
	import Stepper from '#lib/admin/Stepper.svelte';
	import { listBackups } from '#lib/api/client.ts';
	import type { BackupConfig } from '#lib/api/generated/types.gen.ts';
	import { localTime } from '#lib/format.ts';

	const config = $derived(admin.config);
	let text = $state(2);
	let ml = $state(1);
	let imports = $state(1);
	let night = $state(2);
	let saving = $state(false);
	let backups = $state<BackupConfig | null>(null);

	$effect(() => {
		listBackups().then(({ data }) => (backups = data?.config ?? null));
	});

	function reset() {
		text = config?.jobs_text ?? 2;
		ml = config?.jobs_ml ?? 1;
		imports = config?.jobs_import ?? 1;
		night = config?.night_hour ?? 2;
	}
	// The page reloads its data every few seconds: start over only when the
	// saved values change (not while someone is choosing).
	let seen = '';
	$effect(() => {
		if (!config) return;
		const saved = JSON.stringify([
			config.jobs_text,
			config.jobs_ml,
			config.jobs_import,
			config.night_hour
		]);
		if (saved === seen) return;
		seen = saved;
		reset();
	});

	const changed = $derived(
		!!config &&
			(text !== config.jobs_text ||
				ml !== config.jobs_ml ||
				imports !== config.jobs_import ||
				night !== config.night_hour)
	);

	async function save() {
		saving = true;
		await saveConfig(
			{ jobs_text: text, jobs_ml: ml, jobs_import: imports, night_hour: night },
			'Job settings'
		);
		saving = false;
	}

	const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

	/** What runs when, with the saved settings. */
	const schedule = $derived.by(() => {
		if (!config) return [];
		const integrity = {
			off: null,
			daily: `Every night at ${localTime(config.night_hour ?? 2, 45)}`,
			weekly: `Sundays at ${localTime(config.night_hour ?? 2, 45)}`
		}[config.integrity_schedule ?? 'weekly'];
		const backup =
			backups && backups.schedule !== 'off'
				? `${backups.schedule === 'daily' ? 'Every day' : 'Mondays'} at ${localTime(backups.hour ?? 3, 7)}`
				: null;
		return [
			{
				when:
					config.trash_days != null
						? `Every night at ${localTime(config.night_hour ?? 2, 30)}`
						: null,
				what: 'Empty the trash',
				detail:
					config.trash_days != null
						? `What has been in it more than ${config.trash_days} days`
						: 'Off (Trash settings)'
			},
			{
				when: integrity,
				what: 'Integrity check',
				detail: integrity ? 'Whether every file’s contents are there' : 'Off (Integrity checks)'
			},
			{
				when: backup,
				what: 'Backup',
				detail: backup ? (backups?.with_files ? 'Database and files' : 'Database only') : 'Off',
				href: resolve('/admin/backups')
			},
			{ when: 'Every 5 minutes', what: 'Read waiting files', detail: 'In case one was missed' },
			{
				when: 'Every 10 minutes',
				what: 'Vectors for search by meaning',
				detail: 'For passages that lack one'
			},
			{ when: 'Every minute', what: 'Settings to the ML service', detail: 'In case it restarted' }
		];
	});
</script>

<p class="muted intro">
	The worker reads uploaded files, computes their vectors for search by meaning, runs imports, and
	does the maintenance (backups, the trash, integrity checks) one job at a time. Changes apply
	within half a minute; running jobs finish first.
</p>

<SettingRow
	id="jobs-text"
	title="Files read at once"
	description="Each takes a CPU core while it reads a PDF. More: large uploads are searchable sooner."
>
	<Stepper id="jobs-text" label="Files read at once" bind:value={text} min={1} max={16} />
</SettingRow>
<SettingRow
	id="jobs-ml"
	title="Files sent to the ML service at once"
	description="The ML service computes one batch at a time per model; more helps only with several ML services or a GPU."
>
	<Stepper
		id="jobs-ml"
		label="Files sent to the ML service at once"
		bind:value={ml}
		min={1}
		max={8}
	/>
</SettingRow>
<SettingRow
	id="jobs-import"
	title="Imports at once"
	description="Imports from Zotero and others. One person's imports always run one after another."
>
	<Stepper id="jobs-import" label="Imports at once" bind:value={imports} min={1} max={4} />
</SettingRow>
<SettingRow
	id="night-hour"
	title="Night jobs start at"
	description="When the trash is emptied and the integrity check runs; best when nobody works. In your time zone."
>
	<select id="night-hour" bind:value={night}>
		{#each HOURS as hour (hour)}<option value={hour}>{localTime(hour)}</option>{/each}
	</select>
</SettingRow>
<SectionButtons {changed} {saving} onreset={reset} onsave={save} />

<h3>What runs when</h3>
<ul class="schedule">
	{#each schedule as row (row.what)}
		<li class:off={!row.when}>
			<span class="when">{row.when ?? 'Off'}</span>
			<span class="what">
				{#if row.href}<a href={row.href}>{row.what}</a>{:else}{row.what}{/if}
				<small>{row.detail}</small>
			</span>
		</li>
	{/each}
</ul>
<p class="muted small">
	What is waiting or running now: <a href={resolve('/admin/jobs')}>Administration → Jobs</a>.
</p>

<style>
	.intro {
		margin: 14px 0 4px;
	}
	h3 {
		margin: 20px 0 8px;
		font-size: var(--step-0);
	}
	.schedule {
		margin: 0;
		padding: 0;
		list-style: none;
		border: 1px solid var(--rule);
		border-radius: 12px;
	}
	.schedule li {
		display: grid;
		grid-template-columns: 14rem minmax(0, 1fr);
		gap: 4px 16px;
		padding: 10px 14px;
	}
	.schedule li + li {
		border-top: 1px solid var(--rule);
	}
	.when {
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.off .when {
		color: var(--muted);
		font-weight: 400;
	}
	.what small {
		display: block;
		color: var(--muted);
		font-size: var(--step--1);
	}
	.small {
		margin: 8px 0 0;
		font-size: var(--step--1);
	}
	@media (max-width: 560px) {
		.schedule li {
			grid-template-columns: minmax(0, 1fr);
		}
	}
</style>
