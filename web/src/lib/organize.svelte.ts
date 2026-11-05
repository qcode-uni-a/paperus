import { listCollections, listTags } from '#lib/api/client.ts';
import type { CollectionOut, TagOut } from '#lib/api/generated/types.gen.ts';

export type Collection = CollectionOut;
export type Tag = TagOut;

/** Tags and collections for the sidebar and pickers; reload after changes. */
export const organize = $state<{ tags: Tag[]; collections: Collection[] }>({
	tags: [],
	collections: []
});

export async function loadOrganize(): Promise<void> {
	const [tags, collections] = await Promise.all([listTags(), listCollections()]);
	organize.tags = tags.data ?? [];
	organize.collections = collections.data ?? [];
}

/** Children of a collection (or the top level), by name. */
export function childrenOf(parentId: string | null): Collection[] {
	return organize.collections.filter((c) => c.parent_id === parentId);
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

/** All collections in tree order with their depth, for indented lists. */
export function flatTree(): { collection: Collection; depth: number }[] {
	const rows: { collection: Collection; depth: number }[] = [];
	const walk = (parentId: string | null, depth: number) => {
		for (const collection of childrenOf(parentId)) {
			rows.push({ collection, depth });
			walk(collection.id, depth + 1);
		}
	};
	walk(null, 0);
	return rows;
}
