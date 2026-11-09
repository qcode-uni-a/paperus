import type { PDFDocumentProxy } from 'pdfjs-dist';
import type { TextItem } from 'pdfjs-dist/types/src/display/api';

/** A chapter or section of a PDF, to jump to. */
export type Section = {
	title: string;
	/** From 1. */
	page: number;
	/** Distance from the page's top edge, in PDF points (null: the top). */
	top: number | null;
	/** Distance from the page's left edge, in PDF points (null: unknown);
	 * in fluent mode, which column. */
	left: number | null;
	/** 0 for chapters, 1 for their sections, 2 below. */
	depth: number;
};

const MAX_SECTIONS = 150;
// Reading every page's text for headings: enough for papers and theses.
const MAX_PAGES_READ = 80;

/** The PDF's own contents (its bookmarks, as LaTeX writes them), else the
 * headings found in its text; empty if neither. */
export async function contents(pdf: PDFDocumentProxy): Promise<Section[]> {
	const own = await outline(pdf).catch(() => []);
	if (own.length >= 2) return own;
	return headings(pdf).catch(() => []);
}

/** Where a heading is on its page (PDF points from the top and the left
 * edge), found by its words nearest ``top``: a bookmark that gives only a
 * height does not say which column (and may point well above it). */
async function headingOf(
	pdf: PDFDocumentProxy,
	texts: Map<number, Promise<TextItem[]>>,
	number: number,
	title: string,
	top: number | null
): Promise<{ top: number; left: number } | null> {
	const page = await pdf.getPage(number);
	if (!texts.has(number))
		texts.set(
			number,
			page
				.getTextContent()
				.then((content) => content.items.filter((item): item is TextItem => 'str' in item))
		);
	const items = await texts.get(number)!;
	const plain = (text: string) => text.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
	// With its number and without ("I. INTRODUCTION": the PDF may hold the
	// "I." apart).
	const wanted = [plain(title), plain(title.replace(/^\s*[\p{L}\d]{1,5}[.)]\s+/u, ''))].filter(
		(words) => words.length >= 3
	);
	const matches = (words: string) => wanted.some((w) => w.startsWith(words) || words.startsWith(w));
	const upper = page.view[3];
	let best: { top: number; left: number; distance: number } | null = null;
	for (const item of items) {
		const words = plain(item.str);
		if (words.length < 3 || !matches(words)) continue;
		const size = Math.hypot(item.transform[2], item.transform[3]);
		const at = Math.max(0, upper - item.transform[5] - size);
		const distance = top === null ? at : Math.abs(at - top);
		// Near the height the bookmark gives; the first on the page if none.
		if ((top === null || distance < 250) && (!best || distance < best.distance))
			best = { top: at, left: item.transform[4] - page.view[0], distance };
	}
	return best && { top: best.top, left: best.left };
}

type OutlineEntry = { title: string; dest: unknown; items?: OutlineEntry[] };

async function outline(pdf: PDFDocumentProxy): Promise<Section[]> {
	const found: Section[] = [];
	const texts = new Map<number, Promise<TextItem[]>>();
	async function walk(entries: OutlineEntry[] | null | undefined, depth: number) {
		for (const entry of entries ?? []) {
			if (found.length >= MAX_SECTIONS) return;
			const place = await destination(pdf, entry.dest).catch(() => null);
			const title = tidy(entry.title);
			// The heading's own place, where its words are near: bookmarks
			// often give the page's left edge (hyperref's) or a height
			// above it, which in fluent mode would be the wrong column.
			if (place && title) {
				const heading = await headingOf(pdf, texts, place.page, title, place.top).catch(() => null);
				if (heading) Object.assign(place, heading);
			}
			if (place && title) found.push({ title, depth, ...place });
			if (depth < 2) await walk(entry.items, depth + 1);
		}
	}
	await walk((await pdf.getOutline()) as OutlineEntry[] | null, 0);
	return found;
}

async function destination(
	pdf: PDFDocumentProxy,
	dest: unknown
): Promise<{ page: number; top: number | null; left: number | null } | null> {
	const explicit = typeof dest === 'string' ? await pdf.getDestination(dest) : dest;
	if (!Array.isArray(explicit) || explicit.length === 0) return null;
	const [ref, kind, ...args] = explicit as [unknown, { name?: string } | undefined, ...unknown[]];
	const index =
		typeof ref === 'number'
			? ref
			: await pdf.getPageIndex(ref as Parameters<PDFDocumentProxy['getPageIndex']>[0]);
	const page = await pdf.getPage(index + 1);
	const upper = page.view[3];
	// XYZ left top zoom, FitH top, FitBH top, FitR left bottom right top:
	// a height from the bottom.
	const height =
		kind?.name === 'XYZ'
			? args[1]
			: kind?.name === 'FitH' || kind?.name === 'FitBH'
				? args[0]
				: kind?.name === 'FitR'
					? Math.max(Number(args[1]), Number(args[3]))
					: null;
	const left = kind?.name === 'XYZ' ? args[0] : null;
	return {
		page: index + 1,
		top: typeof height === 'number' ? Math.max(0, upper - height) : null,
		left: typeof left === 'number' ? Math.max(0, left - page.view[0]) : null
	};
}

