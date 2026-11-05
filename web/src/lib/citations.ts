/** Citation export (BibTeX, CSL-JSON) from /api/citations. */

export type CitationFormat = 'bibtex' | 'csl-json';

export function citationUrl(
	what: { items?: string[]; collection?: string; nested?: boolean },
	format: CitationFormat = 'bibtex',
	download = false
): string {
	const params = new URLSearchParams({ format });
	for (const id of what.items ?? []) params.append('item', id);
	if (what.collection) params.set('collection', what.collection);
	if (what.nested === false) params.set('nested', 'false');
	if (download) params.set('download', 'true');
	return `/api/citations?${params}`;
}

/** Starts the download of a .bib or .json file (the server says attachment). */
export function downloadCitations(...args: Parameters<typeof citationUrl>) {
	const [what, format] = args;
	location.href = citationUrl(what, format, true);
}

/** Copies the citations; false if the browser does not allow it (only over
 * HTTPS or on localhost), in which case they open in a new tab instead. */
export async function copyCitations(
	what: Parameters<typeof citationUrl>[0],
	format: CitationFormat = 'bibtex'
): Promise<boolean> {
	const url = citationUrl(what, format);
	try {
		// Safari wants the clipboard write to start within the click.
		await navigator.clipboard.write([
			new ClipboardItem({
				// As plain text (some browsers refuse other types); an error page
				// must not end up on the clipboard.
				'text/plain': fetch(url, { credentials: 'same-origin' }).then(async (r) => {
					if (!r.ok) throw new Error(`${r.status}`);
					return new Blob([await r.text()], { type: 'text/plain' });
				})
			})
		]);
		return true;
	} catch {
		window.open(url, '_blank', 'noopener');
		return false;
	}
}
