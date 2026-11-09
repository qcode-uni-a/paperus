import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist';
import { inkOf, layOut, type PageLayout } from '#lib/columns.ts';

export type PageViewport = ReturnType<PDFPageProxy['getViewport']>;

/** A page as the column view needs it: its size (PDF points) and pieces. */
export type FoundPage = {
	width: number;
	height: number;
	/** At scale 1; ``clone({ scale })`` for another. */
	view: PageViewport;
	layout: PageLayout;
};

/** The pages' layouts for the column view, found in the background one
 * page at a time, those near the page being read first. */
export class PageLayouts {
	pages = $state.raw<(FoundPage | null)[]>([]);
	#doc: PDFDocumentProxy;
	#around = 1;
	#running = false;
	#stopped = false;

	constructor(doc: PDFDocumentProxy) {
		this.#doc = doc;
		this.pages = Array.from({ length: doc.numPages }, () => null);
	}

	/** Whether the paper is set in two columns: most of its first pages. */
	async twoColumns(): Promise<boolean> {
		const count = Math.min(3, this.pages.length);
		for (let number = 1; number <= count; number++) await this.find(number);
		const found = this.pages.slice(0, count).filter((page) => page?.layout.columns).length;
		return found >= Math.min(2, count);
	}

	/** Find the rest, nearest to ``page`` first. */
	near(page: number) {
		this.#around = page;
		void this.#run();
	}

	stop() {
		this.#stopped = true;
	}

	async #run() {
		if (this.#running) return;
		this.#running = true;
		while (!this.#stopped) {
			let next = 0;
			let best = Infinity;
			this.pages.forEach((page, i) => {
				const distance = Math.abs(i + 1 - this.#around) + (i + 1 < this.#around ? 0.5 : 0);
				if (!page && distance < best) {
					best = distance;
					next = i + 1;
				}
			});
			if (!next) break;
			await this.find(next);
			// Let scrolling and drawing go first.
			await new Promise((resolve) => setTimeout(resolve, 0));
		}
		this.#running = false;
	}

	/** One page's layout, from a picture of it at one pixel a point. */
	async find(number: number): Promise<FoundPage | null> {
		const known = this.pages[number - 1];
		if (known) return known;
		try {
			const page = await this.#doc.getPage(number);
			const view = page.getViewport({ scale: 1 });
			const canvas = document.createElement('canvas');
			canvas.width = Math.ceil(view.width);
			canvas.height = Math.ceil(view.height);
			await page.render({ canvas, viewport: view }).promise;
			const text = await textBoxes(page, view, canvas.width, canvas.height);
			const layout = layOut(inkOf(canvas), canvas.width, canvas.height, number === 1, text);
			canvas.width = 0;
			const found = { width: view.width, height: view.height, view, layout };
			if (this.#stopped || this.pages[number - 1]) return this.pages[number - 1];
			const pages = [...this.pages];
			pages[number - 1] = found;
			this.pages = pages;
			return found;
		} catch {
			return null;
		}
	}
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
