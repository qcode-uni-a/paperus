<script lang="ts">
	/** A date field in the installation's date format ("DD.MM.YYYY"), with a
	 * calendar button; ``value`` is "YYYY-MM-DD" or null. With the browser's
	 * format it is the browser's own date field. ``id`` is the field's, for
	 * a <label for> beside it (a label around it would take in the
	 * calendar button's name). */
	import { mdiCalendarMonthOutline } from '@mdi/js';
	import { untrack } from 'svelte';
	import Icon from '#lib/Icon.svelte';
	import { dateFormat, datePattern, formatDate, parseDate } from '#lib/dates.svelte.ts';

	let {
		value = $bindable(),
		min,
		max,
		id
	}: {
		value: string | null | undefined;
		min?: string | null;
		max?: string | null;
		id: string;
	} = $props();

	const native = $derived(dateFormat() === 'browser');
	let text = $state('');
	let problem = $state('');
	let picker = $state<HTMLInputElement>();

	// A value set from outside (or another date format): show it.
	$effect.pre(() => {
		const shown = value ? formatDate(value) : '';
		if (untrack(() => parseDate(text)) !== (value ?? null)) {
			text = shown;
			problem = '';
		}
	});

	/** Why a date written cannot be taken, or '' if it can. */
	function check(date: string | null): string {
		if (!date) return `Not a date; write it as ${datePattern()}`;
		if (min && date < min) return `Not before ${formatDate(min)}`;
		if (max && date > max) return `Not after ${formatDate(max)}`;
		return '';
	}

	function oninput(event: Event & { currentTarget: HTMLInputElement }) {
		text = event.currentTarget.value;
		problem = '';
		if (!text.trim()) {
			value = null;
			return;
		}
		const date = parseDate(text);
		if (date && !check(date)) value = date;
	}

	function onblur() {
		if (!text.trim()) return;
		const date = parseDate(text);
		problem = check(date);
		if (!problem && date) text = formatDate(date);
	}

	function choose() {
		if (!picker) return;
		try {
			picker.showPicker();
		} catch {
			// Browsers without showPicker (or refusing it): type the date.
			document.getElementById(id)?.focus();
		}
	}
</script>

{#if native}
	<input
		{id}
		type="date"
		class="native"
		min={min ?? undefined}
		max={max ?? undefined}
		value={value ?? ''}
		oninput={(event) => (value = event.currentTarget.value || null)}
	/>
{:else}
	<span class="date-input">
		<input
			{id}
			type="text"
			autocomplete="off"
			placeholder={datePattern()}
			size={10}
			value={text}
			{oninput}
			{onblur}
			aria-invalid={problem ? 'true' : undefined}
			aria-describedby={problem ? `${id}-problem` : undefined}
		/><button type="button" class="calendar" aria-label="Choose from a calendar" onclick={choose}
			><Icon path={mdiCalendarMonthOutline} size={18} /></button
		><input
			bind:this={picker}
			type="date"
			class="picker"
			tabindex="-1"
			aria-hidden="true"
			min={min ?? undefined}
			max={max ?? undefined}
			value={value ?? ''}
			onchange={(event) => {
				value = event.currentTarget.value || null;
				text = value ? formatDate(value) : '';
				problem = '';
			}}
		/>
		{#if problem}<small class="problem" id="{id}-problem">{problem}</small>{/if}
	</span>
{/if}

<style>
	.date-input {
		position: relative;
		display: inline-flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px;
	}
	.date-input input[type='text'] {
		width: 8.5rem;
		font-variant-numeric: tabular-nums;
	}
	.calendar {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		padding: 0;
		border-color: transparent;
		background: none;
		color: var(--muted);
	}
	.calendar:hover,
	.calendar:focus-visible {
		background: var(--rail);
		color: var(--ink);
	}
	/* Out of sight, but rendered, so its calendar opens by the button. */
	.picker {
		position: absolute;
		left: 0;
		bottom: 0;
		width: 1px;
		height: 1px;
		padding: 0;
		border: 0;
		opacity: 0;
		pointer-events: none;
	}
	.problem {
		flex-basis: 100%;
		color: var(--danger);
		font-size: var(--step--1);
	}
	input[aria-invalid='true'] {
		border-color: var(--danger);
	}
</style>
