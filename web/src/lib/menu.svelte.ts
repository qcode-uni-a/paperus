/** The left menu, opened and closed with the burger button in the header.
 * Wide screens: a sidebar, open unless the viewer collapsed it (remembered).
 * Narrow screens: a drawer over the content, closed until opened. */

const STORAGE_KEY = 'paperus.menu';
// Phones and tablets held upright: the content needs the whole width.
const NARROW = '(max-width: 900px)';

function storedOpen(): boolean {
	try {
		return localStorage.getItem(STORAGE_KEY) !== 'closed';
	} catch {
		return true;
	}
}

const state = $state({
	narrow: matchMedia(NARROW).matches,
	wideOpen: storedOpen(),
	drawerOpen: false
});

export const menu = {
	get narrow(): boolean {
		return state.narrow;
	},
	get open(): boolean {
		return state.narrow ? state.drawerOpen : state.wideOpen;
	},
	toggle(): void {
		if (state.narrow) {
			state.drawerOpen = !state.drawerOpen;
			return;
		}
		state.wideOpen = !state.wideOpen;
		try {
			localStorage.setItem(STORAGE_KEY, state.wideOpen ? 'open' : 'closed');
		} catch {
			// Storage may be blocked; the menu still works for this visit.
		}
	},
	closeDrawer(): void {
		state.drawerOpen = false;
	},
	/** Follow the screen width; returns a cleanup function. */
	watch(): () => void {
		const query = matchMedia(NARROW);
		const update = () => (state.narrow = query.matches);
		query.addEventListener('change', update);
		return () => query.removeEventListener('change', update);
	}
};
