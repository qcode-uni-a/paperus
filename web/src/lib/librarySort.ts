/** The order of the library's and collections' lists, kept in the address
 * (``sort``, ``order``) and remembered on this device for the next visit. */

export type SortField = 'added' | 'title' | 'author' | 'year' | 'published' | 'journal';
export type SortOrder = 'asc' | 'desc';
export type Sort = { field: SortField; order: SortOrder };

export const SORT_FIELDS: { value: SortField; label: string }[] = [
	{ value: 'added', label: 'Date added' },
	{ value: 'title', label: 'Title' },
	{ value: 'author', label: 'First author' },
	{ value: 'year', label: 'Year' },
	{ value: 'published', label: 'Publication date' },
	{ value: 'journal', label: 'Journal' }
];

const DATES: SortField[] = ['added', 'year', 'published'];
const REMEMBERED = 'paperus.sort';

/** Dates newest first, words A to Z, unless asked otherwise. */
export function defaultOrder(field: SortField): SortOrder {
	return DATES.includes(field) ? 'desc' : 'asc';
}

/** The order in words: "Newest first", "Z to A". */
export function orderName(sort: Sort): string {
	if (DATES.includes(sort.field)) return sort.order === 'desc' ? 'Newest first' : 'Oldest first';
	return sort.order === 'asc' ? 'A to Z' : 'Z to A';
}

function field(value: string | null | undefined): SortField | null {
	return SORT_FIELDS.some((f) => f.value === value) ? (value as SortField) : null;
}

function remembered(): Sort | null {
	try {
		const saved = JSON.parse(localStorage.getItem(REMEMBERED) ?? 'null') as Partial<Sort> | null;
		const chosen = field(saved?.field);
		if (!chosen) return null;
		return { field: chosen, order: saved?.order === 'asc' ? 'asc' : 'desc' };
	} catch {
		return null;
	}
}

/** The address's order, else the one last chosen here, else newest added first. */
export function sortFromAddress(params: Pick<URLSearchParams, 'get'>): Sort {
	const chosen = field(params.get('sort'));
	if (!chosen) return remembered() ?? { field: 'added', order: 'desc' };
	const order = params.get('order');
	return {
		field: chosen,
		order: order === 'asc' || order === 'desc' ? order : defaultOrder(chosen)
	};
}

/** The address with this order (others kept); remembered for next time. */
export function sortToAddress(sort: Sort, keep: { toString(): string }): URLSearchParams {
	try {
		localStorage.setItem(REMEMBERED, JSON.stringify(sort));
	} catch {
		// Not remembered (a private window): the address still has it.
	}
	const params = new URLSearchParams(keep.toString());
	params.set('sort', sort.field);
	params.set('order', sort.order);
	return params;
}

/** Newest added first: the list's own order, paged by its last item. */
export function isDefault(sort: Sort): boolean {
	return sort.field === 'added' && sort.order === 'desc';
}

/** For the list API: nothing for the default order. */
export function sortQuery(sort: Sort): { sort?: SortField; order?: SortOrder } {
	return isDefault(sort) ? {} : { sort: sort.field, order: sort.order };
}
