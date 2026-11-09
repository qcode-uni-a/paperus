/** Fluent mode: a paper's pages cut into pieces in reading order, so
 * that on a narrow screen one column fills it and the columns run on into
 * each other (a part across the page, then the left column, the right
 * column, …), without margins, running headers and footers.
 *
 * Found from where a page has ink, drawn at one pixel per PDF point: the
 * page's body is cut into blocks at blank space; in each block, the gap
 * between two columns is a strip near the middle that its lines do not
 * cross, and the rows crossing it (a title, an abstract, a figure over both
 * columns) stay whole. A part in one column keeps only its own ink. */

/** A part of a page, in PDF points from its top left. */
export type Piece = {
	x: number;
	y: number;
	width: number;
	height: number;
	/** Across the page's width (else one column). */
	wide: boolean;
	/** The width that fills the screen: the body's for a wide piece, the
	 * wider column's for a column (both columns' text the same size). */
	span: number;
};

export type PageLayout = {
	/** The page is set in two columns (over a good part of it). */
	columns: boolean;
	pieces: Piece[];
};

/** Narrower ink at a page's side is a margin note (arXiv's stamp, line
 * numbers), not the page's body. */
const MARGIN_NOTE = 30;
/** Blank space that separates ink across the page (points). */
const SIDE_GAP = 8;
/** The gap between columns is at least this wide. */
const GUTTER = 7;
/** How far a line's ink reaches beyond its middle part (points). */
const LINE_REACH = 5;
/** Blank space between blocks of the page, each with its own columns. */
const BLOCK_SPLIT = 9;
/** A figure's panels are at most this far apart. */
const FIGURE_GAP = 30;
/** A stretch of two columns is at least this tall (a few lines). */
const MIN_COLUMNS = 36;
/** A running header or footer: a block of a line or two (with a rule, a
 * small logo) at the page's top or bottom edge, set apart from the body. */
const EDGE_BLOCK = 40;
const EDGE = 0.09;
/** A logo or mark in a corner, leaving the middle empty, may be taller. */
const CORNER_BLOCK = 70;
const CORNER_EDGE = 0.14;
/** Lines closer than this belong to one block. */
const BLOCK_GAP = 6;

/** Which pixels of a page's picture are ink (dark enough to be print). */
export function inkOf(canvas: HTMLCanvasElement): Uint8Array {
	const context = canvas.getContext('2d', { willReadFrequently: true })!;
	const { data } = context.getImageData(0, 0, canvas.width, canvas.height);
	const ink = new Uint8Array(canvas.width * canvas.height);
	for (let i = 0; i < ink.length; i++) {
		const alpha = data[i * 4 + 3];
		const light = (data[i * 4] * 3 + data[i * 4 + 1] * 6 + data[i * 4 + 2]) / 10;
		ink[i] = alpha > 128 && light < 215 ? 1 : 0;
	}
	return ink;
}

/** Runs of true values: [start, end] inclusive. */
function runs(values: boolean[], from = 0, to = values.length - 1): [number, number][] {
	const found: [number, number][] = [];
	let start = -1;
	for (let i = from; i <= to + 1; i++) {
		const on = i <= to && values[i];
		if (on && start < 0) start = i;
		if (!on && start >= 0) {
			found.push([start, i - 1]);
			start = -1;
		}
	}
	return found;
}

/** Runs joined where the space between them is smaller than ``gap``. */
function joined(found: [number, number][], gap: number): [number, number][] {
	const out: [number, number][] = [];
	for (const run of found) {
		const last = out.at(-1);
		if (last && run[0] - last[1] - 1 < gap) last[1] = run[1];
		else out.push([...run]);
	}
	return out;
}

/** Long thin upright lines (a rule between columns, a box's side, a
 * plot's axis) left out: across them every row has ink, as if the page
 * were one line. */
function withoutUprights(ink: Uint8Array, width: number, height: number): Uint8Array {
	const out = new Uint8Array(ink);
	const LONG = 80;
	for (let x = 0; x < width; x++) {
		let start = -1;
		for (let y = 0; y <= height; y++) {
			const on = y < height && ink[y * width + x] === 1;
			if (on && start < 0) start = y;
			if (on || start < 0) continue;
			if (y - start >= LONG) {
				// Thin: little ink a few points either side along it.
				let beside = 0;
				for (let r = start; r < y; r++) {
					if (x >= 3 && ink[r * width + x - 3]) beside++;
					if (x + 3 < width && ink[r * width + x + 3]) beside++;
				}
				if (beside < (y - start) * 0.4)
					for (let r = start; r < y; r++)
						for (let dx = -1; dx <= 1; dx++)
							if (x + dx >= 0 && x + dx < width) out[r * width + x + dx] = 0;
			}
			start = -1;
		}
	}
	return out;
}

