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
