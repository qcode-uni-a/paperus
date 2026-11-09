/** What fluent mode must get right on a layout twin (``twins.py``): its
 * lines read in their order, every figure whole in one piece, the running
 * headers and footers left out. */

import type { PageLayout } from '../../src/lib/columns.ts';

/** A box from the page's top left (PDF points): x0, y0, x1, y1. */
export type Box = [number, number, number, number];

export type Spec = {
	name: string;
	/** Where the layout comes from (a journal, a kind of page). */
	source: string;
	size: [number, number];
	/** The document's first page (its top line is a title). */
	first: boolean;
	/** Expected: set in two columns (``PageLayout.columns``). */
	columns?: boolean;
	lines: {
		box: Box;
		size: number;
		/** Text to read; a figure's labels; a running header or footer. */
		role: 'body' | 'figure' | 'furniture';
		/** Body lines: their place in the reading order. */
		order?: number;
	}[];
	figures: {
		box: Box;
		panels: { box: Box; kind: 'picture' | 'drawing' }[];
		/** Where it is (columns of cells, rows from the top): "1" ink. */
		ink?: string[];
		/** Parts each whole in one piece, if not the whole figure (two
		 * figures close together, measured as one). */
		parts?: Box[];
	}[];
	/** Why fluent mode does not read this page right yet: the test runs it
	 * as a known gap (``todo``). */
	todo?: string;
	marks: { box: Box; kind: string }[];
	rules: Box[];
};

export type Checked = {
	problems: string[];
	/** Each line's piece (index in reading order), -1 for none. */
	pieceOf: number[];
};

/** A box's middle (the order lines are read in: down, then across). */
export const middle = (box: Box): [number, number] => [
	(box[0] + box[2]) / 2,
	(box[1] + box[3]) / 2
];

export function check(spec: Spec, layout: PageLayout): Checked {
	const problems: string[] = [];
	const { pieces } = layout;
	const holds = (i: number, [x, y]: [number, number]) => {
		const p = pieces[i];
		return x >= p.x && x <= p.x + p.width && y >= p.y && y <= p.y + p.height;
	};
	const pieceOf = spec.lines.map((line) => {
		const at = middle(line.box);
		return pieces.findIndex((_, i) => holds(i, at));
	});

	if (spec.columns !== undefined && layout.columns !== spec.columns)
		problems.push(`read as ${layout.columns ? 'two columns' : 'one column'}`);

	// Body lines: each in a piece, read in order (piece after piece, down
	// each piece, left to right on a line).
	const body = spec.lines
		.map((line, i) => ({ line, i, piece: pieceOf[i], at: middle(line.box) }))
		.filter(({ line }) => line.role === 'body');
	const lost = body.filter((b) => b.piece < 0);
	if (lost.length)
		problems.push(
			`${lost.length} lines in no piece (orders ${lost.map((b) => b.line.order).join(', ')})`
		);
	const read = body
		.filter((b) => b.piece >= 0)
		.sort((a, b) => a.piece - b.piece || a.at[1] - b.at[1] || a.at[0] - b.at[0]);
	for (let i = 1; i < read.length; i++) {
		const [before, now] = [read[i - 1], read[i]];
		if (now.line.order! < before.line.order!) {
			problems.push(
				`line ${now.line.order} (piece ${now.piece}) read after line ${before.line.order} (piece ${before.piece})`
			);
			if (problems.length > 8) break;
		}
	}

	// Pieces side by side or one after another, not over each other (their
	// half-line margins aside).
	pieces.forEach((a, i) =>
		pieces.slice(i + 1).forEach((b, k) => {
			const w = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
			const h = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
			if (w > 8 && h > 8 && w * h > Math.min(a.width * a.height, b.width * b.height) * 0.25)
				problems.push(`pieces ${i} and ${i + 1 + k} overlap`);
		})
	);

	// Running headers and footers: in no piece.
	spec.lines.forEach((line, i) => {
		if (line.role === 'furniture' && pieceOf[i] >= 0)
			problems.push(`header or footer at y ${Math.round(line.box[1])} kept (piece ${pieceOf[i]})`);
	});

	// Figures: whole in one piece (or each of their parts).
	spec.figures.forEach((figure, n) => {
		for (const [x0, y0, x1, y1] of figure.parts ?? [figure.box]) {
			const area = (x1 - x0) * (y1 - y0);
			const best = Math.max(
				0,
				...pieces.map((p) => {
					const w = Math.min(x1, p.x + p.width) - Math.max(x0, p.x);
					const h = Math.min(y1, p.y + p.height) - Math.max(y0, p.y);
					return w > 0 && h > 0 ? (w * h) / area : 0;
				})
			);
			if (best < 0.9)
				problems.push(`figure ${n + 1} split (at most ${Math.round(best * 100)}% in one piece)`);
		}
	});
	return { problems, pieceOf };
}
