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
export async function readPage(): Promise<PageInfo> {
	// The page's HTML read (not its images and scripts loaded).
	if (document.readyState === 'loading')
		await new Promise((done) =>
			document.addEventListener('DOMContentLoaded', () => done(undefined), { once: true })
		);
	/** Where to fetch the PDF from within the page: its citation_pdf_url,
	 * over HTTPS on an HTTPS page (else the browser blocks it); if that is
	 * another site (APS: link.aps.org, which the page may not fetch from),
	 * the page's own link to the PDF with the paper's DOI, if it has one. */
	const pdfOf = (link: string | null, doi: string | null): string | null => {
		// The page's own links to the PDF of this paper: they name its DOI
		// (APS: /prb/pdf/10.1103/…) or the article's id in the page's address
		// (ScienceDirect: …/pii/S0010…/pdfft?…, as it names no
		// citation_pdf_url); never just any PDF the page links.
		const article = location.pathname.split('/').filter(Boolean).at(-1) ?? '';
		const names = (href: URL) => {
			let path = href.pathname.toLowerCase();
			try {
				path = decodeURIComponent(href.pathname).toLowerCase();
			} catch {
				// A malformed link: as it is.
			}
			return (
				(!!doi && path.includes(doi.toLowerCase())) ||
				(article.length >= 8 && path.includes(article.toLowerCase()))
			);
		};
		const own = [...document.querySelectorAll<HTMLAnchorElement>('a[href]')]
			.map((a) => {
				try {
					return new URL(String(a.getAttribute('href')), location.href);
				} catch {
					return null;
				}
			})
			.filter((href): href is URL => href !== null)
			.find(
				(href) =>
					href.origin === location.origin &&
					href.pathname !== location.pathname &&
					/\/pdf(\/|$)|\.pdf$|\/pdfft$/i.test(href.pathname) &&
					names(href)
			);
		if (!link) return own?.href ?? null;
		const pdf = new URL(link, location.href);
		if (pdf.protocol === 'http:' && location.protocol === 'https:') pdf.protocol = 'https:';
		return pdf.origin === location.origin ? pdf.href : (own ?? pdf).href;
	};
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
	const doi = doiIn(meta('citation_doi', 'dc.identifier', 'prism.doi', 'bepress_citation_doi'));
	return {
		url,
		isPdf,
		// A PDF's title is its file name: none, paperus reads the PDF instead.
		title: meta('citation_title', 'dc.title', 'og:title') ?? (isPdf ? null : document.title || null),
		doi,
		arxiv: meta('citation_arxiv_id'),
		pdfUrl: pdfOf(meta('citation_pdf_url'), doi),
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
 * (results travel as JSON). Otherwise why not: the answer's status and,
 * for a web page (a login, a robot check), its beginning. */
export async function fetchPdf(
	url: string,
	maxBytes: number
): Promise<
	| { base64: string; size: number }
	| { error: string; status?: number; html?: string; next?: string; at?: string }
> {
	try {
		let response: Response;
		try {
			response = await fetch(url, { credentials: 'include', signal: AbortSignal.timeout(60_000) });
		} catch (error) {
			// The browser let the page not fetch it (a redirect to another
			// site, as AIP's PDFs go to Silverchair's signed addresses): the
			// extension may.
			return { error: `The PDF could not be fetched: ${String(error)}`, next: url };
		}
		// A page in between that sends the browser on to the PDF
		// (ScienceDirect's "pdfft": a refresh to its PDF's signed address, or
		// a link in its message): followed once.
		if ((response.headers.get('content-type') ?? '').includes('text/html')) {
			const html = await response.clone().text();
			const refresh =
				html.match(/<meta[^>]+http-equiv=["']?refresh["']?[^>]*content=["']?\s*\d+\s*;\s*url=([^"'>]+)/i) ??
				html.match(/<meta[^>]+content=["']?\s*\d+\s*;\s*url=([^"'>]+)["']?[^>]*http-equiv=["']?refresh/i) ??
				html.match(/id=["']redirect-message["'][\s\S]{0,500}?href=["']([^"']+)/i) ??
				html.match(/(?:window\.)?location(?:\.href)?\s*=\s*["']([^"']+\.pdf[^"']*)["']/i) ??
				html.match(/location\.replace\(\s*["']([^"']+)["']\s*\)/i);
			if (refresh) {
				const next = new URL(refresh[1].replace(/&amp;/g, '&').trim(), response.url).href;
				try {
					response = await fetch(next, { credentials: 'include', signal: AbortSignal.timeout(60_000) });
				} catch (error) {
					// Another site the page may not fetch from: the extension may.
					return { error: `The PDF could not be fetched: ${String(error)}`, next };
				}
			}
		}
		const buffer = await response.arrayBuffer();
		// Views on the buffer, never .slice() or .subarray(): in some pages
		// (Nature's) Firefox refuses those their "constructor".
		const part = (start: number, length: number) =>
			new Uint8Array(buffer, start, Math.max(0, Math.min(length, buffer.byteLength - start)));
		const head = String.fromCharCode.apply(null, Array.from(part(0, 5)));
		if (!response.ok || head !== '%PDF-') {
			const html = new TextDecoder().decode(part(0, 100_000));
			return {
				error: response.ok
					? 'The PDF link gave a web page, not a PDF.'
					: `The PDF link answered ${response.status}.`,
				status: response.status,
				html,
				// Where it ended up, to say what came back.
				at: response.url
			};
		}
		if (buffer.byteLength > maxBytes) return { error: 'The PDF is larger than paperus takes.' };
		let binary = '';
		for (let i = 0; i < buffer.byteLength; i += 0x8000) {
			binary += String.fromCharCode.apply(null, Array.from(part(i, 0x8000)));
		}
		return { base64: btoa(binary), size: buffer.byteLength };
	} catch (error) {
		return { error: `The PDF could not be fetched: ${String(error)}` };
	}
}

/** What the page shows, for telling why it gave no PDF (see causes.ts). */
export function pageSignals(): {
	title: string;
	text: string;
	captcha: boolean;
	password: boolean;
} {
	return {
		title: document.title,
		// Its words, without laying out the page (innerText would, slowly
		// on a long article): text nodes outside scripts and styles, up to
		// what is looked at.
		text: (() => {
			const parts: string[] = [];
			let length = 0;
			const walker = document.createTreeWalker(document.body ?? document.documentElement, NodeFilter.SHOW_TEXT, {
				acceptNode: (node) =>
					node.parentElement?.closest('script, style, noscript, template')
						? NodeFilter.FILTER_REJECT
						: NodeFilter.FILTER_ACCEPT
			});
			for (let node = walker.nextNode(); node && length < 20000; node = walker.nextNode()) {
				const words = node.nodeValue?.trim();
				if (!words) continue;
				parts.push(words);
				length += words.length + 1;
			}
			return parts.join(' ').slice(0, 20000);
		})(),
		captcha: !!document.querySelector(
			'.g-recaptcha, .h-captcha, .cf-turnstile, #challenge-form, #challenge-running, ' +
				'iframe[src*="captcha"], iframe[src*="challenges.cloudflare.com"], #px-captcha, ' +
				'iframe[src*="captcha-delivery.com"]'
		),
		password: !!document.querySelector('input[type="password"]')
	};
}

/** A small note in the page's corner: saved, or what went wrong. */
export function showNote(
	text: string,
	link: string | null,
	outcome: 'ok' | 'warning' | 'error'
): void {
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
			`border-left:4px solid ${{ ok: '#2338a8', warning: '#b26a00', error: '#c0392b' }[outcome]}`
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
	setTimeout(() => host.remove(), outcome === 'ok' ? 6000 : 12000);
}
