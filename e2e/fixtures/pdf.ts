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
	const objects: string[] = [];
	const kids = pages.map((_, i) => `${4 + 2 * i} 0 R`).join(' ');
	objects.push('<< /Type /Catalog /Pages 2 0 R >>');
	objects.push(`<< /Type /Pages /Kids [${kids}] /Count ${pages.length} >>`);
	objects.push('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');
	pages.forEach((lines, i) => {
		const content = 4 + 2 * i + 1;
		objects.push(
			'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]' +
				` /Resources << /Font << /F1 3 0 R >> >> /Contents ${content} 0 R >>`
		);
		const text = lines.map((line) => `(${escape(line)}) Tj T* `).join('');
		const stream = `BT /F1 11 Tf 14 TL 72 720 Td ${text}ET`;
		objects.push(
			`<< /Length ${Buffer.byteLength(stream, 'latin1')} >>\nstream\n${stream}\nendstream`
		);
	});
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
