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
	const text = await textBoxes(page, view, canvas.width, canvas.height);
	const layout = layOut(inkOf(canvas), canvas.width, canvas.height, first, text);
	canvas.width = 0;
	return { width: view.width, height: view.height, view, layout };
}

/** Where a page has text (its glyphs' boxes, one pixel a point): ink
 * outside them is drawn (figures). */
async function textBoxes(
	page: PDFPageProxy,
	view: PageViewport,
	width: number,
	height: number
): Promise<Uint8Array> {
	const boxes = new Uint8Array(width * height);
	const content = await page.getTextContent();
	for (const item of content.items) {
		if (!('str' in item) || !item.str.trim()) continue;
		const [, , c, d, e, f] = item.transform as number[];
		const size = Math.hypot(c, d);
		const [x, y] = view.convertToViewportPoint(e, f) as [number, number];
		const x0 = Math.max(0, Math.floor(x));
		const x1 = Math.min(width - 1, Math.ceil(x + item.width));
		const y0 = Math.max(0, Math.floor(y - size));
		const y1 = Math.min(height - 1, Math.ceil(y + size * 0.3));
		for (let row = y0; row <= y1; row++) boxes.fill(1, row * width + x0, row * width + x1 + 1);
	}
	return boxes;
}
