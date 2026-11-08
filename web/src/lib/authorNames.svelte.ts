import { getAuthor } from '#lib/api/client.ts';
import { personName } from '#lib/names.svelte.ts';

/** Authors' names by id, for rules that hold ids (smart collections, the
 * library's filter): asked for once, shown when they arrive. */
const names = $state<Record<string, string>>({});
const asked = new Set<string>();

export function authorName(id: string): string {
	if (!(id in names) && !asked.has(id)) {
		asked.add(id);
		getAuthor({ path: { author_id: id } }).then(({ data }) => {
			names[id] = data ? personName(data) : 'someone not in your library';
		});
	}
	return names[id] ?? '…';
}

/** A name already at hand (e.g. picked from a search). */
export function rememberAuthor(id: string, name: string): void {
	names[id] = name;
}
