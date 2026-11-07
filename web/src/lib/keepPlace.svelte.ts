import { snapshot } from '$app/navigation';
import { tick } from 'svelte';

/** Where a list was left: how many rows were loaded, how far down, and the
 * row at the top of the window (``data-place`` on rows) and where it was. */
type Place = { count: number; y: number; row?: string; top?: number };

// Rows loaded beyond the count, for papers added at the top meanwhile.
const SPARE = 20;

/** The first row (``[data-place]``) still visible below ``line``. */
function topRow(line: number): HTMLElement | undefined {
	for (const row of document.querySelectorAll<HTMLElement>('[data-place]')) {
		if (row.getBoundingClientRect().bottom > line) return row;
	}
	return undefined;
}

/**
 * Back to a list (after opening a paper from it) comes back to the same
 * place: as many rows as were loaded, and the row that was at the top of the
 * window where it was (else as far down as before; papers added meanwhile
 * push the rows down). The browser cannot do that alone, as the rows arrive
 * after the page is shown. `reload(count)` loads the first `count` rows (at
 * least).
 */
export function keepPlace(
	id: string,
	count: () => number,
	reload: (count: number) => Promise<unknown>
): void {
	snapshot<Place>({
		id,
		capture: () => {
			const row = topRow(0);
			return {
				count: count(),
				y: window.scrollY,
				row: row?.dataset.place,
				top: row?.getBoundingClientRect().top
			};
		},
		restore: async (place) => {
			// After the list's own first load has started (it would win).
			await tick();
			await reload(place.count + (place.row ? SPARE : 0));
			await tick();
			const row = place.row
				? document.querySelector<HTMLElement>(`[data-place="${CSS.escape(place.row)}"]`)
				: null;
			window.scrollTo(
				0,
				row ? row.getBoundingClientRect().top + window.scrollY - (place.top ?? 0) : place.y
			);
		}
	});
}
