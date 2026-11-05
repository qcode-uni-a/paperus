/** Light, dark, or the device's setting; remembered in the browser. */

export type Theme = 'system' | 'light' | 'dark';

const STORAGE_KEY = 'paperus.theme';
const ORDER: Theme[] = ['system', 'light', 'dark'];

function stored(): Theme {
	try {
		const value = localStorage.getItem(STORAGE_KEY);
		return value === 'light' || value === 'dark' ? value : 'system';
	} catch {
		return 'system';
	}
}

const state = $state({ theme: stored() });

export const theme = {
	get current(): Theme {
		return state.theme;
	},
	next(): void {
		state.theme = ORDER[(ORDER.indexOf(state.theme) + 1) % ORDER.length];
		const root = document.documentElement;
		if (state.theme === 'system') delete root.dataset.theme;
		else root.dataset.theme = state.theme;
		try {
			if (state.theme === 'system') localStorage.removeItem(STORAGE_KEY);
			else localStorage.setItem(STORAGE_KEY, state.theme);
		} catch {
			// Storage may be blocked; the choice holds for this visit.
		}
	}
};
