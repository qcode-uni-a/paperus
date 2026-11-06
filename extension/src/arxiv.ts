/** On arXiv (listings, search results, abstract pages): a small paperus
 * button next to each paper. Dimmed: not in paperus yet, a click saves it
 * with its PDF. Full with a check: in paperus, a click opens it there. */

import { settings } from './paperus';

const ICON = chrome.runtime.getURL('icons/icon-32.png');
const ID = /(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?\/\d{7})(?:v\d+)?/;

interface Spot {
	id: string;
	after: Element;
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
		if (id && !found.some((s) => s.id === id)) found.push({ id, after: link });
	}
	return found;
}

function button(id: string): { host: HTMLElement; set: (state: State, link?: string) => void } {
	const host = document.createElement('span');
	host.className = 'paperus-save';
	const shadow = host.attachShadow({ mode: 'closed' });
	const style = document.createElement('style');
	style.textContent = `
		button { all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;
			margin: 0 6px; padding: 1px 6px 1px 2px; border-radius: 999px; font: 12px system-ui, sans-serif;
			color: #2338a8; vertical-align: middle; }
		button:hover { background: #e9ecfa; }
		button:focus-visible { outline: 2px solid #2338a8; }
		img { width: 16px; height: 16px; opacity: .6; filter: grayscale(1); transition: opacity .15s; }
		button.have img { opacity: 1; filter: none; }
		button.busy img { animation: pulse 1s infinite; }
		@keyframes pulse { 50% { opacity: .9 } }
		.label { display: none; }
		button:hover .label, button.busy .label, button.have .label { display: inline; }
		button.failed { color: #c0392b; }
	`;
	const element = document.createElement('button');
	const image = document.createElement('img');
	image.src = ICON;
	image.alt = '';
	const label = document.createElement('span');
	label.className = 'label';
	element.append(image, label);
	shadow.append(style, element);
	let target: string | undefined;
	element.addEventListener('click', async (event) => {
		event.preventDefault();
		event.stopPropagation();
		if (target) {
			window.open(target, '_blank', 'noopener');
			return;
		}
		set('busy');
		const result = await chrome.runtime.sendMessage({ type: 'saveArxiv', id });
		if (result?.ok) set('have', result.link);
		else set('failed', undefined, result?.text);
	});
	function set(state: State, link?: string, why?: string): void {
		element.className = state;
		target = link;
		const words: Record<State, string> = {
			save: 'Save to paperus',
			busy: 'Saving…',
			have: '✓ in paperus',
			failed: 'Not saved'
		};
		label.textContent = words[state];
		element.title = why ?? (state === 'have' ? 'Open in paperus' : words[state]);
		element.setAttribute('aria-label', element.title);
	}
	set('save');
	return { host, set };
}

type State = 'save' | 'busy' | 'have' | 'failed';

async function start(): Promise<void> {
	const found = spots();
	if (found.length === 0) return;
	const buttons = new Map(found.map((s) => [s.id, button(s.id)]));
	for (const spot of found) spot.after.after(buttons.get(spot.id)!.host);
	const known: Record<string, string | null> =
		(await chrome.runtime.sendMessage({ type: 'lookup', ids: found.map((s) => s.id) })) ?? {};
	const server = (await settings())?.server;
	for (const [id, item] of Object.entries(known)) {
		if (item && server) buttons.get(id)?.set('have', new URL(`/items/${item}`, server).href);
	}
}

start();
