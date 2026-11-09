/** One page's layout for fluent mode: drawn at one pixel a point, where it
 * has ink and where text, cut into pieces (``columns.ts``). Shared by the
 * viewer and the layout tests (which draw on a Node canvas). */

import type { PDFPageProxy } from 'pdfjs-dist';
import { inkOf, layOut, type PageLayout } from './columns.ts';

export type PageViewport = ReturnType<PDFPageProxy['getViewport']>;

/** A canvas to draw on: the browser's, or one made in Node. */
export type MakeCanvas = (width: number, height: number) => HTMLCanvasElement;

/** A page as the column view needs it: its size (PDF points) and pieces. */
export type FoundPage = {
	width: number;
	height: number;
	/** At scale 1; ``clone({ scale })`` for another. */
	view: PageViewport;
	layout: PageLayout;
};

/** The page's layout. ``first``: the document's first page. */
export async function analysePage(
	page: PDFPageProxy,
	makeCanvas: MakeCanvas,
	first: boolean
): Promise<FoundPage> {
	const view = page.getViewport({ scale: 1 });
	const canvas = makeCanvas(Math.ceil(view.width), Math.ceil(view.height));
	await page.render({ canvas, viewport: view }).promise;
	const { text, turned } = await textBoxes(page, view, canvas.width, canvas.height);
	// Turned text (a download line running up the margin, arXiv's stamp) is
	// no part of the page's reading: its ink goes, however close it sits.
	const ink = inkOf(canvas);
	for (const [x0, y0, x1, y1] of turned)
		for (let row = y0; row <= y1; row++)
			ink.fill(0, row * canvas.width + x0, row * canvas.width + x1 + 1);
	const layout = layOut(ink, canvas.width, canvas.height, first, text);
	canvas.width = 0;
	return { width: view.width, height: view.height, view, layout };
}

/** Where a page has text (its glyphs' boxes, one pixel a point): ink
 * outside them is drawn (figures). ``turned``: the boxes of text set
 * upright or upside down (x0, y0, x1, y1). */
async function textBoxes(
	page: PDFPageProxy,
	view: PageViewport,
	width: number,
	height: number
): Promise<{ text: Uint8Array; turned: [number, number, number, number][] }> {
	const boxes = new Uint8Array(width * height);
	const turned: [number, number, number, number][] = [];
	const content = await page.getTextContent();
	for (const item of content.items) {
		if (!('str' in item) || !item.str.trim()) continue;
		const [a, b, c, d, e, f] = item.transform as number[];
		const size = Math.hypot(c, d);
		// Along the line (a, b), and up from it (c, d): its four corners.
		if (Math.abs(b) > Math.abs(a)) {
			const along = Math.hypot(a, b);
			const [ux, uy] = [a / along, b / along];
			const [vx, vy] = [c / size, d / size];
			const corners = [
				[0, -0.3],
				[item.width, -0.3],
				[0, 1],
				[item.width, 1]
			].map(([s, t]) =>
				view.convertToViewportPoint(e + ux * s + vx * t * size, f + uy * s + vy * t * size)
			) as [number, number][];
			const xs = corners.map(([x]) => x);
			const ys = corners.map(([, y]) => y);
			turned.push([
				Math.max(0, Math.floor(Math.min(...xs)) - 1),
				Math.max(0, Math.floor(Math.min(...ys)) - 1),
				Math.min(width - 1, Math.ceil(Math.max(...xs)) + 1),
				Math.min(height - 1, Math.ceil(Math.max(...ys)) + 1)
			]);
			continue;
		}
		const [x, y] = view.convertToViewportPoint(e, f) as [number, number];
		const x0 = Math.max(0, Math.floor(x));
		const x1 = Math.min(width - 1, Math.ceil(x + item.width));
		const y0 = Math.max(0, Math.floor(y - size));
		const y1 = Math.min(height - 1, Math.ceil(y + size * 0.3));
		for (let row = y0; row <= y1; row++) boxes.fill(1, row * width + x0, row * width + x1 + 1);
	}
	return { text: boxes, turned };
}
