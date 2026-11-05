<script lang="ts">
	import 'pdfjs-dist/web/pdf_viewer.css';
	import {
		getDocument,
		GlobalWorkerOptions,
		TextLayer,
		type PDFDocumentProxy,
		type RenderTask
	} from 'pdfjs-dist';
	import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

	GlobalWorkerOptions.workerSrc = workerUrl;

	let { url, startPage = 1 }: { url: string; startPage?: number } = $props();

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
				pdf = doc;
			})
			.catch((reason: unknown) => {
				if (!cancelled) error = reason instanceof Error ? reason.message : String(reason);
			});
		return () => {
			cancelled = true;
			pdf = null;
			task.destroy();
		};
	});

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
					node.style.width = `${viewport.width}px`;
					node.style.height = `${viewport.height}px`;

					const ratio = window.devicePixelRatio || 1;
					const canvas = document.createElement('canvas');
					canvas.width = Math.floor(viewport.width * ratio);
					canvas.height = Math.floor(viewport.height * ratio);
					canvas.style.width = `${viewport.width}px`;
					canvas.style.height = `${viewport.height}px`;
					const layer = document.createElement('div');
					layer.className = 'textLayer';
					node.replaceChildren(canvas, layer);

					rendering = pdfPage.render({
						canvas,
						viewport,
						transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0]
					});
					await rendering.promise.catch(() => {});
					text = new TextLayer({
						textContentSource: pdfPage.streamTextContent(),
						container: layer,
						viewport
					});
					await text.render().catch(() => {});
				},
				{ rootMargin: '800px 0px' }
			);
			const visible = new IntersectionObserver(
				([entry]) => {
					if (entry.isIntersecting) current = number;
				},
				{ threshold: 0.5 }
			);
			nearby.observe(node);
			visible.observe(node);
			if (number === startPage && number > 1) node.scrollIntoView();

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
	{:else if !pdf}
		<p class="muted">Opening PDF…</p>
	{:else}
		<div class="toolbar">
			<span class="muted">{current} / {pdf.numPages}</span>
			<div class="row">
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
				<a href={url} target="_blank" rel="noreferrer">Open file</a>
			</div>
		</div>
		<div class="pages">
			{#each pages as number (number)}
				{#key scale}
					<div
						class="page"
						id="page-{number}"
						style:width="{(firstPage?.width ?? 0) * scale}px"
						style:height="{(firstPage?.height ?? 0) * scale}px"
						style:--total-scale-factor={scale}
						{@attach page(number)}
					></div>
				{/key}
			{/each}
		</div>
	{/if}
</div>

<style>
	.viewer {
		width: 100%;
	}
	.toolbar {
		position: sticky;
		top: 56px;
		z-index: 5;
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 8px;
		padding: 6px 0;
		background: color-mix(in srgb, var(--paper) 94%, transparent);
		backdrop-filter: blur(8px);
	}
	.toolbar button {
		padding: 2px 10px;
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
	.page :global(canvas) {
		display: block;
	}
</style>
