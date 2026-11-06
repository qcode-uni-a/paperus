<script lang="ts">
	import type { Rules } from '#lib/api/generated/types.gen.ts';
	import { TYPE_NAMES } from '#lib/format.ts';
	import { libraryById, libraryName, organize } from '#lib/organize.svelte.ts';

	/** The rules of a smart collection owned by ``library``: papers that
	 * match all rules given. */
	let { rules = $bindable(), library }: { rules: Rules; library: string } = $props();

	const group = $derived(libraryById(library)?.kind === 'group');
	// A group's smart collection holds only the group's papers, so only its
	// tags matter; one's own may use any tag one can see.
	const tags = $derived(
		organize.tags
			.filter((t) => !group || t.library_id === library)
			.toSorted((a, b) => a.name.localeCompare(b.name))
	);
	const types = Object.entries(TYPE_NAMES).filter(([type]) => type !== 'note');

	type TagRule = 'tags_all' | 'tags_any' | 'tags_none';
	const TAG_RULES: [TagRule, string][] = [
		['tags_all', 'With all of these tags'],
		['tags_any', 'With any of these tags'],
		['tags_none', 'Without these tags']
	];

	function tagLabel(id: string): string {
		const tag = organize.tags.find((t) => t.id === id);
		if (!tag) return '?';
		// Tags of the same name in several libraries: say whose.
		const twins = organize.tags.filter((t) => t.name === tag.name).length > 1;
		return twins ? `${tag.name} (${libraryName(tag.library_id)})` : tag.name;
	}

	function addTag(rule: TagRule, id: string) {
		if (id && !(rules[rule] ?? []).includes(id)) rules[rule] = [...(rules[rule] ?? []), id];
	}
	function removeTag(rule: TagRule, id: string) {
		rules[rule] = (rules[rule] ?? []).filter((t) => t !== id);
	}
	function toggle(list: 'types' | 'owners', value: string) {
		const current = rules[list] ?? [];
		rules[list] = current.includes(value)
			? current.filter((v) => v !== value)
			: [...current, value];
	}
	/** Empty fields: no rule. */
	function number(value: string): number | null {
		const parsed = Number.parseInt(value, 10);
		return Number.isFinite(parsed) ? parsed : null;
	}
</script>

<fieldset class="rules">
	<legend>Papers that match all of these (leave out what does not matter)</legend>
	{#each TAG_RULES as [rule, label] (rule)}
		<div class="row">
			<span class="name">{label}</span>
			<div class="chips">
				{#each rules[rule] ?? [] as id (id)}
					<span class="chip"
						>{tagLabel(id)}<button
							type="button"
							aria-label="Remove {tagLabel(id)}"
							onclick={() => removeTag(rule, id)}>×</button
						></span
					>
				{/each}
				<select
					aria-label="{label}: add a tag"
					value=""
					onchange={(event) => {
						addTag(rule, event.currentTarget.value);
						event.currentTarget.value = '';
					}}
				>
					<option value="">Add a tag…</option>
					{#each tags.filter((t) => !(rules[rule] ?? []).includes(t.id)) as tag (tag.id)}
						<option value={tag.id}>{tagLabel(tag.id)}</option>
					{/each}
				</select>
			</div>
		</div>
	{/each}

	<div class="row">
		<span class="name">Of these types</span>
		<div class="chips">
			{#each types as [type, name] (type)}
				<label class="check"
					><input
						type="checkbox"
						checked={(rules.types ?? []).includes(type)}
						onchange={() => toggle('types', type)}
					/>{name}</label
				>
			{/each}
		</div>
	</div>

	<div class="row">
		<span class="name">Published</span>
		<div class="years">
			<label
				>from <input
					type="number"
					inputmode="numeric"
					min="0"
					max="9999"
					placeholder="any"
					value={rules.year_from ?? ''}
					oninput={(event) => (rules.year_from = number(event.currentTarget.value))}
				/></label
			>
			<label
				>to <input
					type="number"
					inputmode="numeric"
					min="0"
					max="9999"
					placeholder="any"
					value={rules.year_to ?? ''}
					oninput={(event) => (rules.year_to = number(event.currentTarget.value))}
				/></label
			>
		</div>
	</div>

	{#if !group && organize.libraries.length > 1}
		<div class="row">
			<span class="name">Owned by</span>
			<div class="chips">
				{#each organize.libraries as owner (owner.id)}
					<label class="check"
						><input
							type="checkbox"
							checked={(rules.owners ?? []).includes(owner.id)}
							onchange={() => toggle('owners', owner.id)}
						/>{libraryName(owner.id)}</label
					>
				{/each}
			</div>
		</div>
	{/if}

	<div class="row">
		<span class="name">Added</span>
		<label class="days"
			>in the last <input
				type="number"
				inputmode="numeric"
				min="1"
				max="36500"
				placeholder="any"
				value={rules.added_days ?? ''}
				oninput={(event) => (rules.added_days = number(event.currentTarget.value))}
			/> days</label
		>
	</div>
</fieldset>

<style>
	.rules {
		display: grid;
		gap: 12px;
		margin: 0;
		padding: 12px 14px;
		border: 1px solid var(--rule);
		border-radius: 8px;
	}
	legend {
		padding: 0 4px;
		font-size: var(--step--1);
		color: var(--muted);
	}
	.row {
		display: grid;
		gap: 6px;
	}
	.name {
		font-weight: 600;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px 10px;
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		padding: 2px 4px 2px 10px;
		border-radius: 999px;
		background: var(--tag-blue-bg);
		color: var(--tag-blue-ink);
		font-size: var(--step--1);
	}
	.chip button {
		width: 22px;
		height: 22px;
		padding: 0;
		border: none;
		border-radius: 50%;
		background: none;
		color: inherit;
		line-height: 1;
	}
	.chip button:hover {
		background: rgb(0 0 0 / 0.08);
	}
	.chips select {
		width: auto;
		min-width: 9rem;
	}
	.check {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-weight: 400;
	}
	.check input {
		width: auto;
		margin: 0;
	}
	.years,
	.days {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		font-weight: 400;
	}
	.years label {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	input[type='number'] {
		width: 6.5rem;
	}
</style>