/** A page's pieces from its ink (``width`` × ``height`` pixels, one a
 * point). ``first``: the document's first page (its top line is a title,
 * not a running header). */
export function layOut(
	ink: Uint8Array,
	width: number,
	height: number,
	first = false,
	text: Uint8Array | null = null
): PageLayout {
	ink = withoutUprights(ink, width, height);
	const at = (x: number, y: number) => ink[y * width + x] === 1;
	/** Mostly drawn, not written: a figure (its ink outside the page's
	 * text boxes, ``text``). */
	const drawn = (x0: number, x1: number, y0: number, y1: number) => {
		if (!text) return false;
		let all = 0;
		let outside = 0;
		for (let y = y0; y <= y1; y++)
			for (let x = x0; x <= x1; x++)
				if (at(x, y)) {
					all++;
					if (!text[y * width + x]) outside++;
				}
		return all > 50 && outside > all * 0.5;
	};
	const whole: PageLayout = { columns: false, pieces: [] };

	// The body across: ink separated by blank space, without margin notes.
	const inColumn = Array.from({ length: width }, (_, x) => {
		for (let y = 0; y < height; y++) if (at(x, y)) return true;
		return false;
	});
	const across = joined(runs(inColumn), SIDE_GAP);
	while (across.length > 1 && across[0][1] - across[0][0] < MARGIN_NOTE) across.shift();
	while (across.length > 1 && across.at(-1)![1] - across.at(-1)![0] < MARGIN_NOTE) across.pop();
	if (!across.length) return whole;
	const left = across[0][0];
	const right = across.at(-1)![1];
	const bodyWidth = right - left + 1;

	// The body down: lines of ink; a running header and footer left out.
	const inRow = Array.from({ length: height }, (_, y) => {
		for (let x = left; x <= right; x++) if (at(x, y)) return true;
		return false;
	});
	// A rule near the top or the bottom (a row inked across most of the
	// body) sets off a running header or footer: it goes, with what lies
	// beyond it.
	const rule = (y: number) => {
		let count = 0;
		for (let x = left; x <= right; x++) if (at(x, y)) count++;
		return count >= bodyWidth * 0.8;
	};
	let headEnd = -1;
	for (let y = 0; y < height * EDGE; y++) if (inRow[y] && rule(y)) headEnd = y;
	let footStart = height;
	for (let y = height - 1; y > height * (1 - EDGE); y--) if (inRow[y] && rule(y)) footStart = y;
	const lines = runs(inRow, headEnd + 1, footStart - 1);
	if (!lines.length) return whole;
	// Running headers and footers (page numbers, journal lines, logos)
	// left out: up to two blocks at each edge, apart from the body. On the
	// first page only a small one above the title, or a mark in a corner.
	const blocks = joined(lines, BLOCK_GAP);
	const span = (block: [number, number]) => block[1] - block[0] + 1;
	const middleFrom = Math.round(left + bodyWidth * 0.3);
	const middleTo = Math.round(left + bodyWidth * 0.7);
	const inCorner = ([y0, y1]: [number, number]) => {
		for (let y = y0; y <= y1; y++)
			for (let x = middleFrom; x <= middleTo; x++) if (at(x, y)) return false;
		return true;
	};
	const edgeBlock = (block: [number, number], atTop: boolean) => {
		const reach = atTop ? block[1] : height - block[0];
		if (inCorner(block) && span(block) <= CORNER_BLOCK && reach < height * CORNER_EDGE) return true;
		if (reach >= height * EDGE) return false;
		if (atTop && first) return span(block) <= 12 && block[1] < height * 0.075;
		return span(block) <= EDGE_BLOCK;
	};
	for (let i = 0; i < 2 && blocks.length > 1; i++) {
		const [head, next] = blocks;
		if (!edgeBlock(head, true) || next[0] - head[1] - 1 < SIDE_GAP) break;
		blocks.shift();
	}
	for (let i = 0; i < 2 && blocks.length > 1; i++) {
		const foot = blocks.at(-1)!;
		const before = blocks.at(-2)!;
		if (!edgeBlock(foot, false) || foot[0] - before[1] - 1 < SIDE_GAP) break;
		blocks.pop();
	}
	const body = lines.filter(([a]) => a >= blocks[0][0] && a <= blocks.at(-1)![1]);
	lines.splice(0, lines.length, ...body);
	const top = lines[0][0];
	const bottom = lines.at(-1)![1];
	// Half the usual space between lines, around each piece.
	const spaces = lines
		.slice(1)
		.map((line, i) => line[0] - lines[i][1] - 1)
		.filter((space) => space > 0)
		.sort((a, b) => a - b);
	const pad = Math.min(
		8,
		Math.max(2, Math.round((spaces[Math.floor(spaces.length / 2)] ?? 4) / 2))
	);

	/** Ink of the rows ``y0``–``y1`` between ``x0`` and ``x1``: its
	 * extent, or null. A rule alone at its top or bottom edge, apart from
	 * the rest (the marks above and below an equation across both
	 * columns, a column's closing rule), is left out. */
	const extent = (x0: number, x1: number, y0: number, y1: number) => {
		const found = inkExtent(x0, x1, y0, y1);
		if (!found) return null;
		const count = (y: number) => {
			let n = 0;
			for (let x = x0; x <= x1; x++) if (at(x, y)) n++;
			return n;
		};
		/** The longest unbroken stretch of ink in row ``y`` (a rule's is
		 * long; text breaks at every letter). */
		const stretch = (y: number) => {
			let best = 0;
			let run = 0;
			for (let x = x0; x <= x1; x++) {
				run = at(x, y) ? run + 1 : 0;
				if (run > best) best = run;
			}
			return best;
		};
		const width = found.x1 - found.x0 + 1;
		/** From the edge row ``from`` going ``step``: the first row past a
		 * rule standing alone there (a tick beside it allowed), or null. */
		const pastRule = (from: number, step: number, limit: number) => {
			let y = from;
			let rule = false;
			for (; step < 0 ? y >= limit : y <= limit; y += step) {
				const n = count(y);
				if (!n) break;
				if (Math.abs(y - from) > 8) return null;
				if (stretch(y) >= width * 0.5) rule = true;
				else if (n > width * 0.15) return null; // a line of text
			}
			if (!rule) return null;
			while ((step < 0 ? y >= limit : y <= limit) && !count(y)) y += step;
			return step < 0 ? (y >= limit ? y : null) : y <= limit ? y : null;
		};
		let [top, bottom] = [found.y0, found.y1];
		top = pastRule(top, 1, bottom) ?? top;
		bottom = pastRule(bottom, -1, top) ?? bottom;
		return top === found.y0 && bottom === found.y1 ? found : inkExtent(x0, x1, top, bottom);
	};

	const inkExtent = (x0: number, x1: number, y0: number, y1: number) => {
		let minX = Infinity;
		let maxX = -1;
		let minY = Infinity;
		let maxY = -1;
		for (let y = y0; y <= y1; y++)
			for (let x = x0; x <= x1; x++)
				if (at(x, y)) {
					if (x < minX) minX = x;
					if (x > maxX) maxX = x;
					if (y < minY) minY = y;
					maxY = y;
				}
		return maxX < 0 ? null : { x0: minX, x1: maxX, y0: minY, y1: maxY };
	};

	/** The gap between two columns in rows ``y0``–``y1``: a strip near
	 * the body's middle that long stretches of rows (a few lines at least)
	 * do not cross, holding the most ink between them. One column of text
	 * crosses any strip a few points wide on nearly every line (word spaces
	 * are narrower); a figure across the page breaks the stretches, not
	 * the columns beside it, and its own gaps do not count. Null if there
	 * is none. */
	const gutterOf = (y0: number, y1: number): [number, number] | null => {
		const from = Math.round(left + bodyWidth * 0.3);
		const to = Math.round(left + bodyWidth * 0.7);
		const starts = to - from + 1 - GUTTER;
		if (starts <= 0) return null;
		// A figure's own gaps (between its panels) are not columns.
		const figures = new Map<string, boolean>();
		const figure = (a: number, b: number) => {
			const key = `${a}-${b}`;
			if (!figures.has(key)) figures.set(key, drawn(left, right, a, b));
			return figures.get(key)!;
		};
		/** Per strip: ink rows in long uncrossed stretches; the current one. */
		const free = new Int32Array(starts);
		const length = new Int32Array(starts);
		const inked = new Int32Array(starts);
		let inkRows = 0;
		for (let y = y0; y <= y1 + 1; y++) {
			const end = y > y1;
			const ink = !end && inRow[y];
			if (ink) inkRows++;
			let count = 0;
			if (ink) for (let x = from; x < from + GUTTER; x++) if (at(x, y)) count++;
			for (let g = 0; g < starts; g++) {
				if (end || count) {
					if (length[g] >= MIN_COLUMNS && !figure(y - length[g], y - 1)) free[g] += inked[g];
					length[g] = 0;
					inked[g] = 0;
				} else {
					length[g]++;
					if (ink) inked[g]++;
				}
				if (ink) {
					if (at(from + g, y)) count--;
					if (at(from + g + GUTTER, y)) count++;
				}
			}
		}
		// Enough of the page's text beside the gap (a page that is mostly
		// figure has little).
		let textRows = inkRows;
		if (text) {
			textRows = 0;
			for (let y = y0; y <= y1; y++) {
				if (!inRow[y]) continue;
				for (let x = left; x <= right; x++)
					if (text[y * width + x] && at(x, y)) {
						textRows++;
						break;
					}
			}
		}
		const most = Math.max(...free);
		if (most < Math.max(MIN_COLUMNS * 1.5, textRows * 0.2)) return null;
		const quiet = runs([...free].map((rows) => rows >= most * 0.9));
		const middle = starts / 2;
		const [a, b] = quiet.sort(
			(p, q) => Math.abs((p[0] + p[1]) / 2 - middle) - Math.abs((q[0] + q[1]) / 2 - middle)
		)[0];
		return [from + a, from + b + GUTTER - 1];
	};

	/** From row ``start`` going ``step`` (up -1, down 1) no further than
	 * ``limit``: rows that belong with the part they touch rather than with
	 * what follows (closer to it than to the rest, a few lines at most): the
	 * last of them, else null. */
	const edgeOf = (start: number, step: number, limit: number): number | null => {
		const within = (y: number) => (step < 0 ? y >= limit : y <= limit);
		let y = start;
		let near = 0;
		while (within(y) && !inRow[y]) {
			near++;
			y += step;
		}
		if (!within(y) || near >= BLOCK_SPLIT) return null;
		let last = y;
		let far = 0;
		// Rows without a line of text in them (an equation's limits and
		// brackets) go with it over less space.
		let text = false;
		const apart = () => far >= (text ? BLOCK_SPLIT : 3);
		for (; within(y); y += step) {
			if (inRow[y]) {
				if (apart()) break;
				// The rows themselves a few lines at most (the space after
				// them may be wide).
				if (Math.abs(y - start) > MIN_COLUMNS) return null;
				if (dense(y)) text = true;
				last = y;
				far = 0;
			} else far++;
		}
		return apart() && far > near ? last : null;
	};

	/** Lines (of text, or a figure) filling most of ``x0``–``x1``: a few at
	 * least in rows ``y0``–``y1``, as a column of text has. A line is a run
	 * of rows with much ink (lines of dense text touch; between them a row
	 * has little). */
	const filled = (x0: number, x1: number, y0: number, y1: number) => {
		const counts = Array.from({ length: y1 - y0 + 1 }, (_, i) => {
			let count = 0;
			for (let x = x0; x <= x1; x++) if (at(x, y0 + i)) count++;
			return count;
		});
		const most = Math.max(0, ...counts);
		if (!most) return false;
		let full = 0;
		for (const [a, b] of runs(counts.map((count) => count >= most * 0.3))) {
			if (b - a < 2) continue; // a rule, not a line
			let from = x1;
			let to = x0;
			for (let y = y0 + a; y <= y0 + b; y++)
				for (let x = x0; x <= x1; x++)
					if (at(x, y)) {
						if (x < from) from = x;
						if (x > to) to = x;
					}
			if (to - from >= (x1 - x0) * 0.6) full++;
			if (full >= 3) return true;
		}
		return false;
	};

	/** A row of a line of text (much ink across the body), not of an
	 * equation's limits or brackets. */
	const inkAcross = Array.from({ length: height }, (_, y) => {
		let count = 0;
		for (let x = left; x <= right; x++) if (at(x, y)) count++;
		return count;
	});
	const dense = (y: number) => inkAcross[y] > bodyWidth * 0.2;

	/** Rows ``y0``–``y1`` cut at the gap ``gutter`` into stretches across
	 * it (wide) and stretches in two columns. */
	const bandsOf = (y0: number, y1: number, [gutterLeft, gutterRight]: [number, number]) => {
		// Rows crossing the gap are across the page. A few crossing rows
		// alone (a rule, an equation reaching over) are not; a crossing line
		// is whole, its accents and descenders with it.
		// The gap's middle half: a column's lines may reach into its edges
		// (justified to them, or hanging out at a reference's start).
		const inset = Math.max(0, Math.floor((gutterRight - gutterLeft + 1 - 3) / 4));
		const crosses = Array.from({ length: y1 - y0 + 1 }, (_, i) => {
			if (!inRow[y0 + i]) return false;
			for (let x = gutterLeft + inset; x <= gutterRight - inset; x++)
				if (at(x, y0 + i)) return true;
			return false;
		});
		for (const [a, b] of runs(crosses))
			if (b - a + 1 < 4) for (let i = a; i <= b; i++) crosses[i] = false;
		const lastRow = crosses.length - 1;
		for (const [a, b] of runs(crosses)) {
			for (let i = a - 1; i >= Math.max(0, a - LINE_REACH) && inRow[y0 + i]; i--) crosses[i] = true;
			for (let i = b + 1; i <= Math.min(lastRow, b + LINE_REACH) && inRow[y0 + i]; i++)
				crosses[i] = true;
		}
		type Band = { y0: number; y1: number; wide: boolean };
		const bands: Band[] = [];
		const end = crosses.length - 1;
		let i = 0;
		while (i <= end) {
			const wide = crosses[i];
			let stop = i;
			// A wide band runs on over short uncrossing stretches (a figure's
			// own gaps); a column band ends at the next crossing row.
			if (wide) {
				while (stop < end) {
					let next = stop + 1;
					while (next <= end && !crosses[next]) next++;
					if (next > end || next - stop - 1 >= MIN_COLUMNS) break;
					stop = next;
				}
			} else {
				while (stop < end && !crosses[stop + 1]) stop++;
			}
			const last = bands.at(-1);
			const short = stop - i + 1 < MIN_COLUMNS;
			if (!wide && short && last) last.y1 = y0 + stop;
			else if (last && last.wide === (wide || short)) last.y1 = y0 + stop;
			else bands.push({ y0: y0 + i, y1: y0 + stop, wide: wide || short });
			i = stop + 1;
		}
		// Two "columns" of drawing are a figure's panels; two of a few lines,
		// or of lines short of the column (a title's words in large type,
		// equations and their numbers), are not columns either: across the
		// page.
		for (const band of bands)
			if (
				!band.wide &&
				(drawn(left, right, band.y0, band.y1) ||
					!filled(left, gutterLeft - 1, band.y0, band.y1) ||
					!filled(gutterRight + 1, right, band.y0, band.y1))
			)
				band.wide = true;
		const merged = bands.reduce<Band[]>((out, band) => {
			const last = out.at(-1);
			if (last && last.wide === band.wide) last.y1 = band.y1;
			else out.push({ ...band });
			return out;
		}, []);
		// A figure keeps the drawn rows next to it (its top panels standing
		// either side of the columns' gap), up to the first line of text.
		const sketch = (y: number) => inRow[y] && drawn(left, right, y, y);
		merged.forEach((band, i) => {
			if (!band.wide || !drawn(left, right, band.y0, band.y1)) return;
			const above = merged[i - 1];
			if (above && !above.wide) {
				let y = band.y0 - 1;
				while (y > above.y0 && (sketch(y) || (!inRow[y] && sketch(y - 1)))) y--;
				if (y < band.y0 - 1) [band.y0, above.y1] = [y + 1, y];
			}
			const below = merged[i + 1];
			if (below && !below.wide) {
				let y = band.y1 + 1;
				while (y < below.y1 && (sketch(y) || (!inRow[y] && sketch(y + 1)))) y++;
				if (y > band.y1 + 1) [band.y1, below.y0] = [y - 1, y];
			}
		});
		// A part across the page keeps what touches it above and below (a
		// figure's labels, an axis, the short last line of a caption or of
		// the authors), if that is closer to it than to the columns.
		merged.forEach((band, i) => {
			if (!band.wide) return;
			const above = merged[i - 1];
			if (above && !above.wide) {
				const edge = edgeOf(band.y0 - 1, -1, above.y0);
				if (edge !== null) {
					band.y0 = edge;
					above.y1 = edge - 1;
				}
			}
			const below = merged[i + 1];
			if (below && !below.wide) {
				const edge = edgeOf(band.y1 + 1, 1, below.y1);
				if (edge !== null) {
					band.y1 = edge;
					below.y0 = edge + 1;
				}
			}
		});
		// Stretched bands may have reached into each other: none overlaps.
		let last = y0 - 1;
		return merged.filter((band) => {
			band.y0 = Math.max(band.y0, last + 1);
			if (band.y1 < band.y0) return false;
			last = band.y1;
			return true;
		});
	};

	// The page's two columns run on over any blank space. A part across
	// them may have columns of its own (a box beside the abstract above the
	// body's columns); else it is cut into blocks at blank space, each
	// keeping only its own ink: an abstract narrower than the page fills
	// the screen too. A figure's blocks (its panels) stay together.
	type Found = { x0: number; x1: number; y0: number; y1: number; wide: boolean; span?: number };
	const found: Found[] = [];
	let mainSpan = 0;
	const place = (y0: number, y1: number, gutter: [number, number] | null, main: boolean) => {
		const bands = gutter ? bandsOf(y0, y1, gutter) : [{ y0, y1, wide: true }];
		for (const band of bands) {
			if (!band.wide && gutter) {
				const one = extent(left, gutter[0] - 1, band.y0, band.y1);
				const two = extent(gutter[1] + 1, right, band.y0, band.y1);
				if (one && two) {
					// Both columns as wide as the wider: their text alike.
					const span = Math.max(one.x1 - one.x0, two.x1 - two.x0) + 1;
					if (main) mainSpan = Math.max(mainSpan, span);
					found.push({ ...one, wide: false, span }, { ...two, wide: false, span });
					continue;
				}
			}
			if (main && !drawn(left, right, band.y0, band.y1)) {
				const own = gutterOf(band.y0, band.y1);
				if (own && (!gutter || own[1] < gutter[0] || own[0] > gutter[1])) {
					place(band.y0, band.y1, own, false);
					continue;
				}
			}
			const blocks: [number, number][] = [];
			for (const block of joined(runs(inRow, band.y0, band.y1), BLOCK_SPLIT)) {
				const last = blocks.at(-1);
				const figure = (b: [number, number]) => drawn(left, right, b[0], b[1]);
				if (last && block[0] - last[1] - 1 < FIGURE_GAP && (figure(last) || figure(block)))
					last[1] = block[1];
				else blocks.push(block);
			}
			for (const [b0, b1] of blocks) {
				const all = extent(left, right, b0, b1);
				if (all) found.push({ ...all, wide: true });
			}
		}
	};
	place(top, bottom, gutterOf(top, bottom), true);

	// Two columns over a good part of the page, not just a figure with its
	// caption beside it. A part across the page is never shown larger than
	// the columns' text (else the body's).
	const inColumns = found.filter((f) => !f.wide).reduce((sum, f) => sum + f.y1 - f.y0 + 1, 0) / 2;
	const columns = inColumns >= (bottom - top + 1) * 0.3;
	const most =
		mainSpan || Math.max(0, ...found.filter((f) => !f.wide).map((f) => f.span!)) || bodyWidth;
	const pieces = found.map((f): Piece => ({
		x: Math.max(0, f.x0 - pad),
		y: Math.max(0, f.y0 - pad),
		width: Math.min(width, f.x1 + pad + 1) - Math.max(0, f.x0 - pad),
		height: Math.min(height, f.y1 + pad + 1) - Math.max(0, f.y0 - pad),
		wide: f.wide,
		span: (f.wide ? Math.max(f.x1 - f.x0 + 1, most) : f.span!) + 2 * pad
	}));
	return { columns, pieces };
}
