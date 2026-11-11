/** On arXiv (listings, search results, abstract pages): a small paperus
 * button next to each paper. Dimmed: not in paperus yet, a click saves it
 * with its PDF. Full with a check: in paperus, a click opens it there. */

import { paperusButton } from './mark';
import { settings } from './paperus';

const ICON = chrome.runtime.getURL('icons/icon-32.png');
const ID = /(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?\/\d{7})(?:v\d+)?/;

interface Spot {
	id: string;
	/** The button goes right after this (the abstract page's title), or at
	 * the end of the line ``in`` (listings: after "[pdf, html, other]", so
	 * that its label, shown on hover, moves nothing). */
	after?: Element;
	in?: Element;
}

/** Where the papers are on this page, and their IDs. */
function spots(): Spot[] {
	const found: Spot[] = [];
	const abs = location.pathname.match(/^\/abs\/(.+?)(?:v\d+)?$/);
	if (abs) {
		const title = document.querySelector('h1.title');
		if (title) found.push({ id: abs[1], after: title });
		return found;
	}
	// Listings: <dt><a title="Abstract" href="/abs/…">arXiv:…</a> …
	// Search results: <p class="list-title"><a href=".../abs/…">arXiv:…</a>
	for (const link of document.querySelectorAll<HTMLAnchorElement>(
		'dt a[href*="/abs/"], p.list-title a[href*="/abs/"]'
	)) {
		const id = link.href.split('/abs/')[1]?.match(ID)?.[1];
		const line = link.closest('dt, p.list-title');
		if (id && line && !found.some((s) => s.id === id)) found.push({ id, in: line });
	}
	return found;
}

function button(id: string): ReturnType<typeof paperusButton> {
	return paperusButton(ICON, () => chrome.runtime.sendMessage({ type: 'saveArxiv', id }));
}

async function start(): Promise<void> {
	const found = spots();
	if (found.length === 0) return;
	const buttons = new Map(found.map((s) => [s.id, button(s.id)]));
	for (const spot of found) {
		const { host } = buttons.get(spot.id)!;
		if (spot.in) spot.in.append(host);
		else spot.after?.after(host);
	}
	const known: Record<string, string | null> =
		(await chrome.runtime.sendMessage({ type: 'lookup', ids: found.map((s) => s.id) })) ?? {};
	const server = (await settings())?.server;
	for (const [id, item] of Object.entries(known)) {
		if (item && server) buttons.get(id)?.set('have', new URL(`/items/${item}`, server).href);
	}
}

start();
