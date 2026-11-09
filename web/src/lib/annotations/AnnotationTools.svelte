<script lang="ts">
	import {
		mdiCheck,
		mdiCommentPlusOutline,
		mdiCursorDefaultOutline,
		mdiDraw,
		mdiEraser,
		mdiFormatStrikethroughVariant,
		mdiFormatText,
		mdiFormatUnderline,
		mdiMarker,
		mdiPen,
		mdiSelectionDrag
	} from '@mdi/js';
	import Icon from '#lib/Icon.svelte';
	import {
		COLORS,
		INK_WIDTHS,
		type FileAnnotations,
		type Tool
	} from '#lib/annotations/annotations.svelte.ts';

	/** The tools for annotating: a row in the viewer's toolbar on a large
	 * screen; on a phone a round button at the bottom that opens them. */
	let { store }: { store: FileAnnotations } = $props();

	const TOOLS: { tool: Tool; label: string; short: string; icon: string }[] = [
		{ tool: 'select', label: 'Select text', short: 'Read', icon: mdiCursorDefaultOutline },
		{ tool: 'highlight', label: 'Highlight', short: 'Highlight', icon: mdiMarker },
		{ tool: 'underline', label: 'Underline', short: 'Underline', icon: mdiFormatUnderline },
		{
			tool: 'strikeout',
			label: 'Strike through',
			short: 'Strike',
			icon: mdiFormatStrikethroughVariant
		},
		{ tool: 'note', label: 'Note', short: 'Note', icon: mdiCommentPlusOutline },
		{ tool: 'text', label: 'Text', short: 'Text', icon: mdiFormatText },
		{ tool: 'image', label: 'Area (figure, equation)', short: 'Area', icon: mdiSelectionDrag },
		{ tool: 'ink', label: 'Pen', short: 'Pen', icon: mdiDraw },
		{ tool: 'eraser', label: 'Eraser (pen strokes)', short: 'Eraser', icon: mdiEraser }
	];

	let colorsOpen = $state(false);
	let fabOpen = $state(false);

	const icon = $derived(TOOLS.find((t) => t.tool === store.tool)?.icon ?? mdiPen);

	function choose(tool: Tool) {
		store.tool = store.tool === tool && tool !== 'select' ? 'select' : tool;
		store.selected = null;
		window.getSelection()?.removeAllRanges();
		fabOpen = false;
	}

	function pick(color: string) {
		store.color = color;
		store.remember();
		colorsOpen = false;
	}

	$effect(() => {
		const key = (event: KeyboardEvent) => {
			if (event.key === 'Escape' && store.tool !== 'select' && !store.selected) {
				store.tool = 'select';
			}
		};
		window.addEventListener('keydown', key);
		return () => window.removeEventListener('keydown', key);
	});
</script>

