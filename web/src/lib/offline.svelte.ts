/** "Keep offline" on this device, in the app (app/src-tauri/src/offline):
 * papers and collections marked so are kept whole with their PDFs, and a
 * collection's new papers too. The app says what is kept after each page
 * load (``window.paperusApp.kept``), also in the copy offline; marking asks
 * it with a link of its own, as logging in in the browser does. */
import { app, offline } from '#lib/app.ts';

function told() {
	return {
		items: [...(app?.kept?.items ?? [])],
		collections: [...(app?.kept?.collections ?? [])],
		/** The papers kept whole on this device now (as of the last sync). */
		available: [...(app?.kept?.available ?? [])]
	};
}

export const keeping = $state(told());

if (typeof window !== 'undefined') {
	window.addEventListener('paperus-kept', () => Object.assign(keeping, told()));
}

/** Whether papers can be kept offline here: in an app that can, online. */
export const canKeep = !!app && (app.features?.offline ?? 0) >= 1 && !offline;

/** Keep (or stop keeping) a paper or collection offline on this device. */
export function keep(kind: 'item' | 'collection', id: string, on: boolean) {
	// At once; the app tells what it keeps after.
	const key = kind === 'item' ? 'items' : 'collections';
	const others = keeping[key].filter((kept) => kept !== id);
	keeping[key] = on ? [...others, id] : others;
	location.href = `paperus-app:keep?kind=${kind}&id=${id}&on=${on}`;
}
