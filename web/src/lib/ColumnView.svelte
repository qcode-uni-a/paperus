<script lang="ts">
	import { addLinks, type Place } from '#lib/pdfLinks.ts';
	import {
		AnnotationMode,
		TextLayer,
		type PDFDocumentProxy,
		type PDFPageProxy,
		type RenderTask
	} from 'pdfjs-dist';
	import { untrack } from 'svelte';
	import AnnotationLayer from '#lib/annotations/AnnotationLayer.svelte';
	import type { FileAnnotations } from '#lib/annotations/annotations.svelte.ts';
	import type { Box, Viewport } from '#lib/annotations/geometry.ts';
	import type { PageLayouts, Piece } from '#lib/pageLayouts.svelte.ts';

	/** Fluent mode: a two-column paper's pages cut into pieces in reading
	 * order (``paperus.page_layout`` on the server), one column across the screen, the columns
	 * running on into each other. Each piece is a window onto its page
	 * drawn whole at the piece's scale, so selecting, marking and the
	 * annotations work as on the page. */
	let {
		doc,
		layouts,
		width,
		pinch,
		store,
		labelOf,
		leaveOut,
		mark,
		highlight,
		startPage,
		startTop = null,
		startLeft = null,
		readingLine = () => 0,
		onlink,
		viewports,
		current = $bindable(1)
	}: {
		doc: PDFDocumentProxy;
		layouts: PageLayouts;
		/** Of the screen's column (CSS pixels). */
		width: number;
		/** The browser's pinch zoom, once settled. */
		pinch: number;
		store: FileAnnotations | null;
		labelOf: (index: number) => string | null;
		leaveOut: (doc: PDFDocumentProxy, page: PDFPageProxy, index: number) => Promise<boolean>;
		mark: (layer: HTMLElement, passage: string) => void;
		highlight: { page: number; text: string } | null;
		startPage: number;
		/** Where on the start page to begin (PDF points from its top; and
		 * its left: which column): where one stopped reading. */
		startTop?: number | null;
		startLeft?: number | null;
		/** Where on the screen one reads (below the toolbar). */
		readingLine?: () => number;
		/** A link within the paper followed (``pdfLinks``). */
		onlink?: (place: Place) => void;
		/** Each piece's viewport by its key, for marking a selection. */
		viewports: Map<string, Viewport>;
		current?: number;
	} = $props();

	/** A page's picture holds at most this many pixels. */
	const MAX_PIXELS = 2 ** 24;

	const scaleOf = (piece: Piece) => width / piece.span;

	/** A page not found yet: about as tall as found ones. */
	const guess = $derived.by(() => {
		const found = layouts.pages.filter((page) => page !== null);
		if (!found.length) return width * 3;
		const total = found.reduce(
			(sum, page) => sum + page.layout.pieces.reduce((s, p) => s + p.height * scaleOf(p), 0),
			0
		);
		return total / found.length;
	});

	/** The piece's region in its page box (CSS pixels): what of the page's
	 * annotations it shows. */
	const clipOf = (piece: Piece, k: number): Box => ({
		left: piece.x * k,
		top: piece.y * k,
		width: piece.width * k,
		height: piece.height * k
	});

	type Shown = { node: HTMLElement; piece: Piece; k: number; text?: TextLayer };

	/** Draws one page's pieces: the page once at the largest scale, cut. */
	class PageDraw {
		shown = new Map<number, Shown>();
		near = new Set<number>();
		kept = new Set<number>();
		seen = new Set<number>();
		ratio = 0;
		hiding: boolean | null = null;
		task: RenderTask | undefined;
		drawing = false;
		texts = false;
		/** The next page after the one being read: drawn already, before
		 * it comes near. */
		ahead = false;
		readonly number: number;
		constructor(number: number) {
			this.number = number;
		}

		wanted(): number {
			return (window.devicePixelRatio || 1) * (this.seen.size ? pinch : 1);
		}

		update() {
			if (!this.kept.size && this.ratio) {
				this.unload();
				return;
			}
			if ((!this.near.size && !this.ahead) || this.drawing) return;
			const ratio = this.wanted();
			if (!this.ratio || ratio > this.ratio + 0.01) void this.draw(ratio);
		}

		unload() {
			this.task?.cancel();
			for (const shown of this.shown.values()) {
				shown.text?.cancel();
				shown.text = undefined;
				shown.node.replaceChildren();
			}
			this.ratio = 0;
			this.texts = false;
			this.ahead = false;
		}

		async draw(ratio: number) {
			this.drawing = true;
			try {
				const page = await doc.getPage(this.number);
				const pieces = [...this.shown.values()];
				if (!pieces.length) return;
				const most = Math.max(...pieces.map((s) => s.k));
				const viewport = page.getViewport({ scale: most });
				const r = Math.max(
					0.5,
					Math.min(ratio, Math.sqrt(MAX_PIXELS / (viewport.width * viewport.height)))
				);
				const whole = document.createElement('canvas');
				whole.width = Math.floor(viewport.width * r);
				whole.height = Math.floor(viewport.height * r);
				this.hiding ??= await leaveOut(doc, page, this.number - 1);
				this.task = page.render({
					canvas: whole,
					viewport,
					transform: r === 1 ? undefined : [r, 0, 0, r, 0, 0],
					annotationMode: this.hiding ? AnnotationMode.ENABLE_STORAGE : AnnotationMode.ENABLE
				});
				await this.task.promise;
				const at = most * r;
				for (const { node, piece, k } of this.shown.values()) {
					const canvas = document.createElement('canvas');
					canvas.width = Math.max(1, Math.round(piece.width * at));
					canvas.height = Math.max(1, Math.round(piece.height * at));
					canvas.style.left = `${piece.x * k}px`;
					canvas.style.top = `${piece.y * k}px`;
					canvas.style.width = `${piece.width * k}px`;
					canvas.style.height = `${piece.height * k}px`;
					canvas
						.getContext('2d')
						?.drawImage(
							whole,
							piece.x * at,
							piece.y * at,
							piece.width * at,
							piece.height * at,
							0,
							0,
							canvas.width,
							canvas.height
						);
					const old = node.querySelector('canvas');
					if (old) old.replaceWith(canvas);
					else node.prepend(canvas);
				}
				whole.width = 0;
				this.ratio = ratio;
				if (!this.texts) {
					this.texts = true;
					await this.text(page);
				}
			} catch {
				// Cancelled (scrolled far away, or closed).
			} finally {
				this.drawing = false;
				this.task = undefined;
			}
			this.update();
		}

		/** Each piece's selectable text: the page's, only what lies in it. */
		async text(page: PDFPageProxy) {
			const content = await page.getTextContent();
			for (const shown of this.shown.values()) {
				const { node, piece, k } = shown;
				if (onlink) void addLinks(node, doc, page, page.getViewport({ scale: k }), onlink);
				const layer = document.createElement('div');
				layer.className = 'textLayer';
				node.append(layer);
				shown.text = new TextLayer({
					textContentSource: content,
					container: layer,
					viewport: page.getViewport({ scale: k })
				});
				await shown.text.render().catch(() => {});
				const box = node.getBoundingClientRect();
				const clip = clipOf(piece, k);
				for (const span of layer.querySelectorAll<HTMLElement>('span')) {
					if (span.querySelector('span')) continue;
					const r = span.getBoundingClientRect();
					const x = r.left + r.width / 2 - box.left;
					const y = r.top + r.height / 2 - box.top;
					if (
						x < clip.left ||
						x > clip.left + clip.width ||
						y < clip.top ||
						y > clip.top + clip.height
					)
						span.remove();
				}
				if (highlight && highlight.page === this.number) mark(layer, highlight.text);
			}
		}
	}

	const draws = new Map<number, PageDraw>();
	const drawOf = (number: number) => {
		let draw = draws.get(number);
		if (!draw) draws.set(number, (draw = new PageDraw(number)));
		return draw;
	};

	$effect(() => {
		void pinch;
		for (const draw of draws.values()) draw.update();
	});

	let scrolledToStart = untrack(() => startPage) <= 1 && untrack(() => startTop) === null;

	/** Watches a piece: near the screen it is drawn, far away let go. */
	function piece(number: number, index: number, found: Piece, k: number) {
		return (node: HTMLDivElement) => {
			const draw = drawOf(number);
			draw.shown.set(index, { node, piece: found, k });
			const window_ = node.closest<HTMLElement>('.piece') ?? node;
			const watch = (set: Set<number>, margin: string) =>
				new IntersectionObserver(
					([entry]) => {
						if (entry.isIntersecting) set.add(index);
						else set.delete(index);
						draw.update();
					},
					{ rootMargin: margin }
				);
			const watchers = [
				// Drawn well before they show (a column in fluent mode is drawn
				// large: one piece may be taller than the screen), kept a while.
				watch(draw.near, '2500px 0px'),
				watch(draw.kept, '5000px 0px'),
				watch(draw.seen, '0px')
			];
			const reading = new IntersectionObserver(
				([entry]) => {
					if (entry.isIntersecting) {
						current = number;
						layouts.near(number);
						// The next page drawn now, so it is there when reached.
						const next = draws.get(number + 1);
						if (next && !next.ahead) {
							next.ahead = true;
							next.update();
						}
					}
				},
				{ rootMargin: '-40% 0px -59% 0px' }
			);
			for (const watcher of watchers) watcher.observe(window_);
			reading.observe(window_);
			const view = untrack(() => layouts.pages[number - 1]!.view);
			viewports.set(`${number}-${index}`, view.clone({ scale: k }));
			if (!scrolledToStart && number === untrack(() => startPage) && index === 0) {
				scrolledToStart = true;
				const top = untrack(() => startTop);
				if (top === null) window_.scrollIntoView();
				else
					follow(
						number,
						top,
						untrack(() => startLeft)
					);
			}
			return () => {
				for (const watcher of watchers) watcher.disconnect();
				reading.disconnect();
				viewports.delete(`${number}-${index}`);
				draw.shown.get(index)?.text?.cancel();
				draw.shown.delete(index);
				if (!draw.shown.size) {
					draw.unload();
					draws.delete(number);
				}
			};
		};
	}

	/** What follows a break where reading jumps, so that a sentence cut off
	 * makes sense: the next page, the other column, a part across the page
	 * after a column (none between parts across the page). */
	function seamOf(page: number, index: number): string {
		if (index === 0) return `Page ${labelOf(page) ?? page + 1}`;
		const pieces = layouts.pages[page]!.layout.pieces;
		const [before, p] = [pieces[index - 1], pieces[index]];
		if (p.wide) return before.wide ? '' : 'Full width';
		return !before.wide && p.x > before.x + before.width / 2 ? 'Right column' : 'Left column';
	}

	/** A page not found yet: found first when near the screen. */
	function waiting(number: number) {
		return (node: HTMLDivElement) => {
			const near = new IntersectionObserver(
				([entry]) => {
					if (entry.isIntersecting) layouts.near(number);
				},
				{ rootMargin: '1200px 0px' }
			);
			near.observe(node);
			return () => near.disconnect();
		};
	}

	/** Where a place on a page is, from the document's top (null: not
	 * laid out yet). ``top``, ``left``: PDF points from the page's top and
	 * left edge (``left`` says which column, if known). */
	export function offsetOf(
		page: number,
		top: number | null,
		left: number | null = null
	): number | null {
		const found = layouts.pages[page - 1];
		if (!found) {
			const node = document.querySelector(`[data-waiting="${page}"]`);
			return node ? node.getBoundingClientRect().top + window.scrollY : null;
		}
		const y = top ?? 0;
		const pieces = found.layout.pieces;
		const across = (p: Piece) => left === null || (left >= p.x - 4 && left <= p.x + p.width);
		// The piece holding the place; else the next one below it (a place
		// may sit in the space between pieces).
		let index = pieces.findIndex((p) => across(p) && y >= p.y && y < p.y + p.height);
		if (index < 0) {
			let best = Infinity;
			pieces.forEach((p, i) => {
				const below = p.y - y;
				if (across(p) && below >= -4 && below < best) {
					best = below;
					index = i;
				}
			});
		}
		if (index < 0) index = 0;
		const p = pieces[index];
		const node = document.querySelector(`[data-piece="${page}-${index}"]`)?.closest('.piece');
		if (!node) return null;
		const within = Math.max(0, y - p.y) * scaleOf(p);
		return node.getBoundingClientRect().top + window.scrollY + within;
	}

	/** The place being read: in the piece at ``line`` (on the screen), its
	 * page and the place on it (PDF points), its left saying which column;
	 * null between pieces. */
	export function placeAt(line: number): { page: number; top: number; left: number } | null {
		for (const node of document.querySelectorAll<HTMLElement>('.fluent .piece')) {
			const box = node.getBoundingClientRect();
			if (line < box.top || line >= box.bottom) continue;
			const [page, index] = (node.querySelector<HTMLElement>('[data-piece]')?.dataset.piece ?? '')
				.split('-')
				.map(Number);
			const p = layouts.pages[page - 1]?.layout.pieces[index];
			if (!p) return null;
			return { page, top: p.y + (line - box.top) / scaleOf(p), left: p.x };
		}
		return null;
	}

	/** Go to a place (as ``offsetOf``) and keep it at the reading line for
	 * a moment: pages are laid out as they come near, and growing or
	 * shrinking they move it. Stops when the reader scrolls. */
	export function follow(page: number, top: number | null, left: number | null = null) {
		let stop = false;
		const halt = () => (stop = true);
		const inputs = ['wheel', 'touchstart', 'keydown', 'mousedown'] as const;
		for (const input of inputs) window.addEventListener(input, halt, { once: true, passive: true });
		let tries = 0;
		const place = () => {
			if (stop) return;
			const at = offsetOf(page, top, left);
			if (at !== null) {
				const target = Math.max(0, at - readingLine());
				if (Math.abs(window.scrollY - target) > 2) window.scrollTo({ top: target });
			}
			if (tries++ < 20) setTimeout(place, 100);
			else for (const input of inputs) window.removeEventListener(input, halt);
		};
		layouts.near(page);
		requestAnimationFrame(place);
	}

	/** Scroll to a page's first piece. */
	export function show(page: number) {
		const node =
			document.querySelector(`[data-piece="${page}-0"]`)?.closest('.piece') ??
			document.querySelector(`[data-waiting="${page}"]`);
		node?.scrollIntoView();
	}

	$effect(() => {
		layouts.near(startPage);
	});
