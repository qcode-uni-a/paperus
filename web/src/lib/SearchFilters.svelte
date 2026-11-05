<script lang="ts">
	import { TYPE_NAMES } from '#lib/format.ts';

	export interface Filters {
		words: boolean;
		meaning: boolean;
		types: string[];
	}

	let { filters, onchange }: { filters: Filters; onchange: (next: Filters) => void } = $props();

	let open = $state(false);
	let root = $state<HTMLElement>();

	const changed = $derived(!filters.words || !filters.meaning || filters.types.length > 0);

	/** At least one way of searching stays on. */
	function toggleMethod(method: 'words' | 'meaning') {
		const next = { ...filters, [method]: !filters[method] };
		if (!next.words && !next.meaning) return;
		onchange(next);
	}

	function toggleType(type: string) {
		const types = filters.types.includes(type)
			? filters.types.filter((t) => t !== type)
			: [...filters.types, type];
		onchange({ ...filters, types });
	}

	function reset() {
		onchange({ words: true, meaning: true, types: [] });
	}
</script>

<svelte:window
	onpointerdown={(event) => {
		if (open && root && !root.contains(event.target as Node)) open = false;
	}}
	onkeydown={(event) => {
		if (open && event.key === 'Escape') {
			event.stopPropagation();
			open = false;
		}
	}}
/>

<div class="filters" bind:this={root}>
	<button
		class="icon"
		class:changed
		onclick={() => (open = !open)}
		aria-expanded={open}
		aria-controls="search-filters"
		aria-label={changed ? 'Search options (changed)' : 'Search options'}
		title="Search options"
	>
		<svg viewBox="0 0 24 24" aria-hidden="true">
			<path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
			<circle cx="16" cy="7" r="2" />
			<circle cx="10" cy="17" r="2" />
		</svg>
	</button>

	{#if open}
		<div class="panel" id="search-filters" role="group" aria-label="Search options">
			<fieldset>
				<legend>Search by</legend>
				<div class="chips">
					<button
						class="chip"
						aria-pressed={filters.words}
						onclick={() => toggleMethod('words')}
						disabled={filters.words && !filters.meaning}
					>
						Words
						<span>exact terms, names, acronyms</span>
					</button>
					<button
						class="chip"
						aria-pressed={filters.meaning}
						onclick={() => toggleMethod('meaning')}
						disabled={filters.meaning && !filters.words}
					>
						Meaning
						<span>similar ideas in other words</span>
					</button>
				</div>
			</fieldset>

			<fieldset>
				<legend>Type</legend>
				<div class="chips">
					{#each Object.entries(TYPE_NAMES) as [type, name] (type)}
						<button
							class="chip small"
							aria-pressed={filters.types.includes(type)}
							onclick={() => toggleType(type)}>{name}</button
						>
					{/each}
				</div>
				<p class="hint">{filters.types.length ? 'Only the chosen types.' : 'All types.'}</p>
			</fieldset>

			<div class="foot">
				<button class="link" onclick={reset} disabled={!changed}>Reset</button>
				<button class="primary" onclick={() => (open = false)}>Done</button>
			</div>
		</div>
	{/if}
</div>

<style>
	.filters {
		display: contents;
	}
	.icon {
		position: relative;
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		padding: 0;
		border-color: transparent;
		border-radius: 50%;
		background: none;
	}
	.icon:hover:not(:disabled),
	.icon[aria-expanded='true'] {
		background: var(--rail);
		border-color: transparent;
	}
	.icon svg {
		width: 20px;
		height: 20px;
		fill: none;
		stroke: var(--muted);
		stroke-width: 2;
		stroke-linecap: round;
	}
	.icon circle {
		fill: var(--surface);
	}
	.icon.changed::after {
		content: '';
		position: absolute;
		top: 5px;
		right: 5px;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--royal);
		border: 2px solid var(--surface);
	}
	.panel {
		position: absolute;
		z-index: 20;
		top: calc(100% + 8px);
		right: 0;
		width: min(440px, 100%);
		display: grid;
		gap: 16px;
		padding: 16px 18px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		box-shadow: var(--shadow);
	}
	fieldset {
		margin: 0;
		padding: 0;
		border: none;
		display: grid;
		gap: 8px;
	}
	legend {
		font-family: var(--serif);
		font-weight: 600;
		margin-bottom: 8px;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.chip {
		display: grid;
		gap: 1px;
		text-align: left;
		padding: 8px 12px;
		border-radius: 8px;
		font-weight: 600;
	}
	.chip span {
		font-weight: 400;
		font-size: var(--step--1);
		color: var(--muted);
	}
	.chip.small {
		padding: 4px 10px;
		font-weight: 400;
		border-radius: 999px;
	}
	.chip[aria-pressed='true'] {
		border-color: var(--royal);
		background: color-mix(in srgb, var(--royal) 10%, var(--surface));
		color: var(--ink);
		box-shadow: inset 0 0 0 1px var(--royal);
	}
	.chip:disabled {
		opacity: 1;
		cursor: default;
	}
	.hint {
		margin: 0;
		font-size: var(--step--1);
		color: var(--muted);
	}
	.foot {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	.link {
		border-color: transparent;
		background: none;
		color: var(--royal);
		padding: 4px 8px;
	}
	.link:hover:not(:disabled) {
		background: var(--rail);
		border-color: transparent;
	}
</style>
