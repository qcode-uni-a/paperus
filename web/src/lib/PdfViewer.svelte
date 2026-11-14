<script lang="ts">
	import { mdiArrowLeft, mdiOpenInNew, mdiTextLong } from '@mdi/js';
	import { tick } from 'svelte';
	import ColumnView from '#lib/ColumnView.svelte';
	import { PageLayouts } from '#lib/pageLayouts.svelte.ts';
	import Icon from '#lib/Icon.svelte';
	import 'pdfjs-dist/web/pdf_viewer.css';
	import {
		AnnotationMode,
		getDocument,
		GlobalWorkerOptions,
		TextLayer,
		type PDFDocumentLoadingTask,
		type PDFDocumentProxy,
		type RenderTask
	} from 'pdfjs-dist';
	import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
	import PdfContents from '#lib/PdfContents.svelte';
	import { cachedPdf, keepPdf } from '#lib/pdfCache.ts';
	import { pdfFiles } from '#lib/pdfjs.ts';
	import { session } from '#lib/session.svelte.ts';
	import { contents, type Section } from '#lib/pdfContents.ts';
	import { addLinks, type Place as LinkPlace } from '#lib/pdfLinks.ts';
	import AnnotationLayer from '#lib/annotations/AnnotationLayer.svelte';
	import AnnotationsPanel from '#lib/annotations/AnnotationsPanel.svelte';
	import AnnotationTools from '#lib/annotations/AnnotationTools.svelte';
	import SelectionMenu from '#lib/annotations/SelectionMenu.svelte';
	import { FileAnnotations, type AnnotationOut } from '#lib/annotations/annotations.svelte.ts';
	import type { Viewport } from '#lib/annotations/geometry.ts';

	GlobalWorkerOptions.workerSrc = workerUrl;

	let {
		url,
		startPage = 1,
		startTop = null,
		startLeft = null,
		onplace,
		highlight = null,
		fileId = null,
		sha256 = null,
		itemId = null,
		title = '',
		coverPages = []
	}: {
		url: string;
		startPage?: number;
		/** Where on the start page to begin: PDF points from its top (and
		 * its left: which column, in fluent mode), where one stopped. */
		startTop?: number | null;
		startLeft?: number | null;
		/** Where one is reading, as one scrolls (and once more, ``leaving``,
		 * when the page is hidden or left): to go on from there. */
		onplace?: (place: Place, leaving: boolean) => void;
		/** A passage to mark on its page (e.g. from a search result). */
		highlight?: { page: number; text: string; scroll?: boolean } | null;
		/** With these, the file's annotations are shown and made. */
		fileId?: string | null;
		/** The file's content: with ``fileId``, kept in the browser to show
		 * it again without downloading it (``pdfCache``). */
		sha256?: string | null;
		itemId?: string | null;
		/** The paper's (for a note gathered from the annotations). */
		title?: string;
		/** Pages a site put in front of or behind the paper (from 1): fluent
		 * mode leaves them out, with a way to show them. */
		coverPages?: number[];
	} = $props();

	type Place = { page: number; top: number; left: number | null };

	const MAX_WIDTH = 1000;
	// Horizontal padding of the desk around the pages (see .pages).
	const DESK_PADDING = 24;
	const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3];

	let pdf = $state.raw<PDFDocumentProxy | null>(null);
	let firstPage = $state<{ width: number; height: number } | null>(null);
	let error = $state('');
	let width = $state(0);
	let zoomIndex = $state(2);
	let current = $state(1);
	let sections = $state<Section[]>([]);
	/** The chapter being read: the last one starting above the reading line. */
	let reading = $state(-1);
	let toolbar = $state<HTMLElement>();
	let viewer = $state<HTMLElement>();

	/** Fluent mode (two-column papers): the columns one after another. */
	let layouts = $state.raw<PageLayouts | null>(null);
	let fluent = $state(false);
	let columnView = $state<ReturnType<typeof ColumnView>>();
	/** The pieces' viewports in fluent mode (by ``data-piece``). */
	const pieceViewports = new Map<string, Viewport>();
	const FLUENT = 'paperus.fluent';

	/** Fluent mode for a two-column paper: as last chosen, else on phones. */
	function wantFluent(): boolean {
		let chosen: string | null = null;
		try {
			chosen = localStorage.getItem(FLUENT);
		} catch {
			// No storage: the default.
		}
		if (chosen) return chosen === 'on';
		return window.matchMedia('(max-width: 720px)').matches;
	}

	/** The place at the reading line: in fluent mode its piece's, else
	 * the page's there (no column known). */
	function placeNow(): Place | null {
		const line = readingLine();
		if (fluent) return columnView?.placeAt(line) ?? null;
		for (const node of document.querySelectorAll<HTMLElement>('.pages > .page')) {
			const box = node.getBoundingClientRect();
			if (line < box.top || line >= box.bottom || !scale) continue;
			return { page: Number(node.dataset.page), top: (line - box.top) / scale, left: null };
		}
		return null;
	}

	// The place, a moment after scrolling stops, and when leaving.
	$effect(() => {
		if (!onplace || !pdf) return;
		let timer: ReturnType<typeof setTimeout> | undefined;
		let last = '';
		const send = (leaving: boolean) => {
			const place = placeNow();
			if (!place) return;
			const key = `${place.page}:${Math.round(place.top / 8)}:${place.left}`;
			if (key === last && !leaving) return;
			last = key;
			onplace(place, leaving);
		};
		const scrolled = () => {
			clearTimeout(timer);
			timer = setTimeout(() => send(false), 1500);
		};
		const hidden = () => {
			if (document.visibilityState === 'hidden') send(true);
		};
		const leaving = () => send(true);
		window.addEventListener('scroll', scrolled, { passive: true });
		document.addEventListener('visibilitychange', hidden);
		window.addEventListener('pagehide', leaving);
		return () => {
			clearTimeout(timer);
			send(true);
			window.removeEventListener('scroll', scrolled);
			document.removeEventListener('visibilitychange', hidden);
			window.removeEventListener('pagehide', leaving);
		};
	});

	/** Fluent mode on or off, staying on the page being read. */
	async function toggleFluent() {
		const at = current;
		fluent = !fluent;
		try {
			localStorage.setItem(FLUENT, fluent ? 'on' : 'off');
		} catch {
			// Not remembered.
		}
		await tick();
		if (fluent) columnView?.show(at);
		else document.getElementById(`page-${at}`)?.scrollIntoView();
	}

	// Annotations: loaded before the pages are drawn (the PDF's own marks
	// are left out once they were taken in).
	const store = $derived(fileId && itemId ? new FileAnnotations(fileId, itemId) : null);
	$effect(() => {
		store?.load();
	});
	/** Each drawn page's viewport (page number from 1), for the layers. */
	let viewports = $state.raw<Record<number, Viewport>>({});
	let labels = $state.raw<string[] | null>(null);
	const labelOf = (index: number) => labels?.[index] ?? null;
	// Pages are drawn again at another zoom: their old viewports are gone.
	$effect(() => {
		void scale;
		viewports = {};
	});

	/** To an annotation: its page, then the annotation once drawn. */
	function goTo(annotation: AnnotationOut) {
		if (!store) return;
		store.selected = annotation.id;
		if (fluent) columnView?.show(annotation.page_index + 1);
		else document.getElementById(`page-${annotation.page_index + 1}`)?.scrollIntoView();
		let tries = 0;
		const look = () => {
			const found = document.getElementById(`annotation-${annotation.id}`);
			if (found) found.scrollIntoView({ block: 'center' });
			else if (tries++ < 30) setTimeout(look, 100);
		};
		look();
	}

	/** The browser's pinch zoom once it settles (1 unzoomed): the pages on
	 * screen are then drawn again that much sharper, else the browser only
	 * enlarges their pictures and the letters blur. */
	let pinch = $state(1);
	$effect(() => {
		const seen = window.visualViewport;
		if (!seen) return;
		let timer = 0;
		const settle = () => {
			clearTimeout(timer);
			timer = window.setTimeout(() => {
				pinch = Math.max(1, Math.round(seen.scale * 4) / 4);
			}, 250);
		};
		seen.addEventListener('resize', settle);
		return () => {
			clearTimeout(timer);
			seen.removeEventListener('resize', settle);
		};
	});
	/** Each drawn page's check whether to draw it again (page number from 1). */
	const sharpen = new Map<number, () => void>();
	$effect(() => {
		void pinch;
		for (const check of sharpen.values()) check();
	});

	const scale = $derived(
		firstPage && width
			? (Math.min(width - DESK_PADDING, MAX_WIDTH) / firstPage.width) * ZOOMS[zoomIndex]
			: 0
	);
	const pages = $derived(pdf ? Array.from({ length: pdf.numPages }, (_, i) => i + 1) : []);

	$effect(() => {
		const user = session.user?.id;
		const kept = fileId && sha256 && user ? ([fileId, sha256, user] as const) : null;
		let task: PDFDocumentLoadingTask | null = null;
		let cancelled = false;
		let downloaded = false;
		let timer: ReturnType<typeof setTimeout> | undefined;
		/** The server still works out the layouts: asked again, and the
		 * fluent toggle shown once they are there; switched to as if there
		 * from the start if the paper has not been scrolled yet. */
		let openedAt: number | null = null;
		const later = (seconds: number) => {
			timer = setTimeout(async () => {
				const doc = pdf;
				if (cancelled || !doc || !fileId) return;
				const ready = await PageLayouts.load(doc, fileId, later).catch(() => null);
				if (cancelled || !ready) return ready?.stop();
				layouts = ready;
				const still = openedAt !== null && Math.abs(window.scrollY - openedAt) < 40;
				if (still && ready.twoColumns() && wantFluent()) fluent = true;
			}, seconds * 1000);
		};
		error = '';
		(async () => {
			const data = kept ? await cachedPdf(...kept) : null;
			if (cancelled) return;
			downloaded = !data;
			task = getDocument({ ...pdfFiles(), ...(data ? { data } : { url, withCredentials: true }) });
			return task.promise;
		})()
			.then(async (doc) => {
				if (!doc) return;
				// Downloaded: kept for next time, once all of it is here.
				if (kept && downloaded)
					doc.getData().then(
						(bytes) => keepPdf(...kept, bytes),
						() => {}
					);
				const found = fileId ? PageLayouts.load(doc, fileId, later) : null;
				const viewport = (await doc.getPage(1)).getViewport({ scale: 1 });
				if (cancelled) return;
				firstPage = { width: viewport.width, height: viewport.height };
				labels = await doc.getPageLabels().catch(() => null);
				const ready = await found?.catch(() => null);
				if (cancelled) {
					ready?.stop();
					return;
				}
				layouts = ready ?? null;
				fluent = !!ready?.twoColumns() && wantFluent();
				pdf = doc;
				openedAt = window.scrollY;
				contents(doc).then((found) => {
					if (!cancelled) sections = found;
				});
			})
			.catch((reason: unknown) => {
				if (!cancelled) error = reason instanceof Error ? reason.message : String(reason);
			});
		return () => {
			cancelled = true;
			clearTimeout(timer);
			layouts?.stop();
			layouts = null;
			fluent = false;
			pdf = null;
			sections = [];
			viewports = {};
			task?.destroy();
		};
	});

	/** Letters and digits only, lower case: line breaks, hyphens at line
	 * ends, spacing and ligatures (NFKC) differ between how the server read
	 * the PDF and PDF.js's text layer; the letters do not. */
	function letters(text: string): string {
		return text
			.normalize('NFKC')
			.toLowerCase()
			.replace(/[^\p{L}\p{N}]/gu, '');
	}

	/** Where a chapter starts on the page, from the document's top. */
	function offsetOf(section: LinkPlace): number | null {
		if (fluent) return columnView?.offsetOf(section.page, section.top, section.left) ?? null;
		const node = document.getElementById(`page-${section.page}`);
		if (!node) return null;
		return node.getBoundingClientRect().top + window.scrollY + (section.top ?? 0) * scale;
	}

	/** Below the site's header and this toolbar, where reading happens. */
	function readingLine(): number {
		// Where the toolbar sticks (not where it is now: before the pages
		// scroll, it sits lower).
		if (!toolbar) return 112;
		const top = parseFloat(getComputedStyle(toolbar).top) || 0;
		return top + toolbar.offsetHeight + 12;
	}

	/** Where the paper's own link was followed from, to go back to. */
	let back = $state<Place | null>(null);

	/** A link within the paper: there, with the way back. */
	function follow(place: LinkPlace) {
		// (Above the first page, or between pieces: the page's top.)
		back = placeNow() ?? { page: current, top: 0, left: null };
		go(place);
	}

	function goBack() {
		const place = back;
		back = null;
		if (place) go(place);
	}

	function go(section: LinkPlace) {
		// Fluent mode: a jump, then the place followed while pages are laid
		// out around it (scrolling through them would move it on the way).
		if (fluent && columnView) {
			columnView.follow(section.page, section.top, section.left);
			return;
		}
		const offset = offsetOf(section);
		if (offset === null) return;
		const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
		window.scrollTo({ top: offset - readingLine(), behavior: smooth ? 'smooth' : 'auto' });
	}

	$effect(() => {
		if (!sections.length || !scale) return;
		let frame = 0;
		const update = () => {
			frame = 0;
			const line = window.scrollY + readingLine() + 4;
			let found = -1;
			sections.forEach((section, index) => {
				const offset = offsetOf(section);
				if (offset !== null && offset <= line) found = index;
			});
			reading = found;
		};
		const later = () => {
			if (!frame) frame = requestAnimationFrame(update);
		};
		update();
		window.addEventListener('scroll', later, { passive: true });
		window.addEventListener('resize', later);
		return () => {
			cancelAnimationFrame(frame);
			window.removeEventListener('scroll', later);
			window.removeEventListener('resize', later);
		};
	});

	/** Find a passage in a page's text layer and mark its spans. */
	function mark(layer: HTMLElement, passage: string) {
		const spans = [...layer.querySelectorAll<HTMLElement>('span')].filter(
			(span) => !span.querySelector('span')
		);
		let page = '';
		const ends: number[] = [];
		for (const span of spans) {
			page += letters(span.textContent ?? '');
			ends.push(page.length);
		}
		const wanted = letters(passage);
		if (!wanted || !page) return;
		const WINDOW = 40;
		// The start and the end of the passage, each by a stretch of its
		// letters; tried a little further in if the first stretch differs.
		let start = -1;
		for (let at = 0; start < 0 && at < Math.min(wanted.length, 400); at += 20) {
			const found = page.indexOf(wanted.slice(at, at + WINDOW));
			if (found >= 0) start = Math.max(0, found - at);
		}
		if (start < 0) return;
		let end = -1;
		for (let at = wanted.length; end < 0 && at > Math.max(0, wanted.length - 400); at -= 20) {
			const piece = wanted.slice(Math.max(0, at - WINDOW), at);
			const found = page.indexOf(piece, start);
			if (found >= 0) end = Math.min(page.length, found + piece.length + (wanted.length - at));
		}
		if (end < 0) end = Math.min(page.length, start + wanted.length);
		let first: HTMLElement | null = null;
		spans.forEach((span, index) => {
			const from = index === 0 ? 0 : ends[index - 1];
			if (ends[index] > start && from < end && ends[index] > from) {
				span.classList.add('passage');
				first ??= span;
			}
		});
		if (highlight?.scroll !== false)
			(first as HTMLElement | null)?.scrollIntoView({ block: 'center' });
	}

	/** The PDF's own annotations taken in as paperus's (found by where they
	 * sit) are marked deleted for PDF.js, so the page is drawn without
	 * them; the rest of the PDF's stay. Whether any were. */
	async function leaveOut(
		doc: PDFDocumentProxy,
		pdfPage: Awaited<ReturnType<PDFDocumentProxy['getPage']>>,
		index: number
	): Promise<boolean> {
		const marks = store?.hiddenMarks.filter((m) => m.page_index === index) ?? [];
		if (!marks.length) return false;
		const own = (await pdfPage.getAnnotations()) as {
			id: string;
			rect: number[];
			popupRef?: string | null;
		}[];
		let any = false;
		for (const mark of marks) {
			const found = own.find((a) =>
				a.rect?.every((value, i) => Math.abs(value - mark.rect[i]) < 1)
			);
			if (!found) continue;
			doc.annotationStorage.setValue(`pdfjs_internal_editor_paperus_${found.id}`, {
				pageIndex: index,
				id: found.id,
				deleted: true,
				popupRef: found.popupRef ?? undefined
			});
			any = true;
		}
		return any;
	}

	/** A page's picture holds at most this many pixels (phones refuse
	 * larger canvases or run out of memory). */
	const MAX_PIXELS = 2 ** 24;

	/** Render a page (canvas + selectable text) once it comes near the
	 * screen; on screen while pinch-zoomed, drawn again that much sharper;
	 * back to the usual sharpness once it leaves the screen's neighbourhood. */
	function page(number: number) {
		return (node: HTMLDivElement) => {
			const doc = pdf;
			const pageScale = scale;
			if (!doc || !pageScale) return;
			let rendering: RenderTask | undefined;
			let text: TextLayer | undefined;
			let started = false;
			let onScreen = false;
			let near = false;
			/** What the picture is drawn with, once it is. */
			let drawn: {
				pdfPage: Awaited<ReturnType<PDFDocumentProxy['getPage']>>;
				viewport: ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['getViewport']>;
				hiding: boolean;
				ratio: number;
			} | null = null;
			let redrawing: RenderTask | undefined;

			const usual = () => window.devicePixelRatio || 1;
			/** Pixels per CSS pixel for the picture: the screen's, times the
			 * pinch zoom while on screen, within MAX_PIXELS. */
			function wanted(): number {
				if (!drawn) return usual();
				const { width: w, height: h } = drawn.viewport;
				const most = Math.sqrt(MAX_PIXELS / (w * h));
				return onScreen ? Math.max(usual(), Math.min(usual() * pinch, most)) : usual();
			}

			function canvasFor(ratio: number) {
				const { width: w, height: h } = drawn!.viewport;
				const canvas = document.createElement('canvas');
				canvas.width = Math.floor(w * ratio);
				canvas.height = Math.floor(h * ratio);
				canvas.style.width = `${w}px`;
				canvas.style.height = `${h}px`;
				return canvas;
			}

			function draw(canvas: HTMLCanvasElement, ratio: number): RenderTask {
				const { pdfPage, viewport, hiding } = drawn!;
				return pdfPage.render({
					canvas,
					viewport,
					transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
					annotationMode: hiding ? AnnotationMode.ENABLE_STORAGE : AnnotationMode.ENABLE
				});
			}

			/** Draw again if the picture is not as sharp as wanted: sharper
			 * on screen (drawn aside, then swapped in, so nothing flashes);
			 * away from the screen, shrunk from the sharp one. */
			function check() {
				if (!drawn) return;
				const ratio = wanted();
				if (Math.abs(ratio - drawn.ratio) < 0.01) return;
				const old = node.querySelector('canvas');
				if (!old) return;
				redrawing?.cancel();
				redrawing = undefined;
				const canvas = canvasFor(ratio);
				if (ratio < drawn.ratio) {
					if (near) return;
					canvas.getContext('2d')?.drawImage(old, 0, 0, canvas.width, canvas.height);
					old.replaceWith(canvas);
					drawn.ratio = ratio;
					return;
				}
				const task = draw(canvas, ratio);
				redrawing = task;
				task.promise.then(
					() => {
						if (redrawing !== task || !drawn) return;
						node.querySelector('canvas')?.replaceWith(canvas);
						drawn.ratio = ratio;
						redrawing = undefined;
					},
					() => {}
				);
			}

			const nearby = new IntersectionObserver(
				async ([entry]) => {
					near = entry.isIntersecting;
					if (!near) {
						check();
						return;
					}
					if (started) return;
					started = true;
					const pdfPage = await doc.getPage(number);
					const viewport = pdfPage.getViewport({ scale: pageScale });
					const sheet = node.parentElement ?? node;
					sheet.style.width = `${viewport.width}px`;
					sheet.style.height = `${viewport.height}px`;

					drawn = { pdfPage, viewport, hiding: false, ratio: usual() };
					const canvas = canvasFor(drawn.ratio);
					const layer = document.createElement('div');
					layer.className = 'textLayer';
					node.replaceChildren(canvas, layer);

					drawn.hiding = await leaveOut(doc, pdfPage, number - 1);
					rendering = draw(canvas, drawn.ratio);
					viewports = { ...viewports, [number]: viewport };
					await rendering.promise.catch(() => {});
					text = new TextLayer({
						textContentSource: pdfPage.streamTextContent(),
						container: layer,
						viewport
					});
					await text.render().catch(() => {});
					void addLinks(node, doc, pdfPage, viewport, follow);
					if (highlight && highlight.page === number) mark(layer, highlight.text);
					check();
				},
				{ rootMargin: '800px 0px' }
			);
			// The page across the window's middle (also a page zoomed taller
			// than the window; and never one on its way out, whose report
			// can come after the next one's).
			const visible = new IntersectionObserver(
				([entry]) => {
					if (entry.isIntersecting) current = number;
				},
				{ rootMargin: '-50% 0px -50% 0px' }
			);
			const seen = new IntersectionObserver(([entry]) => {
				onScreen = entry.isIntersecting;
				if (onScreen) check();
			});
			const sheet = node.parentElement ?? node;
			nearby.observe(sheet);
			visible.observe(sheet);
			seen.observe(sheet);
			sharpen.set(number, check);
			if (number === startPage && startTop !== null) {
				// Where one stopped: that place at the reading line.
				const at = sheet.getBoundingClientRect().top + window.scrollY + startTop * pageScale;
				window.scrollTo({ top: Math.max(0, at - readingLine()) });
			} else if (number === startPage && number > 1) sheet.scrollIntoView();

			return () => {
				sharpen.delete(number);
				nearby.disconnect();
				visible.disconnect();
				seen.disconnect();
				rendering?.cancel();
				redrawing?.cancel();
				text?.cancel();
				node.replaceChildren();
			};
		};
	}
