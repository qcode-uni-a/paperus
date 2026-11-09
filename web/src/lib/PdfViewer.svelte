<script lang="ts">
	import { mdiOpenInNew } from '@mdi/js';
	import Icon from '#lib/Icon.svelte';
	import 'pdfjs-dist/web/pdf_viewer.css';
	import {
		AnnotationMode,
		getDocument,
		GlobalWorkerOptions,
		TextLayer,
		type PDFDocumentProxy,
		type RenderTask
	} from 'pdfjs-dist';
	import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
	import PdfContents from '#lib/PdfContents.svelte';
	import { contents, type Section } from '#lib/pdfContents.ts';
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
		highlight = null,
		fileId = null,
		itemId = null,
		title = ''
	}: {
		url: string;
		startPage?: number;
		/** A passage to mark on its page (e.g. from a search result). */
		highlight?: { page: number; text: string } | null;
		/** With these, the file's annotations are shown and made. */
		fileId?: string | null;
		itemId?: string | null;
		/** The paper's (for a note gathered from the annotations). */
		title?: string;
	} = $props();

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
		document.getElementById(`page-${annotation.page_index + 1}`)?.scrollIntoView();
		let tries = 0;
		const look = () => {
			const found = document.getElementById(`annotation-${annotation.id}`);
			if (found) found.scrollIntoView({ block: 'center' });
			else if (tries++ < 30) setTimeout(look, 100);
		};
		look();
	}

	const scale = $derived(
		firstPage && width
			? (Math.min(width - DESK_PADDING, MAX_WIDTH) / firstPage.width) * ZOOMS[zoomIndex]
			: 0
	);
	const pages = $derived(pdf ? Array.from({ length: pdf.numPages }, (_, i) => i + 1) : []);

	$effect(() => {
		const task = getDocument({ url, withCredentials: true });
		let cancelled = false;
		error = '';
		task.promise
			.then(async (doc) => {
				const viewport = (await doc.getPage(1)).getViewport({ scale: 1 });
				if (cancelled) return;
				firstPage = { width: viewport.width, height: viewport.height };
				labels = await doc.getPageLabels().catch(() => null);
				pdf = doc;
				contents(doc).then((found) => {
					if (!cancelled) sections = found;
				});
			})
			.catch((reason: unknown) => {
				if (!cancelled) error = reason instanceof Error ? reason.message : String(reason);
			});
		return () => {
			cancelled = true;
			pdf = null;
			sections = [];
			viewports = {};
			task.destroy();
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
	function offsetOf(section: Section): number | null {
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

	function go(section: Section) {
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

	/** Render a page (canvas + selectable text) once it comes near the screen. */
	function page(number: number) {
		return (node: HTMLDivElement) => {
			const doc = pdf;
			const pageScale = scale;
			if (!doc || !pageScale) return;
			let rendering: RenderTask | undefined;
			let text: TextLayer | undefined;
			let started = false;

			const nearby = new IntersectionObserver(
				async ([entry]) => {
					if (!entry.isIntersecting || started) return;
					started = true;
					const pdfPage = await doc.getPage(number);
					const viewport = pdfPage.getViewport({ scale: pageScale });
					const sheet = node.parentElement ?? node;
					sheet.style.width = `${viewport.width}px`;
					sheet.style.height = `${viewport.height}px`;

					const ratio = window.devicePixelRatio || 1;
					const canvas = document.createElement('canvas');
					canvas.width = Math.floor(viewport.width * ratio);
					canvas.height = Math.floor(viewport.height * ratio);
					canvas.style.width = `${viewport.width}px`;
					canvas.style.height = `${viewport.height}px`;
					const layer = document.createElement('div');
					layer.className = 'textLayer';
					node.replaceChildren(canvas, layer);

					const hiding = await leaveOut(doc, pdfPage, number - 1);
					rendering = pdfPage.render({
						canvas,
						viewport,
						transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
						annotationMode: hiding ? AnnotationMode.ENABLE_STORAGE : AnnotationMode.ENABLE
					});
					viewports = { ...viewports, [number]: viewport };
					await rendering.promise.catch(() => {});
					text = new TextLayer({
						textContentSource: pdfPage.streamTextContent(),
						container: layer,
						viewport
					});
					await text.render().catch(() => {});
					if (highlight && highlight.page === number) mark(layer, highlight.text);
				},
				{ rootMargin: '800px 0px' }
			);
			const visible = new IntersectionObserver(
				([entry]) => {
					if (entry.isIntersecting) current = number;
				},
				{ threshold: 0.5 }
			);
			const sheet = node.parentElement ?? node;
			nearby.observe(sheet);
			visible.observe(sheet);
			if (number === startPage && number > 1) sheet.scrollIntoView();

			return () => {
				nearby.disconnect();
				visible.disconnect();
				rendering?.cancel();
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
			</div>
			<div class="row">
				{#if store}
					<AnnotationTools {store} />
					<AnnotationsPanel {store} {title} go={goTo} />
				{/if}
				<!-- Phones zoom by pinching. -->
				<div class="row zoom">
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
		<div class="pages" bind:this={viewer}>
			{#each pages as number (number)}
				{#key scale}
					<div
						class="page"
						id="page-{number}"
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
		{#if store}
			<SelectionMenu {store} root={viewer} viewportOf={(number) => viewports[number]} {labelOf} />
		{/if}
	{/if}
</div>

<style>
	.viewer {
		width: 100%;
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
