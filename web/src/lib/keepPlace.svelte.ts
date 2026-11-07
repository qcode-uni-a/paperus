import { snapshot } from '$app/navigation';
import { tick } from 'svelte';

/** Where a list was left: how many rows were loaded, and how far down. */
type Place = { count: number; y: number };

/**
 * Back to a list (after opening a paper from it) comes back to the same
 * place: as many rows as were loaded, scrolled as far. The browser cannot
 * do that alone, as the rows arrive after the page is shown.
 * `reload(count)` loads the first `count` rows (at least).
 */
export function keepPlace(
	id: string,
	count: () => number,
	reload: (count: number) => Promise<unknown>
): void {
	snapshot<Place>({
		id,
		capture: () => ({ count: count(), y: window.scrollY }),
		restore: async (place) => {
			// After the list's own first load has started (it would win).
			await tick();
			await reload(place.count);
			await tick();
			window.scrollTo(0, place.y);
		}
	});
}