</script>

<div class="viewer" bind:clientWidth={width}>
	{#if error}
		<p class="error">Could not open the PDF: {error}</p>
	{:else if !pdf || (store && !store.loaded)}
		<p class="muted">Opening PDF…</p>
	{:else}
		<div class="toolbar" bind:this={toolbar}>
			<div class="row where">
				{#if sections.length}<PdfContents {sections} current={reading} {go} />{/if}
				<span class="muted">{current} / {pdf.numPages}</span>
				{#if back}
					<button class="back" onclick={goBack} title="Back to where you followed the link from"
						><Icon path={mdiArrowLeft} size={16} />Back</button
					>
				{/if}
			</div>
			<div class="row">
				{#if store}
					<AnnotationTools {store} />
					<AnnotationsPanel {store} {title} go={goTo} />
				{/if}
				{#if layouts}
					<button
						class="fluent-toggle"
						class:on={fluent}
						aria-pressed={fluent}
						title={fluent
							? 'Fluent mode: the columns one after another (click for the pages)'
							: 'Fluent mode: the columns one after another'}
						aria-label="Fluent mode"
						onclick={toggleFluent}><Icon path={mdiTextLong} size={20} /></button
					>
				{/if}
				<!-- Phones zoom by pinching. -->
				<div class="row zoom" class:hidden={fluent}>
					<button
						onclick={() => (zoomIndex = Math.max(0, zoomIndex - 1))}
						disabled={zoomIndex === 0}
						aria-label="Zoom out">−</button
					>
					<span class="muted">{Math.round(ZOOMS[zoomIndex] * 100)}%</span>
					<button
						onclick={() => (zoomIndex = Math.min(ZOOMS.length - 1, zoomIndex + 1))}
						disabled={zoomIndex === ZOOMS.length - 1}
						aria-label="Zoom in">+</button
					>
				</div>
				<a
					class="open"
					href={url}
					target="_blank"
					rel="noreferrer"
					title="Open the PDF in a new tab"
					aria-label="Open the PDF in a new tab"><Icon path={mdiOpenInNew} size={20} /></a
				>
			</div>
		</div>
		{#if fluent && layouts}
			<div class="pages fluent-desk" bind:this={viewer}>
				<ColumnView
					bind:this={columnView}
					bind:current
					doc={pdf}
					{layouts}
					width={Math.min(width, 560)}
					{pinch}
					{store}
					{labelOf}
					{leaveOut}
					{mark}
					{highlight}
					{startPage}
					{startTop}
					{startLeft}
					{readingLine}
					covers={coverPages}
					onlink={follow}
					viewports={pieceViewports}
				/>
			</div>
		{:else}
			<div class="pages" bind:this={viewer}>
				{#each pages as number (number)}
					{#key scale}
						<div
							class="page"
							id="page-{number}"
							data-page={number}
							style:width="{(firstPage?.width ?? 0) * scale}px"
							style:height="{(firstPage?.height ?? 0) * scale}px"
							style:--total-scale-factor={scale}
						>
							<div class="sheet" {@attach page(number)}></div>
							{#if store && viewports[number]}
								<AnnotationLayer
									{store}
									index={number - 1}
									viewport={viewports[number]}
									label={labelOf(number - 1)}
								/>
							{/if}
						</div>
					{/key}
				{/each}
			</div>
		{/if}
		{#if store}
			<SelectionMenu
				{store}
				root={viewer}
				viewportOf={(node) =>
					node.dataset.piece
						? pieceViewports.get(node.dataset.piece)
						: viewports[Number(node.dataset.page)]}
				{labelOf}
			/>
		{/if}
	{/if}
</div>

<style>
	.viewer {
		width: 100%;
	}
	.back {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 2px 10px 2px 6px;
		flex: none;
	}
	.toolbar {
		position: sticky;
		top: var(--header-height, 72px);
		z-index: 5;
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
		padding: 6px 0;
	}
	/* The blur on a layer of its own: on the toolbar it would pin the phone's
	   round annotate button (position: fixed) to the toolbar, not the screen. */
	.toolbar::before {
		content: '';
		position: absolute;
		inset: 0;
		z-index: -1;
		background: color-mix(in srgb, var(--paper) 94%, transparent);
		backdrop-filter: blur(8px);
	}
	.toolbar button {
		padding: 2px 10px;
	}
	/* One line: the chapter's name takes what the rest leaves, cut with "…". */
	.toolbar .row {
		flex-wrap: nowrap;
		white-space: nowrap;
	}
	.open {
		display: grid;
		place-items: center;
		width: 32px;
		height: 32px;
		border-radius: 50%;
		color: var(--muted);
	}
	.open:hover {
		color: var(--royal);
		background: var(--rail);
	}
	@media (max-width: 720px) {
		.zoom {
			display: none;
		}
	}
	.zoom.hidden {
		display: none;
	}
	.fluent-toggle {
		display: grid;
		place-items: center;
		width: 32px;
		height: 32px;
		padding: 0 !important;
		border: none;
		border-radius: 50%;
		background: none;
		color: var(--muted);
	}
	.fluent-toggle.on {
		background: color-mix(in srgb, var(--royal) 14%, transparent);
		color: var(--royal);
	}
	.pages.fluent-desk {
		padding: 12px 0 32px;
	}
	.where {
		flex: 1 1 auto;
		min-width: 0;
		gap: 12px;
	}
	.pages {
		display: grid;
		justify-items: center;
		gap: 12px;
		overflow-x: auto;
		padding: 20px 12px 32px;
		background: var(--desk);
		border-radius: 10px;
	}
	.page {
		position: relative;
		background: white;
		box-shadow:
			0 1px 2px rgb(27 36 64 / 0.12),
			0 4px 16px rgb(27 36 64 / 0.1);
		max-width: none;
	}
	.sheet {
		position: absolute;
		inset: 0;
	}
	.page :global(canvas) {
		display: block;
	}
	/* Above the annotations' colours (selectable), below their notes. */
	.page :global(.textLayer) {
		z-index: 2;
	}
	/* The passage one came for (text layer spans are transparent text). */
	.page :global(.textLayer span.passage) {
		background: rgb(255 200 0 / 0.38);
		border-radius: 2px;
	}
</style>
