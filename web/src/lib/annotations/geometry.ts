/** Positions of annotations: PDF points from the page's lower left (as PDF
 * annotations store them, and the server keeps them), drawn on the page in
 * CSS pixels of its viewport (any zoom, any rotation). */

import type { PDFPageProxy } from 'pdfjs-dist';

export type Viewport = ReturnType<PDFPageProxy['getViewport']>;
/** x1, y1, x2, y2 */
export type Rect = [number, number, number, number];
/** In CSS pixels from the page's top left. */
export type Box = { left: number; top: number; width: number; height: number };

/** A point on the page (CSS pixels from its top left) in PDF points. */
export function toPdf(viewport: Viewport, x: number, y: number): [number, number] {
	const [px, py] = viewport.convertToPdfPoint(x, y) as [number, number];
	return [px, py];
}

/** A PDF point on the page, in CSS pixels from its top left. */
export function toView(viewport: Viewport, x: number, y: number): [number, number] {
	const [vx, vy] = viewport.convertToViewportPoint(x, y) as [number, number];
	return [vx, vy];
}

/** A box on the page (CSS pixels) as a PDF rect, lower left first. */
export function boxToRect(viewport: Viewport, box: Box): Rect {
	const [x1, y1] = toPdf(viewport, box.left, box.top);
	const [x2, y2] = toPdf(viewport, box.left + box.width, box.top + box.height);
	return [Math.min(x1, x2), Math.min(y1, y2), Math.max(x1, x2), Math.max(y1, y2)];
}

/** A PDF rect as a box on the page (CSS pixels). */
export function rectToBox(viewport: Viewport, rect: number[]): Box {
	const [x1, y1] = toView(viewport, rect[0], rect[1]);
	const [x2, y2] = toView(viewport, rect[2], rect[3]);
	return {
		left: Math.min(x1, x2),
		top: Math.min(y1, y2),
		width: Math.abs(x2 - x1),
		height: Math.abs(y2 - y1)
	};
}

/** The rects a selection covers on a page, joined into one box per line
 * (pdf.js's text layer gives one per word or span). ``page``: the page's
 * own box on the screen. */
export function lineBoxes(rects: Iterable<DOMRectReadOnly>, page: DOMRectReadOnly): Box[] {
	const boxes = [...rects]
		.filter((r) => r.width >= 1 && r.height >= 1)
		.map((r) => ({
			left: Math.max(r.left, page.left) - page.left,
			top: Math.max(r.top, page.top) - page.top,
			width: Math.min(r.right, page.right) - Math.max(r.left, page.left),
			height: Math.min(r.bottom, page.bottom) - Math.max(r.top, page.top)
		}))
		.filter((b) => b.width > 0 && b.height > 0)
		.sort((a, b) => a.top - b.top || a.left - b.left);
	const lines: Box[] = [];
	for (const box of boxes) {
		const line = lines.find((l) => {
			const overlap = Math.min(l.top + l.height, box.top + box.height) - Math.max(l.top, box.top);
			return overlap > Math.min(l.height, box.height) * 0.5;
		});
		if (!line) {
			lines.push({ ...box });
			continue;
		}
		const right = Math.max(line.left + line.width, box.left + box.width);
		const bottom = Math.max(line.top + line.height, box.top + box.height);
		line.left = Math.min(line.left, box.left);
		line.top = Math.min(line.top, box.top);
		line.width = right - line.left;
		line.height = bottom - line.top;
	}
	return lines;
}

/** How far a point is from a pen stroke (CSS pixels), for the eraser. */
export function distanceToPath(points: [number, number][], x: number, y: number): number {
	let best = Infinity;
	for (let i = 0; i < points.length; i++) {
		const [ax, ay] = points[i];
		const [bx, by] = points[i + 1] ?? points[i];
		const dx = bx - ax;
		const dy = by - ay;
		const length = dx * dx + dy * dy;
		const t = length ? Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / length)) : 0;
		best = Math.min(best, Math.hypot(x - (ax + t * dx), y - (ay + t * dy)));
	}
	return best;
}
