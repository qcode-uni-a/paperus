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
	document: 'Document'
};

export function typeName(type: string): string {
	return TYPE_NAMES[type] ?? type.replace(/-/g, ' ').replace(/^./, (c) => c.toUpperCase());
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

/** A time of day stored in UTC (as the server's schedules are), in the
 * browser's time zone: "03:30". */
export function localTime(utcHour: number, minute = 0): string {
	const date = new Date();
	date.setUTCHours(utcHour, minute, 0, 0);
	return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
