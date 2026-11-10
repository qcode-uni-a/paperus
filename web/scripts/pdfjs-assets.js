// pdf.js's own files, which it loads when a PDF needs them: the decoders
// for JBIG2 and JPEG 2000 images (most scans), the standard fonts a PDF
// may use without embedding them, the character maps for Chinese, Japanese
// and Korean text, and colour profiles. Copied from pdfjs-dist into
// static/pdfjs/ (not checked in) before every build and start
// (src/lib/pdfjs.ts names them).
import { cpSync, rmSync } from 'node:fs';

const from = new URL('../node_modules/pdfjs-dist/', import.meta.url);
const to = new URL('../static/pdfjs/', import.meta.url);
rmSync(to, { recursive: true, force: true });
for (const folder of ['wasm', 'cmaps', 'standard_fonts', 'iccs']) {
	cpSync(new URL(folder, from), new URL(folder, to), {
		recursive: true,
		// Not needed: scripts inside PDFs are not run. Left out: the
		// Liberation fonts (GPL-2.0 with a font exception, unlike all else
		// paperus ships); pdf.js draws Helvetica and Arial with the browser's
		// sans-serif instead, as without these files.
		filter: (source) => !/quickjs|liberation/i.test(source)
	});
}