// "2 Methods", "2.1 Data", "III. RESULTS", "A. Proof of …"
const NUMBERED = /^(?:(\d{1,2}(?:\.\d{1,2}){0,2})\.?|([IVX]{1,5})\.|([A-H])\.)\s+\S/;
const NAMED =
	/^(?:abstract|introduction|background|related work|methods?|materials and methods|model|theory|setup|experiment(?:s|al setup)?|results(?: and discussion)?|discussion|conclusions?|summary(?: and outlook)?|outlook|acknowledge?ments?|references|bibliography|appendi(?:x|ces)\b.*|supplementary.*)$/i;

type Line = { text: string; size: number; bold: boolean; x: number; y: number };

/** Headings in the text: numbered ones and the usual names (Abstract,
 * Introduction, References, …), set larger or bolder than the body text. */
async function headings(pdf: PDFDocumentProxy): Promise<Section[]> {
	const pages: { number: number; upper: number; start: number; lines: Line[] }[] = [];
	const sizes: number[] = [];
	for (let number = 1; number <= Math.min(pdf.numPages, MAX_PAGES_READ); number++) {
		const page = await pdf.getPage(number);
		const content = await page.getTextContent();
		// Pieces of text by height on the page; split where a wide gap
		// separates columns, so a heading is not read with the text beside it.
		const rows = new Map<number, (TextItem & { size: number; bold: boolean })[]>();
		for (const item of content.items as TextItem[]) {
			if (!('str' in item) || !item.str.trim()) continue;
			const size = Math.abs(item.transform[3]) || item.height;
			const family = content.styles[item.fontName]?.fontFamily ?? '';
			const bold = /bold|black|heavy/i.test(`${item.fontName} ${family}`);
			const key = Math.round(item.transform[5] / 2);
			rows.set(key, [...(rows.get(key) ?? []), { ...item, size, bold }]);
			for (let i = 0; i < Math.min(item.str.length, 40); i++) sizes.push(size);
		}
		const lines: Line[] = [];
		for (const row of rows.values()) {
			row.sort((a, b) => a.transform[4] - b.transform[4]);
			let line: Line | null = null;
			let end = 0;
			for (const item of row) {
				const x = item.transform[4];
				if (!line || x - end > item.size * 2.5) {
					line = { text: '', size: 0, bold: true, x, y: item.transform[5] };
					lines.push(line);
				}
				line.text +=
					(item.str.startsWith(' ') || line.text.endsWith(' ') || !line.text ? '' : ' ') + item.str;
				line.size = Math.max(line.size, item.size);
				line.bold &&= item.bold;
				end = x + item.width;
			}
		}
		pages.push({
			number,
			upper: page.view[3],
			start: page.view[0],
			lines: lines.sort((a, b) => b.y - a.y)
		});
	}
	if (!sizes.length) return [];
	const body = sizes.sort((a, b) => a - b)[Math.floor(sizes.length / 2)];

	const found: Section[] = [];
	for (const { number, upper, start, lines } of pages) {
		for (const line of lines) {
			const text = tidy(line.text);
			if (text.length < 3 || text.length > 90 || found.length >= MAX_SECTIONS) continue;
			const larger = line.size >= body * 1.12;
			const stands = larger || line.bold || capitals(text);
			const numbered = NUMBERED.exec(text);
			const named = NAMED.test(text.replace(/^\d+(\.\d+)*\.?\s+/, ''));
			if (!stands || !(numbered || named)) continue;
			if (numbered && !named && !wordy(text.slice(numbered[0].length - 1))) continue;
			const depth = numbered?.[1] ? numbered[1].split('.').length - 1 : numbered?.[3] ? 1 : 0;
			const previous = found.at(-1);
			if (previous && previous.title === text) continue;
			found.push({
				title: text,
				page: number,
				top: Math.max(0, upper - line.y - line.size),
				left: Math.max(0, line.x - start),
				depth: Math.min(depth, 2)
			});
		}
	}
	return found.length >= 2 ? found : [];
}

/** Set in capitals, but for a few (an abbreviation like "BdG" in
 * "II. FULL BdG MODEL"). */
function capitals(text: string): boolean {
	const letters = text.replace(/[^\p{L}]/gu, '');
	const upper = letters.replace(/[^\p{Lu}]/gu, '').length;
	return letters.length > 0 && upper >= letters.length * 0.8;
}

/** Words after a heading's number, not an equation's numbers or a sentence
 * of a numbered list: starting with a letter, mostly letters, two letters
 * in a row at least, no full stop at the end. */
function wordy(rest: string): boolean {
	const letters = (rest.match(/\p{L}/gu) ?? []).length;
	return (
		/^\p{L}/u.test(rest) &&
		/\p{L}{3}/u.test(rest) &&
		letters >= rest.replace(/\s/g, '').length * 0.7 &&
		!/[.;,:]$/.test(rest)
	);
}

function tidy(title: string): string {
	return title.replace(/\s+/g, ' ').trim();
}
