<script lang="ts">
	import { admin } from '#lib/admin/data.svelte.ts';
	import { saveConfig } from '#lib/admin/config.svelte.ts';
	import SectionButtons from '#lib/admin/SectionButtons.svelte';
	import SettingRow from '#lib/admin/SettingRow.svelte';
	import type { SystemConfig } from '#lib/api/generated/types.gen.ts';

	type Level = NonNullable<SystemConfig['log_level']>;
	const LEVELS: [Level, string][] = [
		['debug', 'Debug: everything, for finding faults'],
		['info', 'Info: what happens (default)'],
		['warning', 'Warnings: only what went wrong or may'],
		['error', 'Errors only']
	];

	const config = $derived(admin.config);
	let level = $state<Level>('info');
	let saving = $state(false);

	function reset() {
		level = config?.log_level ?? 'info';
	}
	// The page reloads its data every few seconds: start over only when the
	// saved values change (not while someone is typing).
	let seen = '';
	$effect(() => {
		if (!config) return;
		const saved = JSON.stringify([config.log_level]);
		if (saved === seen) return;
		seen = saved;
		reset();
	});
	const changed = $derived(!!config && level !== (config.log_level ?? 'info'));

	async function save() {
		saving = true;
		await saveConfig({ log_level: level }, 'Logging settings');
		saving = false;
	}
</script>

<SettingRow
	id="log-level"
	title="Log level"
	description="How much the server and the worker write to their logs: under Administration → Logs (the last two weeks) and in docker compose logs. Applies within a minute, no restart."
>
	<select id="log-level" bind:value={level}>
		{#each LEVELS as [value, label] (value)}<option {value}>{label}</option>{/each}
	</select>
</SettingRow>
<SectionButtons {changed} {saving} onreset={reset} onsave={save} />
