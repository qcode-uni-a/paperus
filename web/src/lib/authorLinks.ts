import { resolve } from '$app/paths';

/** Where a paper's author leads: their page once linked to a person, else
 * the library's papers with that name. */
export function authorHref(
	item: { authors: string[]; author_ids?: (string | null)[] | null },
	index: number
): string {
	const id = item.author_ids?.[index];
	if (id) return resolve('/authors/[id]', { id });
	return `${resolve('/')}?${new URLSearchParams({ author: item.authors[index] })}`;
}
