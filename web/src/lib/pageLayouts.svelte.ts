import type { PDFDocumentProxy } from 'pdfjs-dist';
import { analysePage, type FoundPage } from '#lib/pageAnalysis.ts';

export type { FoundPage, PageViewport } from '#lib/pageAnalysis.ts';

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
			const found = await analysePage(
				page,
				(width, height) => Object.assign(document.createElement('canvas'), { width, height }),
				number === 1
			);
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
