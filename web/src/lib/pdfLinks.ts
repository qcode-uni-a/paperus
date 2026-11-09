/** The paper's own links over its pages: to a place in it (a reference, a
 * chapter, a figure, an equation), or to a web page. Only http(s) and
 * mailto addresses become links, opened in a tab of their own that cannot
 * reach back (noopener, noreferrer); the address shows on hover. */

import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist';
import { destination } from '#lib/pdfContents.ts';

type Viewport = ReturnType<PDFPageProxy['getViewport']>;

/** A place in the paper: a page, PDF points from its top and left edge. */
export type Place = { page: number; top: number | null; left: number | null };

const SAFE = /^(https?:|mailto:)/i;

type LinkAnnotation = { subtype?: string; rect?: number[]; dest?: unknown; url?: string };

/** Lays the page's links over ``node`` (the page drawn at ``viewport``);
 * a link within the paper calls ``go``. */
export async function addLinks(
	node: HTMLElement,
	pdf: PDFDocumentProxy,
	page: PDFPageProxy,
	viewport: Viewport,
	go: (place: Place) => void
): Promise<void> {
	const annotations = (await page.getAnnotations({ intent: 'display' })) as LinkAnnotation[];
	const layer = document.createElement('div');
	layer.className = 'linkLayer';
	for (const a of annotations) {
		if (a.subtype !== 'Link' || !Array.isArray(a.rect) || a.rect.length !== 4) continue;
		const [x1, y1] = viewport.convertToViewportPoint(a.rect[0], a.rect[1]) as number[];
		const [x2, y2] = viewport.convertToViewportPoint(a.rect[2], a.rect[3]) as number[];
		const link = document.createElement('a');
		Object.assign(link.style, {
			left: `${Math.min(x1, x2)}px`,
			top: `${Math.min(y1, y2)}px`,
			width: `${Math.abs(x2 - x1)}px`,
			height: `${Math.abs(y2 - y1)}px`
		});
		if (a.dest) {
			link.href = '#';
			link.title = 'Go there in the paper';
			link.addEventListener('click', async (event) => {
				event.preventDefault();
				const place = await destination(pdf, a.dest).catch(() => null);
				if (place) go(place);
			});
		} else if (typeof a.url === 'string' && SAFE.test(a.url)) {
			link.href = a.url;
			link.target = '_blank';
			link.rel = 'noopener noreferrer nofollow';
			link.title = a.url;
		} else continue;
		layer.append(link);
	}
	if (layer.childElementCount) node.append(layer);
}
