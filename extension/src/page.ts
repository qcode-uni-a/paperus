/** Functions run inside the web page (injected with chrome.scripting): they
 * see what the reader sees, and fetch with the reader's own access (campus
 * network, publisher login). Each must stand alone: no imports, no
 * closures. */

import type { PageLink, ScholarRow } from './extras';

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
		/(?:doi\.org|\/doi(?:\/(?:abs|full|pdf|epdf|pdfdirect|reader))?)\/(10\.\d{4,9}\/[^\s?#"']+)/
	);
	return {
		doi: doi?.[1].replace(/\.pdf$/i, '').replace(/[.,;)]+$/, '') ?? null,
		arxiv: arxiv?.[1] ?? null
	};
}

/** A paper's page (or a PDF), saved at once; else, if it links papers or
 * files, a page that lists them (the popup's choice). A page the
 * extension could not read counts as a paper's: saved from its address. */
export function namesPaper(page: PageInfo | null, url: string): boolean {
	const inUrl = idsInUrl(page?.url ?? url);
	return (
		!page ||
		page.isPdf ||
		!!page.doi ||
		!!page.arxiv ||
		!!page.pdfUrl ||
		page.authors.length > 0 ||
		!!inUrl.doi ||
		!!inUrl.arxiv
	);
}

/** Only the page's DOI and arXiv ID, from its tags (as readPage reads
 * them, without the rest): to mark a paper one has when its page opens. */
