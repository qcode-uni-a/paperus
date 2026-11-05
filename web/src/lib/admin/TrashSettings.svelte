<script lang="ts">
	import { admin } from '#lib/admin/data.svelte.ts';
	import { saveConfig } from '#lib/admin/config.svelte.ts';
	import SectionButtons from '#lib/admin/SectionButtons.svelte';
	import SettingRow from '#lib/admin/SettingRow.svelte';
	import Switch from '#lib/admin/Switch.svelte';
	import { runJob } from '#lib/api/client.ts';
	import { notify } from '#lib/toasts.svelte.ts';

	const config = $derived(admin.config);
	let automatic = $state(false);
	let days = $state(30);
	let saving = $state(false);

	function reset() {
		automatic = config?.trash_days != null;
		days = config?.trash_days ?? 30;
	}
	// The page reloads its data every few seconds: start over only when the
	// saved values change (not while someone is typing).
	let seen = '';
	$effect(() => {
		if (!config) return;
		const saved = JSON.stringify([config.trash_days]);
		if (saved === seen) return;
		seen = saved;
		reset();
	});

	const chosen = $derived(automatic ? days : null);
	const changed = $derived(!!config && chosen !== (config.trash_days ?? null));

	async function save() {
		saving = true;
		await saveConfig({ trash_days: chosen }, 'Trash settings');
		saving = false;
	}

	async function runNow() {
		await runJob({ path: { job: 'trash' } });
		notify({
			kind: 'info',
			title: 'Emptying the trash',
			text: `Deleting for good what has been in it longer than ${config?.trash_days} days.`
		});
	}
</script>

<SettingRow
	id="trash-auto"
	title="Empty the trash automatically"
	description="Papers, files and notes in the trash are deleted for good after some days, every night. Off: they stay until someone empties the trash."
>
	<Switch id="trash-auto" label="Empty the trash automatically" bind:checked={automatic} />
</SettingRow>
{#if automatic}
	<SettingRow
		id="trash-days"
		title="Days in the trash"
		description="How long things stay restorable before they are deleted for good."
	>
		<input id="trash-days" type="number" min="1" max="3650" bind:value={days} />
	</SettingRow>
{/if}
<SectionButtons {changed} {saving} onreset={reset} onsave={save} />
{#if config?.trash_days != null && !changed}
	<p class="muted small">
		Next run tonight at 02:30 (UTC).
		<button class="link" onclick={runNow}>Run now</button>
	</p>
{/if}

<style>
	.small {
		margin: 8px 0 0;
		font-size: var(--step--1);
	}
	.link {
		padding: 0 4px;
		border: none;
		background: none;
		color: var(--royal);
	}
</style>
