/** Small PDFs with real text (one font, one text block per page), made in
 * the test: each test gets its own words, so its paper is found by them
 * and is not a duplicate of another test's. A port of server/tests/pdfs.py. */

function escape(text: string): string {
	return text.replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)');
}

/** A PDF with one page per entry (each a list of text lines) and, if
 * given, a title in its document information (paperus uses it as the
 * paper's title when nothing better is found). */
export function makePdf(pages: string[][], title?: string): Buffer {
	return makePdfFrom(
		pages.map((lines) => {
			const text = lines.map((line) => `(${escape(line)}) Tj T* `).join('');
			return `BT /F1 11 Tf 14 TL 72 720 Td ${text}ET`;
		}),
		title
	);
}

/** A PDF of one page per content stream, in Helvetica (``/F1``);
 * ``annotations``: per page, annotation dictionaries (``{page N}`` in
 * them names page N's object). */
function makePdfFrom(streams: string[], title?: string, annotations: string[][] = []): Buffer {
	const objects: string[] = [];
	const kids = streams.map((_, i) => `${4 + 2 * i} 0 R`).join(' ');
	// Annotations come after the pages, numbered in order.
	let next = 4 + 2 * streams.length;
	const annotationIds = streams.map((_, i) => (annotations[i] ?? []).map(() => next++));
	objects.push('<< /Type /Catalog /Pages 2 0 R >>');
	objects.push(`<< /Type /Pages /Kids [${kids}] /Count ${streams.length} >>`);
	objects.push('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');
	streams.forEach((stream, i) => {
		const content = 4 + 2 * i + 1;
		const annots = annotationIds[i].length
			? ` /Annots [${annotationIds[i].map((id) => `${id} 0 R`).join(' ')}]`
			: '';
		objects.push(
			'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]' +
				` /Resources << /Font << /F1 3 0 R >> >> /Contents ${content} 0 R${annots} >>`
		);
		objects.push(
			`<< /Length ${Buffer.byteLength(stream, 'latin1')} >>\nstream\n${stream}\nendstream`
		);
	});
	for (const page of annotations)
		for (const body of page)
			objects.push(body.replace(/\{page (\d+)\}/g, (_, n) => `${4 + 2 * (Number(n) - 1)} 0 R`));
	let info = '';
	if (title !== undefined) {
		objects.push(`<< /Title (${escape(title)}) >>`);
		info = ` /Info ${objects.length} 0 R`;
	}

	let out = '%PDF-1.4\n';
	const offsets: number[] = [];
	objects.forEach((body, i) => {
		offsets.push(Buffer.byteLength(out, 'latin1'));
		out += `${i + 1} 0 obj\n${body}\nendobj\n`;
	});
	const xref = Buffer.byteLength(out, 'latin1');
	out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
	for (const offset of offsets) out += `${String(offset).padStart(10, '0')} 00000 n \n`;
	out += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R${info} >>\nstartxref\n${xref}\n%%EOF\n`;
	return Buffer.from(out, 'latin1');
}

/** A line of text placed on a page (PDF points from the lower left). */
export type Placed = { x: number; y: number; text: string; size?: number };

/** A PDF of placed lines and horizontal rules ([x1, x2, y]), one page per
 * entry: for layouts such as two columns under a running header. */
export function makeLayoutPdf(
	pages: { lines: Placed[]; rules?: [number, number, number][] }[],
	title?: string
): Buffer {
	return makePdfFrom(
		pages.map(({ lines, rules = [] }) => {
			const text = lines
				.map(
					({ x, y, text: words, size = 10 }) =>
						`BT /F1 ${size} Tf ${x} ${y} Td (${escape(words)}) Tj ET `
				)
				.join('');
			const drawn = rules.map(([x1, x2, y]) => `${x1} ${y} m ${x2} ${y} l S `).join('');
			return `0.6 w ${drawn}${text}`;
		}),
		title
	);
}

/** Two pages, the first with links: to the second page (a place in the
 * paper), to a web page, and one with a script for an address (never a
 * link). */
export function makeLinkedPdf(title: string, word: string): Buffer {
	const text = (lines: [number, string][]) =>
		lines.map(([y, line]) => `BT /F1 11 Tf 72 ${y} Td (${escape(line)}) Tj ET `).join('');
	const link = (y: number, action: string) =>
		`<< /Type /Annot /Subtype /Link /Rect [70 ${y - 3} 300 ${y + 11}] /Border [0 0 0] ${action} >>`;
	return makePdfFrom(
		[
			text([
				[720, title],
				[690, `Abstract. We study the ${word} effect in libraries.`],
				[660, 'See the results on page 2'],
				[640, 'The paper online'],
				[620, 'Not a link']
			]),
			text([
				[700, 'Results'],
				[680, `The ${word} effect is real and measurable.`]
			])
		],
		title,
		[
			[
				link(660, '/Dest [{page 2} /XYZ 72 712 null]'),
				link(640, '/A << /S /URI /URI (https://example.org/paper) >>'),
				link(620, '/A << /S /URI /URI (javascript:alert\\(1\\)) >>')
			]
		]
	);
}
