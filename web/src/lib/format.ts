/** Readable names and short citations for items in lists. */

export const TYPE_NAMES: Record<string, string> = {
	'article-journal': 'Journal article',
	article: 'Preprint',
	'paper-conference': 'Conference paper',
	chapter: 'Book chapter',
	book: 'Book',
	thesis: 'Thesis',
	report: 'Report',
	dataset: 'Dataset',
	software: 'Software',
	speech: 'Talk',
	document: 'Document',
	// Not a paper's type: notes, which search finds too.
	note: 'Note'
};

export function typeName(type: string): string {
	return TYPE_NAMES[type] ?? type.replace(/-/g, ' ').replace(/^./, (c) => c.toUpperCase());
}

/** A type in the plural, lower case: "journal articles", "theses". */
export function plural(type: string): string {
	const name = typeName(type).toLowerCase();
	if (name.endsWith('sis')) return `${name.slice(0, -3)}ses`;
	if (name === 'software') return name;
	return `${name}s`;
}

/** "Huang, Xin" → "Xin Huang"; names without a comma stay as they are. */
export function fullName(author: string): string {
	const [family, given] = author.split(',').map((part) => part.trim());
	return given ? `${given} ${family}` : author;
}

/** "Harris, Millman and van der Walt" or "Harris, Millman et al." */
export function shortAuthors(authors: string[]): string {
	const family = authors.map((a) => a.split(',')[0].trim());
	if (family.length <= 3) {
		return family.length < 2
			? (family[0] ?? '')
			: `${family.slice(0, -1).join(', ')} and ${family.at(-1)}`;
	}
	return `${family.slice(0, 2).join(', ')} et al.`;
}

const RELATIVE = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
	['year', 365 * 24 * 3600],
	['month', 30 * 24 * 3600],
	['week', 7 * 24 * 3600],
	['day', 24 * 3600],
	['hour', 3600],
	['minute', 60]
];

/** "3 days ago", "yesterday", "just now". */
export function ago(when: string | Date, now: Date = new Date()): string {
	const seconds = (new Date(when).getTime() - now.getTime()) / 1000;
	for (const [unit, size] of UNITS) {
		if (Math.abs(seconds) >= size) return RELATIVE.format(Math.round(seconds / size), unit);
	}
	return 'just now';
}

/** Why a file's text could not be read, in plain words (the technical
 * message stays available beside it). */
export function readingProblem(error: string | null | undefined): string {
	const text = error ?? '';
	if (/password|encrypt/i.test(text)) return 'The PDF is protected with a password.';
	if (/Data format error|Failed to load document/i.test(text))
		return 'The PDF is damaged, or not a real PDF (e.g. a login page saved as one). Replace it with a good copy.';
	if (/Failed to load page/i.test(text))
		return 'A page of the PDF could not be read; the file may be damaged.';
	if (/too long for tsvector/i.test(text))
		return 'A passage was too long to index; fixed since. Read the file again.';
	if (!text) return 'Reading stopped without a reason; try again.';
	return 'Reading failed.';
}

/** "820 kB", "12 MB", "1.4 GB". */
export function fileSize(bytes: number): string {
	if (bytes < 1024 ** 2) return `${Math.max(1, Math.round(bytes / 1024))} kB`;
	if (bytes < 1024 ** 3) return `${Math.round(bytes / 1024 ** 2)} MB`;
	return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}