{#snippet colors()}
	<div class="swatches" role="radiogroup" aria-label="Colour">
		{#each COLORS as color (color.value)}
			<button
				class="swatch"
				class:chosen={store.color === color.value}
				style:background={color.value}
				role="radio"
				aria-checked={store.color === color.value}
				aria-label={color.name}
				title={color.name}
				onclick={() => pick(color.value)}
			></button>
		{/each}
	</div>
	{#if store.tool === 'ink'}
		<div class="widths" role="radiogroup" aria-label="Pen width">
			{#each INK_WIDTHS as width (width)}
				<button
					class="width"
					class:chosen={store.inkWidth === width}
					role="radio"
					aria-checked={store.inkWidth === width}
					aria-label="{width} pt"
					title="{width} pt"
					onclick={() => {
						store.inkWidth = width;
						store.remember();
					}}><span style:height="{width * 1.5}px" style:background={store.color}></span></button
				>
			{/each}
		</div>
	{/if}
{/snippet}

<div class="bar" role="toolbar" aria-label="Annotate">
	{#each TOOLS as { tool, label, icon: path } (tool)}
		<button
			class="tool"
			class:active={store.tool === tool}
			aria-pressed={store.tool === tool}
			aria-label={label}
			title={label}
			onclick={() => choose(tool)}><Icon {path} size={18} /></button
		>
	{/each}
	<div class="color">
		<button
			class="current"
			style:background={store.color}
			aria-label="Colour"
			aria-expanded={colorsOpen}
			title="Colour"
			onclick={() => (colorsOpen = !colorsOpen)}
		></button>
		{#if colorsOpen}<div class="drop">{@render colors()}</div>{/if}
	</div>
</div>

<div class="fab-area">
	{#if fabOpen}
		<div class="fab-menu" role="toolbar" aria-label="Annotate">
			<div class="fab-tools">
				{#each TOOLS as { tool, label, short, icon: path } (tool)}
					<button
						class="fab-tool"
						class:active={store.tool === tool}
						aria-pressed={store.tool === tool}
						aria-label={label}
						onclick={() => choose(tool)}><Icon {path} size={22} /><span>{short}</span></button
					>
				{/each}
			</div>
			{@render colors()}
		</div>
	{/if}
	<button
		class="fab"
		class:working={store.tool !== 'select'}
		style:--mark={store.color}
		aria-label={fabOpen ? 'Close the tools' : 'Annotate'}
		aria-expanded={fabOpen}
		onclick={() => (fabOpen = !fabOpen)}><Icon path={fabOpen ? mdiCheck : icon} size={26} /></button
	>
</div>

<style>
	.bar {
		display: flex;
		align-items: center;
		gap: 2px;
	}
	.tool {
		display: grid;
		place-items: center;
		width: 32px;
		height: 32px;
		padding: 0 !important;
		border: none;
		border-radius: 8px;
		background: none;
		color: var(--muted);
	}
	.tool:hover {
		background: var(--rail);
		color: var(--ink);
	}
	.tool.active {
		background: color-mix(in srgb, var(--royal) 14%, transparent);
		color: var(--royal);
	}
	.color {
		position: relative;
		margin-left: 4px;
	}
	.current {
		width: 22px;
		height: 22px;
		padding: 0 !important;
		border: 2px solid var(--surface);
		border-radius: 50%;
		box-shadow: 0 0 0 1px var(--rule);
	}
	.drop {
		position: absolute;
		top: calc(100% + 8px);
		right: 0;
		z-index: 6;
		display: grid;
		gap: 8px;
		padding: 10px;
		border: 1px solid var(--rule);
		border-radius: 10px;
		background: var(--surface);
		box-shadow: var(--shadow);
	}
	.swatches {
		display: grid;
		grid-template-columns: repeat(4, 28px);
		gap: 6px;
	}
	.swatch {
		width: 28px;
		height: 28px;
		padding: 0 !important;
		border: 2px solid transparent;
		border-radius: 50%;
		box-shadow: inset 0 0 0 1px rgb(0 0 0 / 0.15);
	}
	.swatch.chosen {
		border-color: var(--ink);
	}
	.widths {
		display: flex;
		gap: 6px;
	}
	.width {
		display: grid;
		place-items: center;
		width: 36px;
		height: 28px;
		padding: 0 !important;
		border-radius: 8px;
	}
	.width span {
		width: 22px;
		border-radius: 2px;
	}
	.width.chosen {
		border-color: var(--ink);
	}
	.fab-area {
		display: none;
	}
	/* On a phone: a round button at the bottom, the tools above it. */
	@media (max-width: 720px) {
		.bar {
			display: none;
		}
		.fab-area {
			position: fixed;
			right: 16px;
			bottom: calc(16px + env(safe-area-inset-bottom, 0px));
			z-index: 20;
			display: grid;
			justify-items: end;
			gap: 10px;
		}
		.fab {
			display: grid;
			place-items: center;
			width: 56px;
			height: 56px;
			padding: 0;
			border: none;
			border-radius: 50%;
			background: var(--royal);
			color: white;
			box-shadow: 0 4px 14px rgb(0 0 0 / 0.3);
		}
		.fab.working {
			box-shadow:
				0 0 0 4px var(--mark),
				0 4px 14px rgb(0 0 0 / 0.3);
		}
		.fab-menu {
			display: grid;
			gap: 10px;
			max-height: calc(100vh - 180px);
			overflow-y: auto;
			padding: 10px;
			border: 1px solid var(--rule);
			border-radius: 14px;
			background: var(--surface);
			box-shadow: var(--shadow);
		}
		.fab-tools {
			display: grid;
			grid-template-columns: repeat(3, 72px);
			gap: 4px;
		}
		.fab-tool {
			display: grid;
			justify-items: center;
			gap: 2px;
			padding: 8px 4px;
			border: none;
			border-radius: 10px;
			background: none;
			font-size: 12px;
			font-weight: 500;
		}
		.fab-tool.active {
			background: color-mix(in srgb, var(--royal) 14%, transparent);
			color: var(--royal);
		}
	}
</style>
