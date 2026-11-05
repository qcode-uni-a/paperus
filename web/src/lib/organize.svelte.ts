import { listCollections, listLibraries, listTags } from '#lib/api/client.ts';
import type { CollectionOut, LibraryOut, TagOut } from '#lib/api/generated/types.gen.ts';

export type Collection = CollectionOut;
export type Tag = TagOut;
export type Library = LibraryOut;

/** Libraries, tags and collections for pickers and filters; reload after
 * changes. */
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

/** "My library", "Shared library", or "Chair / Project" for nested groups. */
export function libraryName(id: string | null | undefined): string {
	const library = libraryById(id);
	return library ? [...library.path, library.name].join(' / ') : '';
}

/** Libraries the person may add to, the default first. */
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

/** Where new items for a collection go: a group's collection holds only that
 * group's items, so its library; a private one, the default library. */
export function libraryForCollection(collectionId: string | undefined): string | undefined {
	const collection = organize.collections.find((c) => c.id === collectionId);
	const library = libraryById(collection?.library_id);
	return library?.kind === 'group' ? library.id : undefined;
}
