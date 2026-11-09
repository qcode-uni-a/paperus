<script lang="ts">
	import { mdiCommentTextOutline } from '@mdi/js';
	import Icon from '#lib/Icon.svelte';
	import AnnotationPopup from '#lib/annotations/AnnotationPopup.svelte';
	import type { AnnotationOut, FileAnnotations } from '#lib/annotations/annotations.svelte.ts';
	import {
		boxToRect,
		distanceToPath,
		lineBoxes,
		rectToBox,
		toPdf,
		toView,
		type Box,
		type Viewport
	} from '#lib/annotations/geometry.ts';

	/** One page's annotations, drawn over it, and the tools at work on it:
	 * marking text by dragging over it, a tap for a note or words, a drag
	 * for an area, the pen and the eraser. With a tool in hand one finger
	 * works the tool and two fingers scroll. */
	let {
		store,
		index,
		viewport,
		label
	}: {
		store: FileAnnotations;
		/** The page, from 0. */
		index: number;
		viewport: Viewport;
		label: string | null;
	} = $props();

	let root = $state<HTMLDivElement>();
	let capture = $state<HTMLDivElement>();

	const NOTE_SIZE = 22;
	const marks = $derived(store.onPage(index));
	const scale = $derived(viewport.scale);

	const boxes = (a: AnnotationOut): Box[] =>
		((a.position.rects ?? []) as number[][]).map((r) => rectToBox(viewport, r));
	const strokes = (a: AnnotationOut): [number, number][][] =>
		((a.position.paths ?? []) as number[][]).map((path) => {
			const points: [number, number][] = [];
			for (let i = 0; i + 1 < path.length; i += 2)
				points.push(toView(viewport, path[i], path[i + 1]));
			return points;
		});
	const d = (points: [number, number][]) =>
		points.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');

	/** Around all of an annotation's parts. */
	function outline(a: AnnotationOut): Box | null {
		const parts = [
			...boxes(a),
			...strokes(a).map((points) => {
				const xs = points.map((p) => p[0]);
				const ys = points.map((p) => p[1]);
				return {
					left: Math.min(...xs),
					top: Math.min(...ys),
					width: Math.max(...xs) - Math.min(...xs),
					height: Math.max(...ys) - Math.min(...ys)
				};
			})
		];
		if (!parts.length) return null;
		const left = Math.min(...parts.map((b) => b.left));
		const top = Math.min(...parts.map((b) => b.top));
		const right = Math.max(...parts.map((b) => b.left + b.width));
		const bottom = Math.max(...parts.map((b) => b.top + b.height));
		return { left, top, width: right - left, height: bottom - top };
	}

	const selected = $derived(marks.find((a) => a.id === store.selected));

	// Where the pointer is on the page.
	function at(event: { clientX: number; clientY: number }): [number, number] {
		const page = root!.getBoundingClientRect();
		return [event.clientX - page.left, event.clientY - page.top];
	}

	// Clicking a highlight (under the text layer) or a pen stroke opens it.
	function hit(x: number, y: number): AnnotationOut | undefined {
		for (const a of [...marks].reverse()) {
			if (a.kind === 'ink') {
				const width = Math.max(6, ((a.position.width as number) ?? 1) * scale);
				if (strokes(a).some((points) => distanceToPath(points, x, y) <= width)) return a;
			} else if (
				boxes(a).some(
					(b) =>
						x >= b.left - 2 &&
						x <= b.left + b.width + 2 &&
						y >= b.top - 2 &&
						y <= b.top + b.height + 2
				)
			) {
				return a;
			}
		}
	}

	$effect(() => {
		const page = root?.parentElement;
		if (!page) return;
		const click = (event: MouseEvent) => {
			if (store.tool !== 'select') return;
			const target = event.target as HTMLElement;
			if (target.closest('.popup, .mark-html')) return;
			if (!window.getSelection()?.isCollapsed) return;
			const found = hit(...at(event));
			if (found) store.selected = found.id;
			else if (store.current?.page_index === index) store.selected = null;
		};
		page.addEventListener('click', click);
		return () => page.removeEventListener('click', click);
	});

	// The tools: one pointer works, a second one turns it into scrolling.
	type Mode = 'mark' | 'draw' | 'erase' | 'area' | 'tap' | 'pan' | null;
	let mode: Mode = null;
	const pointers = new Map<number, { x: number; y: number }>();
	let start: [number, number] = [0, 0];
	let startCaret: { node: Node; offset: number } | null = null;
	let lastMiddle: [number, number] = [0, 0];
	let preview = $state<{ boxes?: Box[]; points?: [number, number][]; area?: Box } | null>(null);
	let text = '';
	let rects: Box[] = [];

	/** The text under a point, ignoring the tool's own overlay. */
	function caretAt(x: number, y: number): { node: Node; offset: number } | null {
		if (!capture) return null;
		capture.style.pointerEvents = 'none';
		try {
			const doc = document as Document & {
				caretPositionFromPoint?: (
					x: number,
					y: number
				) => {
					offsetNode: Node;
					offset: number;
				} | null;
				caretRangeFromPoint?: (x: number, y: number) => Range | null;
			};
			let found: { node: Node; offset: number } | null = null;
			if (doc.caretPositionFromPoint) {
				const p = doc.caretPositionFromPoint(x, y);
				if (p) found = { node: p.offsetNode, offset: p.offset };
			} else if (doc.caretRangeFromPoint) {
				const r = doc.caretRangeFromPoint(x, y);
				if (r) found = { node: r.startContainer, offset: r.startOffset };
			}
			const layer = root?.parentElement?.querySelector('.textLayer');
			return found && layer?.contains(found.node) ? found : null;
		} finally {
			capture.style.pointerEvents = '';
		}
	}

	function between(a: { node: Node; offset: number }, b: { node: Node; offset: number }): Range {
		const range = document.createRange();
		range.setStart(a.node, a.offset);
		if (range.comparePoint(b.node, b.offset) < 0) {
			range.setStart(b.node, b.offset);
			range.setEnd(a.node, a.offset);
		} else {
			range.setEnd(b.node, b.offset);
		}
		return range;
	}

	function middle(): [number, number] {
		const all = [...pointers.values()];
		return [
			all.reduce((s, p) => s + p.x, 0) / all.length,
			all.reduce((s, p) => s + p.y, 0) / all.length
		];
	}

	function down(event: PointerEvent) {
		if (event.button > 0) return;
		capture?.setPointerCapture(event.pointerId);
		pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
		if (pointers.size > 1) {
			mode = 'pan';
			preview = null;
			lastMiddle = middle();
			return;
		}
		start = at(event);
		const tool = store.tool;
		if (tool === 'highlight' || tool === 'underline' || tool === 'strikeout') {
			mode = 'mark';
			startCaret = caretAt(event.clientX, event.clientY);
			text = '';
			rects = [];
		} else if (tool === 'ink') {
			mode = 'draw';
			preview = { points: [start] };
		} else if (tool === 'eraser') {
			mode = 'erase';
			erase(...start);
		} else if (tool === 'image') {
			mode = 'area';
		} else {
			mode = 'tap';
		}
	}

	function move(event: PointerEvent) {
		if (!pointers.has(event.pointerId)) return;
		pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
		if (mode === 'pan') {
			const [mx, my] = middle();
			window.scrollBy(lastMiddle[0] - mx, lastMiddle[1] - my);
			lastMiddle = [mx, my];
			return;
		}
		const [x, y] = at(event);
		if (mode === 'mark' && startCaret) {
			const end = caretAt(event.clientX, event.clientY);
			if (!end) return;
			const range = between(startCaret, end);
			text = range.toString();
			rects = lineBoxes(range.getClientRects(), root!.getBoundingClientRect());
			preview = { boxes: rects };
		} else if (mode === 'draw' && preview?.points) {
			const [lx, ly] = preview.points[preview.points.length - 1];
			if (Math.hypot(x - lx, y - ly) >= 1.5) preview = { points: [...preview.points, [x, y]] };
		} else if (mode === 'erase') {
			erase(x, y);
		} else if (mode === 'area') {
			preview = {
				area: {
					left: Math.min(start[0], x),
					top: Math.min(start[1], y),
					width: Math.abs(x - start[0]),
					height: Math.abs(y - start[1])
				}
			};
		}
	}

	async function up(event: PointerEvent) {
		if (!pointers.delete(event.pointerId)) return;
		if (pointers.size > 0) return;
		const done = mode;
		const shown = preview;
		mode = null;
		preview = null;
		const base = { page_index: index, page_label: label, color: store.color };
		if (done === 'mark' && rects.length && text.trim()) {
			const kind = store.tool as 'highlight' | 'underline' | 'strikeout';
			await store.add({
				...base,
				kind,
				text: text.replace(/\s+/g, ' ').trim(),
				position: { rects: rects.map((b) => boxToRect(viewport, b)) }
			});
		} else if (done === 'draw' && shown?.points && shown.points.length > 1) {
			await store.add({
				...base,
				kind: 'ink',
				position: {
					paths: [shown.points.flatMap(([x, y]) => toPdf(viewport, x, y))],
					width: store.inkWidth
				}
			});
		} else if (done === 'area' && shown?.area && shown.area.width > 8 && shown.area.height > 8) {
			await store.add(
				{ ...base, kind: 'image', position: { rects: [boxToRect(viewport, shown.area)] } },
				true
			);
		} else if (done === 'tap') {
			const [x, y] = at(event);
			if (Math.hypot(x - start[0], y - start[1]) > 8) return;
			if (store.tool === 'note') {
				const size = NOTE_SIZE * scale;
				await store.add(
					{
						...base,
						kind: 'note',
						position: {
							rects: [boxToRect(viewport, { left: x, top: y, width: size, height: size })]
						}
					},
					true
				);
			} else if (store.tool === 'text') {
				const box = {
					left: x,
					top: y,
					width: 180 * scale,
					height: store.fontSize * 1.6 * scale
				};
				await store.add(
					{
						...base,
						kind: 'text',
						position: { rects: [boxToRect(viewport, box)], font_size: store.fontSize }
					},
					true
				);
			}
		}
	}

	function cancel(event: PointerEvent) {
		pointers.delete(event.pointerId);
		if (!pointers.size) {
			mode = null;
			preview = null;
		}
	}

	const erasing = new Set<string>();
	function erase(x: number, y: number) {
		for (const a of marks) {
			if (a.kind !== 'ink' || !a.mine || erasing.has(a.id)) continue;
			const width = Math.max(8, ((a.position.width as number) ?? 1) * scale);
			if (strokes(a).some((points) => distanceToPath(points, x, y) <= width)) {
				erasing.add(a.id);
				store.remove(a.id).finally(() => erasing.delete(a.id));
			}
		}
	}

	// Notes, words and areas of one's own move by dragging them.
	let dragging = $state<{ id: string; dx: number; dy: number } | null>(null);
	let dragStart: [number, number] = [0, 0];

	function grab(event: PointerEvent, a: AnnotationOut) {
		if (store.tool !== 'select' || event.button > 0) return;
		event.stopPropagation();
		store.selected = a.id;
		if (!a.mine) return;
		(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
		dragStart = at(event);
		dragging = { id: a.id, dx: 0, dy: 0 };
	}

	function drag(event: PointerEvent) {
		if (!dragging) return;
		const [x, y] = at(event);
		dragging = { ...dragging, dx: x - dragStart[0], dy: y - dragStart[1] };
	}

	async function drop(a: AnnotationOut) {
		if (!dragging || dragging.id !== a.id) return;
		const { dx, dy } = dragging;
		dragging = null;
		if (Math.hypot(dx, dy) < 3) return;
		const rects = boxes(a).map((b) =>
			boxToRect(viewport, { ...b, left: b.left + dx, top: b.top + dy })
		);
		await store.change(a.id, { position: { ...a.position, rects } });
	}

	const shift = (a: AnnotationOut) =>
		dragging?.id === a.id ? `translate(${dragging.dx}px, ${dragging.dy}px)` : undefined;
</script>

<div class="layer" bind:this={root}>
	<svg class="marks" width={viewport.width} height={viewport.height} aria-hidden="true">
		{#each marks as a (a.id)}
			{#if a.kind === 'highlight'}
				{#each boxes(a) as b, i (i)}
					<rect
						class="highlight"
						x={b.left}
						y={b.top}
						width={b.width}
						height={b.height}
						fill={a.color}
					/>
				{/each}
			{:else if a.kind === 'underline' || a.kind === 'strikeout'}
				{#each boxes(a) as b, i (i)}
					{@const y = a.kind === 'underline' ? b.top + b.height - 1 : b.top + b.height / 2}
					<line
						x1={b.left}
						x2={b.left + b.width}
						y1={y}
						y2={y}
						stroke={a.color}
						stroke-width={Math.max(1.2, scale)}
					/>
				{/each}
			{:else if a.kind === 'ink'}
				{#each strokes(a) as points, i (i)}
					<path
						d={d(points)}
						stroke={a.color}
						stroke-width={((a.position.width as number) ?? 1) * scale}
						fill="none"
						stroke-linecap="round"
						stroke-linejoin="round"
					/>
				{/each}
			{/if}
		{/each}
		{#if preview?.boxes}
			{#each preview.boxes as b, i (i)}
				<rect
					class="highlight"
					x={b.left}
					y={b.top}
					width={b.width}
					height={b.height}
					fill={store.color}
				/>
			{/each}
		{/if}
		{#if preview?.points}
			<path
				d={d(preview.points)}
				stroke={store.color}
				stroke-width={store.inkWidth * scale}
				fill="none"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>
		{/if}
		{#if preview?.area}
			<rect
				x={preview.area.left}
				y={preview.area.top}
				width={preview.area.width}
				height={preview.area.height}
				fill="none"
				stroke={store.color}
				stroke-width="2"
				stroke-dasharray="6 4"
			/>
		{/if}
		{#if selected}
			{@const box = outline(selected)}
			{#if box}
				<rect
					class="selected"
					x={box.left - 3}
					y={box.top - 3}
					width={box.width + 6}
					height={box.height + 6}
				/>
			{/if}
		{/if}
	</svg>

	{#each marks as a (a.id)}
		{#if a.kind === 'note' || a.kind === 'text' || a.kind === 'image'}
			{@const [b] = boxes(a)}
			{#if b}
				<button
					type="button"
					id="annotation-{a.id}"
					class="mark-html {a.kind}"
					class:mine={a.mine}
					class:tools={store.tool !== 'select'}
					style:left="{b.left}px"
					style:top="{b.top}px"
					style:width="{b.width}px"
					style:height="{b.height}px"
					style:transform={shift(a)}
					style:--mark={a.color}
					style:font-size={a.kind === 'text'
						? `${((a.position.font_size as number) ?? 12) * scale}px`
						: undefined}
					aria-label="{a.kind === 'note' ? 'Note' : a.kind === 'text' ? 'Text' : 'Area'}{a.comment
						? `: ${a.comment}`
						: ''}"
					onpointerdown={(event) => grab(event, a)}
					onpointermove={drag}
					onpointerup={() => drop(a)}
					onclick={(event) => {
						event.stopPropagation();
						store.selected = a.id;
					}}
				>
					{#if a.kind === 'note'}<Icon
							path={mdiCommentTextOutline}
							size={Math.max(14, 16 * scale)}
						/>
					{:else if a.kind === 'text'}{a.text ?? ''}{/if}
				</button>
			{/if}
		{:else}
			<!-- An anchor to scroll to from the list. -->
			{@const box = outline(a)}
			{#if box}
				<span
					class="anchor"
					id="annotation-{a.id}"
					style:left="{box.left}px"
					style:top="{box.top}px"
					style:width="{box.width}px"
					style:height="{box.height}px"
				></span>
			{/if}
		{/if}
	{/each}

	{#if store.tool !== 'select'}
		<div
			class="capture tool-{store.tool}"
			bind:this={capture}
			role="application"
			aria-label="Annotate page {label ?? index + 1}"
			onpointerdown={down}
			onpointermove={move}
			onpointerup={up}
			onpointercancel={cancel}
		></div>
	{/if}

	{#if selected}
		{@const box = outline(selected)}
		{#if box}<AnnotationPopup {store} annotation={selected} {box} pageWidth={viewport.width} />{/if}
	{/if}
</div>

<style>
	.layer {
		position: absolute;
		inset: 0;
		pointer-events: none;
	}
	.marks {
		position: absolute;
		inset: 0;
		z-index: 1;
		overflow: visible;
	}
	.highlight {
		fill-opacity: 0.4;
		mix-blend-mode: multiply;
	}
	.selected {
		fill: none;
		stroke: var(--royal);
		stroke-width: 1.5;
		stroke-dasharray: 4 3;
		rx: 3;
	}
	.mark-html {
		position: absolute;
		z-index: 3;
		padding: 0;
		border: none;
		border-radius: 0;
		background: none;
		font-weight: normal;
		pointer-events: auto;
		cursor: pointer;
	}
	.mark-html.mine {
		cursor: grab;
	}
	.mark-html.tools {
		pointer-events: none;
	}
	.note {
		display: grid;
		place-items: center;
		border-radius: 4px;
		background: var(--mark);
		color: rgb(0 0 0 / 0.7);
		box-shadow: 0 1px 3px rgb(0 0 0 / 0.3);
	}
	.text {
		width: auto !important;
		height: auto !important;
		min-width: 2em;
		min-height: 1.4em;
		padding: 0 2px;
		color: var(--mark);
		font-family: Helvetica, Arial, sans-serif;
		line-height: 1.3;
		text-align: left;
		white-space: pre-wrap;
		outline: 1px dashed transparent;
	}
	.text:hover {
		outline-color: var(--mark);
	}
	/* Dark colours read on paper: yellow words would not. */
	.text[style*='#ffd400'],
	.text[style*='#aaaaaa'] {
		color: #6b5a00;
	}
	.image {
		border: 2px solid var(--mark);
		border-radius: 2px;
	}
	.anchor {
		position: absolute;
		pointer-events: none;
	}
	.capture {
		position: absolute;
		inset: 0;
		z-index: 4;
		touch-action: none;
		pointer-events: auto;
		cursor: crosshair;
	}
	.capture.tool-highlight,
	.capture.tool-underline,
	.capture.tool-strikeout,
	.capture.tool-text {
		cursor: text;
	}
	.capture.tool-note {
		cursor: copy;
	}
	.capture.tool-eraser {
		cursor: cell;
	}
</style>
