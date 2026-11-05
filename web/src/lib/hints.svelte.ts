import { markHintSeen } from '#lib/api/client.ts';
import { writableLibraries } from '#lib/organize.svelte.ts';
import { session } from '#lib/session.svelte.ts';

/** Tutorial hints, each shown once per person (remembered on the server). */

const FIRST_OWNER = 'first-owner';

export const hints = $state<{
	/** The first paper someone added, while they may choose its owner. */
	firstOwner: { itemId: string; title: string; libraryId: string } | null;
}>({ firstOwner: null });

/** After adding a paper: explain owners the first time, if there is a choice. */
export function addedPaper(itemId: string, title: string, libraryId: string | undefined): void {
	const user = session.user;
	if (!user || !libraryId || hints.firstOwner) return;
	if (user.seen_hints.includes(FIRST_OWNER) || writableLibraries().length < 2) return;
	hints.firstOwner = { itemId, title, libraryId };
}

export async function dismissFirstOwner(): Promise<void> {
	hints.firstOwner = null;
	if (session.user && !session.user.seen_hints.includes(FIRST_OWNER)) {
		session.user.seen_hints = [...session.user.seen_hints, FIRST_OWNER];
		await markHintSeen({ path: { hint: FIRST_OWNER } });
	}
}
