import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist';
import { fileLayout } from '#lib/api/client.ts';
import type { LayoutPiece, PageLayoutOut, PageLayoutsOut } from '#lib/api/generated/types.gen.ts';

/** A part of a page, in PDF points from its top left (in reading order). */
export type Piece = LayoutPiece;

export type PageViewport = ReturnType<PDFPageProxy['getViewport']>;

/** A page as the column view needs it: its size (PDF points) and pieces. */
export type FoundPage = {
	width: number;
	height: number;
	/** At scale 1; ``clone({ scale })`` for another. */
	view: PageViewport;
	layout: PageLayoutOut;
};

/** The pages' layouts for the column view, worked out on the server once
 * per file (``paperus.page_layout``): fetched once, and each page's
 * viewport taken in the background, those near the page being read first. */
export class PageLayouts {
	pages = $state.raw<(FoundPage | null)[]>([]);
	#doc: PDFDocumentProxy;
	#layouts: PageLayoutOut[];
	#around = 1;
	#running = false;
	#stopped = false;

	private constructor(doc: PDFDocumentProxy, layouts: PageLayoutOut[]) {
		this.#doc = doc;
		this.#layouts = layouts;
		this.pages = Array.from({ length: doc.numPages }, () => null);
	}

	/** The file's layouts: null while the server is still working them out
	 * (``waiting`` is told; ask again later), or if it cannot (no PDF it
	 * can read, or another number of pages than this one). */
	static async load(
		doc: PDFDocumentProxy,
		fileId: string,
		waiting?: (seconds: number) => void
	): Promise<PageLayouts | null> {
		const { data, response } = await fileLayout({ path: { file_id: fileId } });
		if (response?.status === 202) {
			waiting?.(Number(response.headers.get('Retry-After')) || 3);
			return null;
		}
		const pages = response?.ok ? (data as PageLayoutsOut).pages : null;
		if (!pages || pages.length !== doc.numPages) return null;
		return new PageLayouts(doc, pages);
	}

	/** Whether the paper is set in two columns: most of its first pages. */
	twoColumns(): boolean {
		const first = this.#layouts.slice(0, 3);
		return first.filter((page) => page.columns).length >= Math.min(2, first.length);
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

	/** One page's layout, with its viewport. */
	async find(number: number): Promise<FoundPage | null> {
		const known = this.pages[number - 1];
		if (known) return known;
		try {
			const view = (await this.#doc.getPage(number)).getViewport({ scale: 1 });
			const layout = this.#layouts[number - 1];
			if (this.#stopped || this.pages[number - 1]) return this.pages[number - 1];
			const pages = [...this.pages];
			pages[number - 1] = { width: view.width, height: view.height, view, layout };
			this.pages = pages;
			return pages[number - 1];
		} catch {
			return null;
		}
	}
}
