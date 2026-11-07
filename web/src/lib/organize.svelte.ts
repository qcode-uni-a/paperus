import { listCollections, listLibraries, listTags } from '#lib/api/client.ts';
import type { CollectionOut, LibraryOut, Rules, TagOut } from '#lib/api/generated/types.gen.ts';
import { plural } from '#lib/format.ts';

export type Collection = CollectionOut;
export type Tag = TagOut;
export type Library = LibraryOut;

/** Owners (the person and their groups; "libraries" in the API), tags and
 * collections for pickers; reload after changes. */
export const organize = $state<{ libraries: Library[]; tags: Tag[]; collections: Collection[] }>({
	libraries: [],
	tags: [],
	collections: []
});

export async function loadOrganize(): Promise<void> {
	const [libraries, tags, collections] = await Promise.all([
		listLibraries(),
		listTags(),
		listCollections()
	]);
	organize.libraries = libraries.data ?? [];
	organize.tags = tags.data ?? [];
	organize.collections = collections.data ?? [];
}

/** Whether the person reads more than their own library (then lists show
 * which library things are in). */
export function severalLibraries(): boolean {
	return organize.libraries.length > 1;
}

export function libraryById(id: string | null | undefined): Library | undefined {
	return organize.libraries.find((library) => library.id === id);
}

/** The owner's name: "Me", or the group's ("Chair / Project" if nested). */
export function libraryName(id: string | null | undefined): string {
	const library = libraryById(id);
	return library ? [...library.path, library.name].join(' / ') : '';
}

/** Owners the person may give things to, the default first. */
export function writableLibraries(): Library[] {
	return organize.libraries
		.filter((library) => library.writable)
		.toSorted((a, b) => Number(b.default) - Number(a.default));
}

export function defaultLibrary(): Library | undefined {
	return organize.libraries.find((library) => library.default);
}

/** Children of a collection (or the top level of a library, or of all), by
 * name. */
export function childrenOf(parentId: string | null, libraryId?: string): Collection[] {
	return organize.collections.filter(
		(c) => c.parent_id === parentId && (!libraryId || c.library_id === libraryId)
	);
}

/** "Thesis / Chapter 2" for pickers. */
export function collectionPath(id: string): string {
	const names: string[] = [];
	let current = organize.collections.find((c) => c.id === id);
	while (current) {
		names.unshift(current.name);
		current = organize.collections.find((c) => c.id === current?.parent_id);
	}
	return names.join(' / ');
}

/** All collections (of one library, if given) in tree order with their
 * depth, for indented lists. */
export function flatTree(libraryId?: string): { collection: Collection; depth: number }[] {
	const rows: { collection: Collection; depth: number }[] = [];
	const walk = (parentId: string | null, depth: number) => {
		for (const collection of childrenOf(parentId)) {
			rows.push({ collection, depth });
			walk(collection.id, depth + 1);
		}
	};
	for (const collection of childrenOf(null, libraryId)) {
		rows.push({ collection, depth: 0 });
		walk(collection.id, 1);
	}
	return rows;
}

/** Who owns new papers added to a collection: a group's collection holds
 * only the group's papers, so the group; for a private one, the default. */
export function libraryForCollection(collectionId: string | undefined): string | undefined {
	const collection = organize.collections.find((c) => c.id === collectionId);
	const library = libraryById(collection?.library_id);
	return library?.kind === 'group' ? library.id : undefined;
}

/** Whether a group owns it (it is shared with the group's members). */
export function isShared(libraryId: string | null | undefined): boolean {
	return libraryById(libraryId)?.kind === 'group';
}

/** A smart collection finds its papers by rules; papers are not added to it. */
export function isSmart(collection: Collection | undefined): boolean {
	return collection?.rules != null;
}

/** A smart collection's rules in words: "tagged radar, from 2020, books". */
/** "published 2020–2025", "published in March 2024", "published 15 March
 * 2024 – 30 June 2025", "published on 1 May 2024 or later". */
function publishedWords(rules: Rules): string | null {
	const from =
		rules.published_from ?? (rules.year_from != null ? `${rules.year_from}-01-01` : null);
	const to = rules.published_to ?? (rules.year_to != null ? `${rules.year_to}-12-31` : null);
	if (!from && !to) return null;
	const year = (iso: string) => iso.slice(0, 4).replace(/^0+/, '');
	const wholeYears = (!from || from.endsWith('-01-01')) && (!to || to.endsWith('-12-31'));
	if (wholeYears) {
		if (from && to)
			return year(from) === year(to)
				? `published in ${year(from)}`
				: `published ${year(from)}–${year(to)}`;
		return from ? `published in ${year(from)} or later` : `published in ${year(to!)} or earlier`;
	}
	const day = (iso: string) =>
		new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', {
			day: 'numeric',
			month: 'long',
			year: 'numeric',
			timeZone: 'UTC'
		});
	const month = (iso: string) =>
		new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', {
			month: 'long',
			year: 'numeric',
			timeZone: 'UTC'
		});
	if (from && to) {
		const last = new Date(Date.UTC(+to.slice(0, 4), +to.slice(5, 7), 0)).getUTCDate();
		if (from.slice(0, 7) === to.slice(0, 7) && from.endsWith('-01') && +to.slice(8) === last)
			return `published in ${month(from)}`;
		return `published ${day(from)} – ${day(to)}`;
	}
	return from ? `published on ${day(from)} or later` : `published on ${day(to!)} or earlier`;
}

export function describeRules(rules: Rules): string {
	const tagNames = (ids: string[] | undefined) =>
		(ids ?? []).map((id) => organize.tags.find((t) => t.id === id)?.name ?? '?');
	const and = (names: string[], word: string) =>
		names.length > 1 ? `${names.slice(0, -1).join(', ')} ${word} ${names.at(-1)}` : names[0];
	const parts: string[] = [];
	if (rules.tags_all?.length) parts.push(`tagged ${and(tagNames(rules.tags_all), 'and')}`);
	if (rules.tags_any?.length) parts.push(`tagged ${and(tagNames(rules.tags_any), 'or')}`);
	if (rules.tags_none?.length) parts.push(`not tagged ${and(tagNames(rules.tags_none), 'or')}`);
	if (rules.types?.length) parts.push(and(rules.types.map(plural), 'or'));
	const published = publishedWords(rules);
	if (published) parts.push(published);
	if (rules.owners?.length) parts.push(`owned by ${and(rules.owners.map(libraryName), 'or')}`);
	if (rules.added_days != null)
		parts.push(
			rules.added_days === 1
				? 'added today or yesterday'
				: `added in the last ${rules.added_days} days`
		);
	return parts.length ? `Papers ${parts.join(', ')}.` : 'All papers.';
}
