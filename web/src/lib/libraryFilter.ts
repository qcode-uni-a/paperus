import type { Rules } from '#lib/api/generated/types.gen.ts';

/** The library's filter, kept in the address (so Back and links keep it):
 * the rules of smart collections, and an author ("Family, Given"). */
export type Filter = { rules: Rules; author: string };

// Address parameter for each list of the rules (as the list API names them).
const LISTS = {
	tags_all: 'tag',
	tags_any: 'tag_any',
	tags_none: 'tag_none',
	types: 'type',
	owners: 'owner',
	authors: 'author_id'
} as const;
const DATES = { published_from: 'published_from', published_to: 'published_to' } as const;

/** ``params``: the address's (``page.url.searchParams``). */
export function fromAddress(params: Pick<URLSearchParams, 'get' | 'getAll'>): Filter {
	const rules: Rules = {};
	for (const [rule, param] of Object.entries(LISTS)) {
		const values = params.getAll(param);
		if (values.length) rules[rule as keyof typeof LISTS] = values;
	}
	for (const [rule, param] of Object.entries(DATES)) {
		const value = params.get(param);
		if (value) rules[rule as keyof typeof DATES] = value;
	}
	const days = Number.parseInt(params.get('added_days') ?? '', 10);
	if (days > 0) rules.added_days = days;
	return { rules, author: params.get('author')?.trim() ?? '' };
}

/** The address's parameters for the filter (others, e.g. a search, kept). */
export function toAddress(filter: Filter, keep: { toString(): string }): URLSearchParams {
	const params = new URLSearchParams(keep.toString());
	for (const param of [...Object.values(LISTS), ...Object.values(DATES), 'added_days', 'author']) {
		params.delete(param);
	}
	for (const [rule, param] of Object.entries(LISTS)) {
		for (const value of filter.rules[rule as keyof typeof LISTS] ?? []) params.append(param, value);
	}
	for (const [rule, param] of Object.entries(DATES)) {
		const value = filter.rules[rule as keyof typeof DATES];
		if (value) params.set(param, value);
	}
	if (filter.rules.added_days) params.set('added_days', String(filter.rules.added_days));
	if (filter.author) params.set('author', filter.author);
	return params;
}

/** For the list API. */
export function toQuery(filter: Filter) {
	const { rules } = filter;
	const list = (values: string[] | undefined) => (values?.length ? values : undefined);
	return {
		tag: list(rules.tags_all),
		tag_any: list(rules.tags_any),
		tag_none: list(rules.tags_none),
		type: list(rules.types),
		owner: list(rules.owners),
		author_id: list(rules.authors),
		published_from: rules.published_from ?? undefined,
		published_to: rules.published_to ?? undefined,
		added_days: rules.added_days ?? undefined,
		author: filter.author || undefined
	};
}

export function isEmpty(filter: Filter): boolean {
	return !filter.author && Object.values(toQuery(filter)).every((v) => v === undefined);
}