</script>

<div class="fluent" style:width="{width}px">
	{#each layouts.pages as found, i (i)}
		{#if !found}
			<div
				class="waiting"
				data-waiting={i + 1}
				style:height="{guess}px"
				{@attach waiting(i + 1)}
			></div>
		{:else}
			{#each found.layout.pieces as p, index (index)}
				{@const k = scaleOf(p)}
				{#if (i > 0 || index > 0) && seamOf(i, index)}
					<div class="seam" aria-hidden="true">
						<span>{seamOf(i, index)}</span>
					</div>
				{/if}
				<div
					class="piece"
					class:wide={p.wide}
					style:width="{p.width * k}px"
					style:height="{p.height * k}px"
				>
					<div
						class="page"
						data-page={i + 1}
						data-piece="{i + 1}-{index}"
						style:left="{-p.x * k}px"
						style:top="{-p.y * k}px"
						style:width="{found.width * k}px"
						style:height="{found.height * k}px"
						style:--total-scale-factor={k}
					>
						<div class="sheet" {@attach piece(i + 1, index, p, k)}></div>
						{#if store}
							<AnnotationLayer
								{store}
								index={i}
								viewport={found.view.clone({ scale: k })}
								label={labelOf(i)}
								clip={clipOf(p, k)}
							/>
						{/if}
					</div>
				</div>
			{/each}
		{/if}
	{/each}
</div>

<style>
	.fluent {
		display: grid;
		justify-items: center;
		margin: 0 auto;
		background: white;
		border-radius: 6px;
		overflow: hidden;
	}
	.waiting {
		width: 100%;
	}
	/* A break between pieces: a faint line and what follows. */
	.seam {
		position: relative;
		width: 100%;
		height: 14px;
	}
	.seam::before {
		content: '';
		position: absolute;
		inset: 50% 8px auto;
		border-top: 1px dashed rgb(27 36 64 / 0.18);
	}
	.seam span {
		position: absolute;
		top: 50%;
		right: 8px;
		padding: 0 6px;
		transform: translateY(-50%);
		background: white;
		color: #8a8f9c;
		font-size: 10px;
		line-height: 1;
	}
	.piece {
		position: relative;
		overflow: hidden;
	}
	.page {
		position: absolute;
	}
	.sheet {
		position: absolute;
		inset: 0;
	}
	.sheet :global(canvas) {
		position: absolute;
		display: block;
	}
	/* Above the annotations' colours (selectable), below their notes. */
	.page :global(.textLayer) {
		z-index: 2;
	}
	.page :global(.textLayer span.passage) {
		background: rgb(255 200 0 / 0.38);
		border-radius: 2px;
	}
</style>
