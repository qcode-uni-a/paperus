/** Functions run inside the web page (injected with chrome.scripting): they
 * see what the reader sees, and fetch with the reader's own access (campus
 * network, publisher login). Each must stand alone: no imports, no
 * closures. */

export interface PageInfo {
	url: string;
	isPdf: boolean;
	title: string | null;
	doi: string | null;
	arxiv: string | null;
	pdfUrl: string | null;
	authors: string[];
	date: string | null;
	journal: string | null;
	volume: string | null;
	issue: string | null;
	firstPage: string | null;
	lastPage: string | null;
	publisher: string | null;
	abstract: string | null;
}

/** A DOI or arXiv ID in an address: arxiv.org/abs/…, arxiv.org/pdf/…,
 * doi.org/10.…, a publisher's /doi/pdf/10.…. */
export function idsInUrl(url: string): { doi: string | null; arxiv: string | null } {
	let text = url;
	try {
		text = decodeURIComponent(url);
	} catch {
		// Left as it is.
	}
	const arxiv = text.match(/arxiv\.org\/(?:abs|pdf|html)\/([^?#/]+?)(?:v\d+)?(?:\.pdf)?(?:[?#]|$)/);
	const doi = text.match(
		/(?:doi\.org|\/doi(?:\/(?:abs|full|pdf|epdf|pdfdirect|reader))?)\/(10\.\d{4,9}\/[^\s?#"'<>]+)/
	);
	return {
		doi: doi?.[1].replace(/\.pdf$/i, '').replace(/[.,;)]+$/, '') ?? null,
		arxiv: arxiv?.[1] ?? null
	};
}

/** The paper's details from the page: Highwire/Google Scholar tags
 * (citation_*) and Dublin Core (the address: see idsInUrl). */
export function readPage(): PageInfo {
	const meta = (...names: string[]): string | null => {
		for (const name of names) {
			const tag = document.querySelector<HTMLMetaElement>(
				`meta[name="${name}" i], meta[property="${name}" i]`
			);
			const value = tag?.content?.trim();
			if (value) return value;
		}
		return null;
	};
	const metas = (name: string): string[] =>
		[...document.querySelectorAll<HTMLMetaElement>(`meta[name="${name}" i]`)]
			.map((tag) => tag.content.trim())
			.filter(Boolean);
	const doiIn = (text: string | null): string | null =>
		text?.match(/\b(10\.\d{4,9}\/[^\s"'<>]+)/)?.[1]?.replace(/[.,;)]+$/, '') ?? null;
	const url = location.href;
	const isPdf = document.contentType === 'application/pdf';
	const pdfLink = meta('citation_pdf_url');
	return {
		url,
		isPdf,
		// A PDF's title is its file name: none, paperus reads the PDF instead.
		title: meta('citation_title', 'dc.title', 'og:title') ?? (isPdf ? null : document.title || null),
		doi: doiIn(meta('citation_doi', 'dc.identifier', 'prism.doi', 'bepress_citation_doi')),
		arxiv: meta('citation_arxiv_id'),
		pdfUrl: pdfLink ? new URL(pdfLink, url).href : null,
		authors: metas('citation_author').length ? metas('citation_author') : metas('dc.creator'),
		date: meta('citation_publication_date', 'citation_date', 'citation_online_date', 'dc.date'),
		journal: meta('citation_journal_title', 'citation_conference_title', 'prism.publicationName'),
		volume: meta('citation_volume', 'prism.volume'),
		issue: meta('citation_issue', 'prism.number'),
		firstPage: meta('citation_firstpage', 'prism.startingPage'),
		lastPage: meta('citation_lastpage', 'prism.endingPage'),
		publisher: meta('citation_publisher', 'dc.publisher'),
		abstract: meta('citation_abstract', 'dc.description', 'description')
	};
}

/** The PDF, fetched from the page with the reader's access; as base64
 * (results travel as JSON). Null if it is not a PDF (e.g. a login page). */
export async function fetchPdf(
	url: string,
	maxBytes: number
): Promise<{ base64: string; size: number } | { error: string }> {
	try {
		const response = await fetch(url, { credentials: 'include' });
		if (!response.ok) return { error: `The PDF link answered ${response.status}.` };
		const buffer = await response.arrayBuffer();
		if (buffer.byteLength > maxBytes) return { error: 'The PDF is larger than paperus takes.' };
		const bytes = new Uint8Array(buffer);
		const head = String.fromCharCode(...bytes.slice(0, 5));
		if (head !== '%PDF-') return { error: 'The PDF link gave a web page (a login?), not a PDF.' };
		let binary = '';
		for (let i = 0; i < bytes.length; i += 0x8000) {
			binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
		}
		return { base64: btoa(binary), size: bytes.length };
	} catch (error) {
		return { error: `The PDF could not be fetched: ${String(error)}` };
	}
}

/** A small note in the page's corner: saved, or what went wrong. */
export function showNote(text: string, link: string | null, ok: boolean): void {
	document.getElementById('paperus-note')?.remove();
	const host = document.createElement('div');
	host.id = 'paperus-note';
	const shadow = host.attachShadow({ mode: 'closed' });
	const box = document.createElement('div');
	box.setAttribute(
		'style',
		[
			'position:fixed',
			'right:16px',
			'bottom:16px',
			'z-index:2147483647',
			'max-width:360px',
			'padding:12px 16px',
			'border-radius:12px',
			'background:#fff',
			'color:#1b2440',
			'font:14px/1.4 system-ui,sans-serif',
			'box-shadow:0 6px 24px rgba(27,36,64,.25)',
			`border-left:4px solid ${ok ? '#2338a8' : '#c0392b'}`
		].join(';')
	);
	box.textContent = text;
	if (link) {
		const a = document.createElement('a');
		a.href = link;
		a.target = '_blank';
		a.textContent = ' Open in paperus';
		a.setAttribute('style', 'color:#2338a8;font-weight:600;margin-left:4px');
		box.append(a);
	}
	shadow.append(box);
	document.documentElement.append(host);
	setTimeout(() => host.remove(), ok ? 6000 : 12000);
}
