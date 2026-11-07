import type { PDFDocumentProxy } from 'pdfjs-dist';
import type { TextItem } from 'pdfjs-dist/types/src/display/api';

/** A chapter or section of a PDF, to jump to. */
export type Section = {
	title: string;
	/** From 1. */
	page: number;
	/** Distance from the page's top edge, in PDF points (null: the top). */
	top: number | null;
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

type OutlineEntry = { title: string; dest: unknown; items?: OutlineEntry[] };

async function outline(pdf: PDFDocumentProxy): Promise<Section[]> {
	const found: Section[] = [];
	async function walk(entries: OutlineEntry[] | null | undefined, depth: number) {
		for (const entry of entries ?? []) {
			if (found.length >= MAX_SECTIONS) return;
			const place = await destination(pdf, entry.dest).catch(() => null);
			const title = tidy(entry.title);
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
): Promise<{ page: number; top: number | null } | null> {
	const explicit = typeof dest === 'string' ? await pdf.getDestination(dest) : dest;
	if (!Array.isArray(explicit) || explicit.length === 0) return null;
	const [ref, kind, ...args] = explicit as [unknown, { name?: string } | undefined, ...unknown[]];
	const index =
		typeof ref === 'number'
			? ref
			: await pdf.getPageIndex(ref as Parameters<PDFDocumentProxy['getPageIndex']>[0]);
	const page = await pdf.getPage(index + 1);
	const upper = page.view[3];
	// XYZ left top zoom, FitH top, FitBH top: a height from the bottom.
	const height =
		kind?.name === 'XYZ'
			? args[1]
			: kind?.name === 'FitH' || kind?.name === 'FitBH'
				? args[0]
				: null;
	return {
		page: index + 1,
		top: typeof height === 'number' ? Math.max(0, upper - height) : null
	};
}

// "2 Methods", "2.1 Data", "III. RESULTS", "A. Proof of …"
const NUMBERED = /^(?:(\d{1,2}(?:\.\d{1,2}){0,2})\.?|([IVX]{1,5})\.|([A-H])\.)\s+\S/;
const NAMED =
	/^(?:abstract|introduction|background|related work|methods?|materials and methods|model|theory|setup|experiment(?:s|al setup)?|results(?: and discussion)?|discussion|conclusions?|summary(?: and outlook)?|outlook|acknowledge?ments?|references|bibliography|appendi(?:x|ces)\b.*|supplementary.*)$/i;

type Line = { text: string; size: number; bold: boolean; y: number };

/** Headings in the text: numbered ones and the usual names (Abstract,
 * Introduction, References, …), set larger or bolder than the body text. */
async function headings(pdf: PDFDocumentProxy): Promise<Section[]> {
	const pages: { number: number; upper: number; lines: Line[] }[] = [];
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
					line = { text: '', size: 0, bold: true, y: item.transform[5] };
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
			lines: lines.sort((a, b) => b.y - a.y)
		});
	}
	if (!sizes.length) return [];
	const body = sizes.sort((a, b) => a - b)[Math.floor(sizes.length / 2)];

	const found: Section[] = [];
	for (const { number, upper, lines } of pages) {
		for (const line of lines) {
			const text = tidy(line.text);
			if (text.length < 3 || text.length > 90 || found.length >= MAX_SECTIONS) continue;
			const larger = line.size >= body * 1.12;
			const stands = larger || line.bold || text === text.toUpperCase();
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
				depth: Math.min(depth, 2)
			});
		}
	}
	return found.length >= 2 ? found : [];
}

/** Words after a heading's number, not an equation's numbers or a sentence
 * of a numbered list: starting with a letter, mostly letters, two letters
 * in a row at least, no full stop at the end. */
function wordy(rest: string): boolean {
	const letters = (rest.match(/\p{L}/gu) ?? []).length;
	return (
		/^\p{L}/u.test(rest) &&
		/\p{L}{2}/u.test(rest) &&
		letters >= rest.replace(/\s/g, '').length * 0.7 &&
		!/[.;,:]$/.test(rest)
	);
}

function tidy(title: string): string {
	return title.replace(/\s+/g, ' ').trim();
}