export function pageIds(): { doi: string | null; arxiv: string | null } {
	const tags = (selector: string): string[] =>
		[...document.querySelectorAll<HTMLMetaElement>(selector)].map((tag) => tag.content ?? '');
	const doiIn = (text: string): string | null =>
		text.match(/\b(10\.\d{4,9}\/[^\s"']+)/)?.[1]?.replace(/[.,;)]+$/, '') ?? null;
	const named = (...names: string[]): string[] =>
		tags(names.map((name) => `meta[name="${name}" i], meta[property="${name}" i]`).join(', '));
	/** IEEE Xplore's, in no tag: in its script's "xplGlobal.document.metadata={…}". */
	const xplDoi = (): string | null => {
		for (const script of document.querySelectorAll('script:not([src])')) {
			const text = script.textContent ?? '';
			const at = text.search(/xplGlobal\.document\.metadata\s*=\s*\{/);
			if (at < 0) continue;
			return text.slice(at).split('\n')[0].match(/"doi"\s*:\s*"([^"]+)"/)?.[1] ?? null;
		}
		return null;
	};
	return {
		doi:
			[
				...named('citation_doi', 'prism.doi', 'bepress_citation_doi', 'publication_doi'),
				...named('dc.identifier')
			]
				.map(doiIn)
				.find(Boolean) ??
			xplDoi() ??
			null,
		arxiv: named('citation_arxiv_id')[0]?.replace(/\s+/g, ' ').trim() || null
	};
}

/** The paper's details from the page: Highwire/Google Scholar tags
 * (citation_*) and Dublin Core (the address: see idsInUrl). */
export async function readPage(): Promise<PageInfo> {
	// The page's HTML read (not its images and scripts loaded); a page whose
	// scripts hold that up for long has its head (the citation_* tags) read
	// by then all the same.
	if (document.readyState === 'loading')
		await new Promise((done) => {
			document.addEventListener('DOMContentLoaded', () => done(undefined), { once: true });
			setTimeout(done, 10_000);
		});
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
		// Never the supplementary material, which names the DOI too (Science
		// Advances: /doi/suppl/10.1126/…/suppl_file/…_sm.pdf).
		const supplement =
			/\/suppl(?:[_/]|ement)|supplementa|[_/]si(?:[_/.]|$)|_sm\.pdf$|\/mmc\d+\.pdf$|_esm\.pdf$/i;
		/** Lower is likelier the paper: the PDF at /…/pdf/<DOI> (Atypon's
		 * sites: Science, ACS, Taylor & Francis), its reader /…/epdf/<DOI>
		 * (as its PDF), then other links that name the paper. */
		const rank = (href: URL): number => {
			let path = href.pathname.toLowerCase();
			try {
				path = decodeURIComponent(href.pathname).toLowerCase();
			} catch {
				// A malformed link: as it is.
			}
			const id = doi?.toLowerCase();
			if (id && path.replace(/\/$/, '').endsWith(`/pdf/${id}`)) return 0;
			if (id && path.replace(/\/$/, '').endsWith(`/epdf/${id}`)) return 1;
			return 2;
		};
		const own = [...document.querySelectorAll<HTMLAnchorElement>('a[href]')]
			.map((a) => {
				try {
					return new URL(String(a.getAttribute('href')), location.href);
				} catch {
					return null;
				}
			})
			.filter(
				(href): href is URL =>
					href !== null &&
					href.origin === location.origin &&
					href.pathname !== location.pathname &&
					(/\/pdf(\/|$)|\.pdf$|\/pdfft$/i.test(href.pathname) || rank(href) === 1) &&
					!supplement.test(href.pathname) &&
					names(href)
			)
			.map((href) => ({ href, place: rank(href) }))
			// Stable: in the page's order within a rank.
			.sort((a, b) => a.place - b.place)
			.map(({ href, place }) => {
				if (place !== 1) return href;
				// The reader's PDF: /…/epdf/<DOI> → /…/pdf/<DOI> (Wiley's goes on
				// to its download, directPdf).
				const pdf = new URL(href.href);
				pdf.pathname = pdf.pathname.replace(/\/epdf\//i, '/pdf/');
				return pdf;
			})[0];
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
			// One line (ACS's titles break inside the tag).
			const value = tag?.content?.replace(/\s+/g, ' ').trim();
			if (value) return value;
		}
		return null;
	};
	const metas = (name: string): string[] =>
		[...document.querySelectorAll<HTMLMetaElement>(`meta[name="${name}" i]`)]
			.map((tag) => tag.content.replace(/\s+/g, ' ').trim())
			.filter(Boolean);
	const doiIn = (text: string | null): string | null =>
		text?.match(/\b(10\.\d{4,9}\/[^\s"']+)/)?.[1]?.replace(/[.,;)]+$/, '') ?? null;
	/** IEEE Xplore's details, which it has in no citation_* tags: in a
	 * script, as one line "xplGlobal.document.metadata={…};". Only the
	 * paper's fields are read (it also names the reader's institution). */
	const xpl = ((): Record<string, unknown> | null => {
		for (const script of document.querySelectorAll('script:not([src])')) {
			const text = script.textContent ?? '';
			const at = text.search(/xplGlobal\.document\.metadata\s*=\s*\{/);
			if (at < 0) continue;
			const line = text.slice(text.indexOf('{', at)).split('\n')[0].trim();
			try {
				const data: unknown = JSON.parse(line.replace(/;$/, ''));
				return data && typeof data === 'object' ? (data as Record<string, unknown>) : null;
			} catch {
				return null;
			}
		}
		return null;
	})();
	const field = (name: string): string | null => {
		const value = xpl?.[name];
		return typeof value === 'string' && value.trim()
			? value.trim()
			: typeof value === 'number'
				? String(value)
				: null;
	};
	const listedAuthors = xpl?.authors;
	const xplAuthors = Array.isArray(listedAuthors)
		? listedAuthors
				.map((author: unknown) =>
					author && typeof author === 'object' && 'name' in author ? String(author.name) : ''
				)
				.filter(Boolean)
		: [];
	const url = location.href;
	const isPdf = document.contentType === 'application/pdf';
	// Of all dc.Identifier tags, the DOI (Science's first is its own ID).
	const doi =
		doiIn(meta('citation_doi', 'prism.doi', 'bepress_citation_doi', 'publication_doi')) ??
		metas('dc.identifier').map(doiIn).find(Boolean) ??
		doiIn(field('doi'));
	const authors = metas('citation_author').length ? metas('citation_author') : metas('dc.creator');
	return {
		url,
		isPdf,
		// A PDF's title is its file name: none, paperus reads the PDF instead.
		title:
			meta('citation_title', 'dc.title') ??
			field('title') ??
			meta('og:title') ??
			(isPdf ? null : document.title || null),
		doi,
		arxiv: meta('citation_arxiv_id'),
		// IEEE's: /stamp/stamp.jsp?…, a page with the PDF in a frame (fetchPdf).
		pdfUrl: pdfOf(meta('citation_pdf_url') ?? field('pdfUrl'), doi),
		authors: authors.length ? authors : xplAuthors,
		date:
			meta('citation_publication_date', 'citation_date', 'citation_online_date', 'dc.date') ??
			field('publicationDate'),
		journal:
			meta('citation_journal_title', 'citation_conference_title', 'prism.publicationName') ??
			field('publicationTitle'),
		volume: meta('citation_volume', 'prism.volume') ?? field('volume'),
		issue: meta('citation_issue', 'prism.number') ?? field('issue'),
		firstPage: meta('citation_firstpage', 'prism.startingPage') ?? field('startPage'),
		lastPage: meta('citation_lastpage', 'prism.endingPage') ?? field('endPage'),
		publisher: meta('citation_publisher', 'dc.publisher') ?? field('publisher'),
		abstract: meta('citation_abstract', 'dc.description') ?? field('abstract') ?? meta('description')
	};
}

/** The PDF, fetched from the page with the reader's access; as base64
 * (results travel as JSON). Otherwise why not: the answer's status and,
 * for a web page (a login, a robot check), its beginning. */
export async function fetchPdf(
	url: string,
	maxBytes: number
): Promise<
	| { base64: string; size: number; name?: string }
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
		// a link in its message; IEEE's: a frame): followed once.
		if ((response.headers.get('content-type') ?? '').includes('text/html')) {
			const html = await response.clone().text();
			const refresh =
				html.match(/<meta[^>]+http-equiv=["']?refresh["']?[^>]*content=["']?\s*\d+\s*;\s*url=([^"'>]+)/i) ??
				html.match(/<meta[^>]+content=["']?\s*\d+\s*;\s*url=([^"'>]+)["']?[^>]*http-equiv=["']?refresh/i) ??
				html.match(/id=["']redirect-message["'][\s\S]{0,500}?href=["']([^"']+)/i) ??
				html.match(/(?:window\.)?location(?:\.href)?\s*=\s*["']([^"']+\.pdf[^"']*)["']/i) ??
				html.match(/location\.replace\(\s*["']([^"']+)["']\s*\)/i) ??
				// The PDF in a frame (IEEE's stamp.jsp: …/stampPDF/getPDF.jsp?…).
				html.match(/<(?:iframe|embed)\b[^>]*\bsrc=["']([^"']*(?:\.pdf\b|getPDF\.jsp)[^"']*)["']/i);
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
		// The name the site gives it (arXiv's says its version: "2401.12345v3.pdf").
		const name = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(
			response.headers.get('content-disposition') ?? ''
		)?.[1];
		return { base64: btoa(binary), size: buffer.byteLength, ...(name ? { name } : {}) };
	} catch (error) {
		return { error: `The PDF could not be fetched: ${String(error)}` };
	}
}

/** Every link of the article with what is around it, for finding its
 * supplementary material, code and data (extras.ts decides): the heading
 * of its section (the last heading before it), the sentence or item it
 * sits in, and whether it is in the abstract (arXiv's comments too). Not
 * the site's header, footer and menus. */
export function pageLinks(): PageLink[] {
	const headings = [...document.querySelectorAll('h1, h2, h3, h4, h5, h6')];
	/** The last heading before the link, in the page's order. */
	const headingOf = (link: Element): string => {
		let low = 0;
		let high = headings.length - 1;
		let found = -1;
		while (low <= high) {
			const middle = (low + high) >> 1;
			if (headings[middle].compareDocumentPosition(link) & Node.DOCUMENT_POSITION_FOLLOWING) {
				found = middle;
				low = middle + 1;
			} else high = middle - 1;
		}
		return found < 0 ? '' : (headings[found].textContent ?? '').trim().slice(0, 200);
	};
	const found: PageLink[] = [];
	const seen = new Set<string>();
	for (const link of [...document.querySelectorAll('a[href]')].slice(0, 5000)) {
		if (link.closest('header, footer, nav, [role="banner"], [role="contentinfo"], [role="navigation"]'))
			continue;
		let url: URL;
		try {
			url = new URL(String(link.getAttribute('href')), location.href);
		} catch {
			continue;
		}
		if (url.protocol !== 'https:' && url.protocol !== 'http:') continue;
		url.hash = '';
		if (seen.has(url.href)) continue;
		seen.add(url.href);
		found.push({
			url: url.href,
			text: (link.textContent ?? '').trim().slice(0, 200),
			heading: headingOf(link),
			context: (link.closest('p, li, dd, td, figcaption')?.textContent ?? '').trim().slice(0, 600),
			abstract: !!link.closest(
				'blockquote.abstract, .abstract, #abstract, [id^="abstract" i], [class*="abstract" i], td.comments'
			)
		});
	}
	return found;
}

/** A Google Scholar profile's papers, all of them: those shown, then the
 * rest a hundred at a time (as "Show more" does), a second apart, at most
 * a thousand. */
export async function scholarProfile(): Promise<{ name: string; rows: ScholarRow[] }> {
	const rowsOf = (page: Document): ScholarRow[] =>
		[...page.querySelectorAll('tr.gsc_a_tr')].map((row) => {
			const link = row.querySelector<HTMLAnchorElement>('a.gsc_a_at');
			const gray = row.querySelectorAll('.gs_gray');
			let url = '';
			try {
				url = new URL(link?.getAttribute('href') ?? '', location.href).href;
			} catch {
				// No link.
			}
			return {
				title: (link?.textContent ?? '').trim(),
				authors: (gray[0]?.textContent ?? '').trim(),
				venue: (gray[1]?.firstChild?.textContent ?? gray[1]?.textContent ?? '').trim(),
				year: (row.querySelector('.gsc_a_y span, .gsc_a_h')?.textContent ?? '').trim(),
				url
			};
		});
	const rows = rowsOf(document);
	const name = (document.querySelector('#gsc_prf_in')?.textContent ?? '').trim();
	const more = document.querySelector<HTMLButtonElement>('#gsc_bpf_more');
	if (!more || more.disabled) return { name, rows };
	for (let start = rows.length; start < 1000; start += 100) {
		await new Promise((done) => setTimeout(done, 1000));
		const next = new URL(location.href);
		next.searchParams.set('cstart', String(start));
		next.searchParams.set('pagesize', '100');
		const response = await fetch(next, { credentials: 'include' });
		if (!response.ok) break;
		const page = new DOMParser().parseFromString(await response.text(), 'text/html');
		const found = rowsOf(page);
		rows.push(...found);
		if (found.length < 100) break;
	}
	return { name, rows };
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
