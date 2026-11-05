<script lang="ts">
	import { changeTag, createTag, errorMessage } from '#lib/api/client.ts';
	import type { TagColor, TagOut } from '#lib/api/generated/types.gen.ts';
	import { TAG_COLORS } from '#lib/tags.ts';
	import { defaultLibrary, libraryName, writableLibraries } from '#lib/organize.svelte.ts';

	/** Create a tag, or edit one: name, colour and description. */
	let { onsaved }: { onsaved?: () => void } = $props();

	let dialog = $state<HTMLDialogElement>();
	let tag = $state<TagOut | null>(null);
	let name = $state('');
	let color = $state<TagColor | null>(null);
	let description = $state('');
	let library = $state('');
	let error = $state('');
	let saving = $state(false);

	export function open(editing: TagOut | null = null) {
		tag = editing;
		name = editing?.name ?? '';
		color = editing?.color ?? null;
		description = editing?.description ?? '';
		library = defaultLibrary()?.id ?? '';
		error = '';
		dialog?.showModal();
	}

	async function save(event: SubmitEvent) {
		event.preventDefault();
		saving = true;
		const body = { name, color, description: description.trim() || null };
		const result = tag
			? await changeTag({ path: { tag_id: tag.id }, body })
			: await createTag({ body: { ...body, library_id: library || undefined } });
		saving = false;
		if (!result.data) {
			error = errorMessage(result.error);
			return;
		}
		dialog?.close();
		onsaved?.();
	}
</script>

<dialog bind:this={dialog} aria-labelledby="tag-dialog-title">
	<form onsubmit={save}>
		<h2 id="tag-dialog-title">{tag ? 'Edit tag' : 'New tag'}</h2>
		<label>Name <input bind:value={name} required maxlength="100" /></label>
		{#if !tag && writableLibraries().length > 1}
			<label
				>Owner
				<select bind:value={library}>
					{#each writableLibraries() as option (option.id)}
						<option value={option.id}>{libraryName(option.id)}</option>
					{/each}
				</select>
			</label>
		{/if}
		<fieldset>
			<legend>Colour</legend>
			<div class="swatches">
				<label class="swatch" title="No colour">
					<input type="radio" name="color" value={null} bind:group={color} />
					<span class="dot none" aria-hidden="true"></span>
					<span class="visually-hidden">No colour</span>
				</label>
				{#each TAG_COLORS as option (option.value)}
					<label class="swatch" title={option.label} data-tag-color={option.value}>
						<input type="radio" name="color" value={option.value} bind:group={color} />
						<span class="dot" aria-hidden="true"></span>
						<span class="visually-hidden">{option.label}</span>
					</label>
				{/each}
			</div>
		</fieldset>
		<div class="preview" aria-hidden="true">
			<span class="chip" data-tag-color={color}>{name.trim() || 'Tag'}</span>
		</div>
		<label>
			Description <span class="optional">(optional)</span>
			<textarea bind:value={description} rows="3" maxlength="2000"></textarea>
		</label>
		{#if error}<p class="error">{error}</p>{/if}
		<div class="buttons">
			<button type="button" onclick={() => dialog?.close()}>Cancel</button>
			<button class="primary" disabled={saving}>{tag ? 'Save' : 'Create tag'}</button>
		</div>
	</form>
</dialog>

<style>
	dialog {
		width: min(460px, calc(100vw - 32px));
		padding: 22px 24px 24px;
		border: 1px solid var(--rule);
		border-radius: 12px;
		background: var(--surface);
		color: var(--ink);
		box-shadow: var(--shadow);
	}
	dialog::backdrop {
		background: rgb(10 14 30 / 0.4);
	}
	form {
		display: grid;
		gap: 14px;
	}
	h2 {
		margin: 0;
		font-size: var(--step-2);
	}
	form > label {
		display: grid;
		gap: 6px;
		font-weight: 600;
	}
	form > label :global(input),
	form > label :global(select),
	form > label :global(textarea) {
		font-weight: 400;
	}
	.optional {
		font-weight: 400;
		color: var(--muted);
	}
	textarea {
		resize: vertical;
	}
	fieldset {
		margin: 0;
		padding: 0;
		border: none;
	}
	legend {
		padding: 0;
		margin-bottom: 8px;
		font-weight: 600;
	}
	.swatches {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.swatch {
		position: relative;
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		border-radius: 50%;
		cursor: pointer;
	}
	.swatch input {
		position: absolute;
		inset: 0;
		margin: 0;
		opacity: 0;
		cursor: pointer;
	}
	.dot {
		width: 24px;
		height: 24px;
		border-radius: 50%;
		background: var(--tag-bg);
		box-shadow:
			inset 0 0 0 4px var(--tag-bg),
			inset 0 0 0 24px var(--tag-ink);
	}
	.dot.none {
		background: none;
		box-shadow: none;
		border: 2px dashed var(--rule);
	}
	.swatch:has(input:checked) {
		box-shadow: 0 0 0 2px var(--ink);
	}
	.swatch:has(input:focus-visible) {
		outline: 2px solid var(--focus);
		outline-offset: 2px;
	}
	.preview {
		display: flex;
	}
	.chip {
		padding: 2px 10px;
		border-radius: 999px;
		background: var(--tag-bg, var(--rail));
		color: var(--tag-ink, var(--ink));
		font-size: 0.92em;
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
	.error {
		margin: 0;
	}
</style>
