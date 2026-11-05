import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import { createNote, errorMessage } from '#lib/api/client.ts';

/** Start a note (about some papers, or in a collection) and open it for writing. */
export async function startNote(
	about: { items?: string[]; collection?: string; library?: string } = {}
): Promise<string | null> {
	const { data, error } = await createNote({
		body: {
			text: '',
			items: (about.items ?? []).map((item_id) => ({ item_id })),
			collection_id: about.collection ?? null,
			library_id: about.library ?? null
		}
	});
	if (!data) return errorMessage(error);
	await goto(`${resolve('/notes/[id]', { id: data.id })}?write`);
	return null;
}
