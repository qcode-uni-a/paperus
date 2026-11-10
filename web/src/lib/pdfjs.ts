import { resolve } from '$app/paths';
import type { DocumentInitParameters } from 'pdfjs-dist/types/src/display/api';

/** Where pdf.js finds its own files (scripts/pdfjs-assets.js copies them):
 * without them, scans with JBIG2 or JPEG 2000 images stay blank, and
 * fonts a PDF does not embed are guessed. */
export function pdfFiles(): DocumentInitParameters {
	const root = `${resolve('/').replace(/\/$/, '')}/pdfjs`;
	return {
		wasmUrl: `${root}/wasm/`,
		cMapUrl: `${root}/cmaps/`,
		cMapPacked: true,
		standardFontDataUrl: `${root}/standard_fonts/`,
		iccUrl: `${root}/iccs/`
	};
}
