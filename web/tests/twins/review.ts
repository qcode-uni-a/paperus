/** Look over the layout twins: each drawn with fluent mode's pieces
 * (numbered in reading order) and its lines (green: read in order, red:
 * not, grey: running header or footer), into ``OUT/index.html``.
 *
 *     node tests/twins/review.ts OUT [--accept] [NAME ...]
 *
 * ``--accept``: take the order and the columns read now as the twins'
 * expected ones (once the drawing shows them right). */

import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createCanvas } from '@napi-rs/canvas';
import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs';
import { analysePage } from '../../src/lib/pageAnalysis.ts';
import { check, middle, type Spec } from './check.ts';

const HERE = import.meta.dirname;
const SCALE = 1.4;

const args = process.argv.slice(2);
const out = args.shift()!;
const accept = args.includes('--accept');
const wanted = args.filter((a) => a !== '--accept');
execFileSync('python3', [join(HERE, 'twins.py'), out, ...wanted]);

const cards: string[] = [];
for (const file of readdirSync(join(HERE, 'pages')).sort()) {
	const path = join(HERE, 'pages', file);
	const spec = JSON.parse(readFileSync(path, 'utf8')) as Spec;
	if (wanted.length && !wanted.includes(spec.name)) continue;
	const task = getDocument({
		data: new Uint8Array(readFileSync(join(out, `${spec.name}.pdf`))),
		verbosity: 0
	});
	const doc = await task.promise;
	const page = await doc.getPage(1);
	const make = (w: number, h: number) => createCanvas(w, h) as unknown as HTMLCanvasElement;
	const { layout } = await analysePage(page, make, spec.first);
	const { problems, pieceOf } = check(spec, layout);

	if (accept && !spec.todo) {
		// Kept "headers or footers" away from the page's very edge: a figure's
		// labels, footnotes, lines of an equation the measuring took for them.
		const [, height] = spec.size;
		spec.lines.forEach((line, i) => {
			if (line.role !== 'furniture' || pieceOf[i] < 0) return;
			if (line.box[1] < height * 0.04 || line.box[3] > height * 0.96) return;
			const [x, y] = middle(line.box);
			const inFigure = spec.figures.some(
				({ box: [x0, y0, x1, y1] }) => x >= x0 - 4 && x <= x1 + 4 && y >= y0 - 4 && y <= y1 + 4
			);
			line.role = inFigure ? 'figure' : 'body';
		});
		const body = spec.lines
			.map((line, i) => ({ line, piece: pieceOf[i] }))
			.filter(({ line }) => line.role === 'body')
			.sort(
				(a, b) =>
					(a.piece < 0 ? 1e9 : a.piece) - (b.piece < 0 ? 1e9 : b.piece) ||
					middle(a.line.box)[1] - middle(b.line.box)[1] ||
					middle(a.line.box)[0] - middle(b.line.box)[0]
			);
		// Lines left out at the page's top or bottom edge: a header or a
		// footer the measuring missed.
		const edge = (line: Spec['lines'][number]) =>
			line.box[3] < spec.size[1] * 0.12 || line.box[1] > spec.size[1] * 0.88;
		let order = 0;
		for (const { line, piece } of body) {
			if (piece < 0 && edge(line)) {
				line.role = 'furniture';
				delete line.order;
			} else line.order = order++;
		}
		spec.columns = layout.columns;
		// A figure fluent mode divides: its parts, each whole in one piece.
		for (const figure of spec.figures) {
			const [x0, y0, x1, y1] = figure.box;
			const parts = layout.pieces
				.map((p): [number, number, number, number] => [
					Math.max(x0, p.x),
					Math.max(y0, p.y),
					Math.min(x1, p.x + p.width),
					Math.min(y1, p.y + p.height)
				])
				.filter(
					([a, b, c, d]) => c > a && d > b && (c - a) * (d - b) > (x1 - x0) * (y1 - y0) * 0.05
				)
				.map((box) => box.map((v) => Math.round(v * 10) / 10) as [number, number, number, number]);
			// Divided, or partly left out (a cover's picture reaching into the
			// margin): what is shown, each part whole.
			const shown = parts.reduce((sum, [a, b, c, d]) => sum + (c - a) * (d - b), 0);
			if (parts.length > 1 || shown < (x1 - x0) * (y1 - y0) * 0.9) figure.parts = parts;
			else delete figure.parts;
		}
		writeFileSync(path, JSON.stringify(spec, null, 1) + '\n');
	}

	// The twin, its pieces and its lines.
	const viewport = page.getViewport({ scale: SCALE });
	const canvas = createCanvas(Math.ceil(viewport.width), Math.ceil(viewport.height));
	const context = canvas.getContext('2d');
	await page.render({ canvas: canvas as unknown as HTMLCanvasElement, viewport }).promise;
	const order = new Map<number, boolean>();
	const read = spec.lines
		.map((line, i) => ({ line, piece: pieceOf[i] }))
		.filter(({ line, piece }) => line.role === 'body' && piece >= 0)
		.sort(
			(a, b) =>
				a.piece - b.piece ||
				middle(a.line.box)[1] - middle(b.line.box)[1] ||
				middle(a.line.box)[0] - middle(b.line.box)[0]
		);
	let highest = -1;
	for (const { line } of read) {
		order.set(line.order!, line.order! > highest);
		highest = Math.max(highest, line.order!);
	}
	spec.lines.forEach((line, i) => {
		const [x0, y0, x1, y1] = line.box.map((v) => v * SCALE);
		context.fillStyle =
			line.role === 'furniture'
				? pieceOf[i] >= 0
					? 'rgba(220,0,0,0.45)'
					: 'rgba(120,120,120,0.35)'
				: line.role === 'figure'
					? 'rgba(0,0,0,0)'
					: pieceOf[i] < 0 || !order.get(line.order!)
						? 'rgba(220,0,0,0.45)'
						: 'rgba(0,160,60,0.25)';
		context.fillRect(x0, y0, x1 - x0, y1 - y0);
	});
	layout.pieces.forEach((p, i) => {
		context.strokeStyle = p.wide ? '#7a3cff' : '#0060df';
		context.lineWidth = 2;
		context.strokeRect(p.x * SCALE, p.y * SCALE, p.width * SCALE, p.height * SCALE);
		context.fillStyle = context.strokeStyle;
		context.fillRect(p.x * SCALE, p.y * SCALE, 22, 18);
		context.fillStyle = 'white';
		context.font = 'bold 13px sans-serif';
		context.fillText(String(i + 1), p.x * SCALE + 4, p.y * SCALE + 14);
	});
	writeFileSync(join(out, `${spec.name}.png`), canvas.toBuffer('image/png'));
	cards.push(
		`<section><h2>${spec.name}</h2><p>${spec.source}</p>` +
			`<p class="${problems.length ? 'bad' : 'good'}">${problems.length ? problems.join('<br>') : 'All right'}</p>` +
			`<img src="${spec.name}.png" width="${Math.round(viewport.width / 2)}"></section>`
	);
	await task.destroy();
}
writeFileSync(
	join(out, 'index.html'),
	`<!doctype html><meta charset="utf-8"><title>Layout twins</title><style>
body{font:14px system-ui;margin:24px;background:#f4f5f7}section{display:inline-block;vertical-align:top;margin:0 16px 24px 0;background:white;padding:12px;border-radius:8px;max-width:440px}
h2{font-size:15px;margin:0}.bad{color:#b00020}.good{color:#0a7a3a}img{border:1px solid #ddd}</style>${cards.join('')}`
);
console.log(`${cards.length} twins: ${join(out, 'index.html')}`);
