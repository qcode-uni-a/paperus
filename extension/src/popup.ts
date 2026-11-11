/** The popup under the paperus button (as Zotero's): opening it saves the
 * tab's paper to the default owner, showing each step, then the paper, its
 * PDF or why not, and a choice of owner that moves a paper just added. */
import { settings } from './paperus';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const ALL_SITES = { origins: ['https://*/*', 'http://*/*'] };

interface Owner {
	id: string;
	name: string;
}
type Result =
	| {
			ok: true;
			text: string;
			link: string;
			warning?: boolean;
			item?: { id: string; libraryId: string | null; title: string; added: boolean };
	  }
	| { ok: false; text: string };

$('version').textContent = `Version ${chrome.runtime.getManifest().version}`;
$('settings').addEventListener('click', async (event) => {
	event.preventDefault();
	await chrome.runtime.openOptionsPage();
	window.close();
});

/** A site by its own name (sciencedirect, nature, wiley), short enough to
 * stand under its icon: the address's name before its ending (before
 * ".co.uk" and the like, too). */
function siteName(host: string): string {
	// An address by number, or a machine's own name: as it is.
	if (/^[\d.]+$|^\[|^[^.]+$/.test(host)) return host;
	const parts = host.split('.');
	let name = parts.at(-2) ?? host;
	if (parts.length > 2 && /^(co|ac|com|org|edu|gov|net)$/.test(name)) name = parts.at(-3)!;
	return name;
}

/** Where the PDF is in the little picture. */
type Stage = 'reading' | 'fetching' | 'saving' | 'done' | 'no-pdf' | 'failed';
function stage(name: Stage): void {
	$('flow').dataset.stage = name;
}
const STAGES: Record<string, Stage> = {
	'Reading the page…': 'reading',
	'Fetching the PDF…': 'fetching',
	'Saving to paperus…': 'saving'
};

function state(text: string, outcome?: 'ok' | 'warning' | 'error'): void {
	const shown = $('state');
	shown.textContent = text;
	shown.className = `state ${outcome ?? ''}`;
}

/** The result's sentence split: what happened (first), then the rest. */
function show(result: Result, owners: Owner[]): void {
	if (!result.ok) {
		stage('failed');
		state('Not saved', 'error');
		$('detail').textContent = result.text;
		$('detail').hidden = false;
		// Without access to the site (taken back in Firefox): one click.
		if (/may not fetch|needs to fetch|browser asks you|not let the extension/i.test(result.text))
			$('allow').hidden = false;
		return;
	}
	const known = /^Already in paperus|in paperus already/.test(result.text);
	stage(result.warning ? 'no-pdf' : 'done');
	state(
		known ? 'Already in paperus' : result.warning ? 'Saved, without its PDF' : 'Saved',
		result.warning ? 'warning' : 'ok'
	);
	if (result.item?.title) {
		$('title').textContent = result.item.title;
		$('title').hidden = false;
	}
	// What follows the title: the PDF's fate.
	const rest = result.text.replace(/^[^“]*“[^”]*”[.,]?\s*/, '').replace(/^without its PDF\.\s*/, '');
	$('detail').textContent = rest || (known ? '' : 'With its PDF.');
	$('detail').hidden = !$('detail').textContent;
	const open = $<HTMLAnchorElement>('open');
	open.href = result.link;
	open.hidden = false;

	// A paper this click added may go to another owner.
	const item = result.item;
	if (!item?.added || !item.libraryId || owners.length < 2) return;
	const select = $<HTMLSelectElement>('owner');
	select.replaceChildren(
		...owners.map((owner) => new Option(owner.name, owner.id, false, owner.id === item.libraryId))
	);
	$('owner-field').hidden = false;
	select.addEventListener('change', async () => {
		stay();
		select.disabled = true;
		const moved = (await chrome.runtime.sendMessage({
			type: 'moveItem',
			itemId: item.id,
			libraryId: select.value
		})) as { ok: boolean };
		select.disabled = false;
		state(
			moved.ok ? `Moved to ${select.selectedOptions[0].text}` : 'Not moved',
			moved.ok ? 'ok' : 'error'
		);
	});
}

/** Closing by itself once done: soon when saved, later when only in
 * part or not at all (there is more to read). It waits while the pointer
 * is on it or it has the focus, and stays once one does something there
 * (another owner, allowing access). */
const CLOSE_MS = { ok: 3_000, warning: 8_000, error: 12_000 };
let closing: ReturnType<typeof setTimeout> | undefined;
let left = 0;
let since = 0;
let staying = false;
let resting = false; // the pointer on it, or the focus in it

function closeIn(ms: number): void {
	clearTimeout(closing);
	left = ms;
	if (!resting && !staying) {
		since = Date.now();
		closing = setTimeout(() => window.close(), left);
	}
}
function pause(): void {
	resting = true;
	if (closing === undefined) return;
	clearTimeout(closing);
	closing = undefined;
	left = Math.max(1_500, left - (Date.now() - since));
}
function go(): void {
	resting = false;
	if (left && !staying) closeIn(left);
}
/** One did something here: it stays open. */
function stay(): void {
	staying = true;
	clearTimeout(closing);
	closing = undefined;
}
document.addEventListener('pointerenter', pause);
document.addEventListener('pointerleave', go);
document.addEventListener('focusin', pause);
document.addEventListener('focusout', go);

async function save(tabId: number, owners: Owner[]): Promise<void> {
	state('Reading the page…');
	stage('reading');
	const result = (await chrome.runtime.sendMessage({ type: 'popupSave', tabId })) as Result;
	show(result, owners);
	closeIn(!result.ok ? CLOSE_MS.error : result.warning ? CLOSE_MS.warning : CLOSE_MS.ok);
}

(async () => {
	if (!(await settings())) {
		state('Not connected to a paperus yet.');
		$('connect').hidden = false;
		$('connect').addEventListener('click', async () => {
			await chrome.runtime.openOptionsPage();
			window.close();
		});
		return;
	}
	// The tab under the button; or one named (opened as a page, in tests).
	const named = Number(new URLSearchParams(location.search).get('tab'));
	const [tab] = named
		? [await chrome.tabs.get(named)]
		: await chrome.tabs.query({ active: true, currentWindow: true });
	if (tab?.id === undefined) {
		state('No page to save.', 'error');
		return;
	}
	chrome.runtime.onMessage.addListener((message) => {
		if (message?.type === 'saveStep' && message.tabId === tab.id) {
			state(message.text);
			if (STAGES[message.text]) stage(STAGES[message.text]);
		}
	});
	// The page's site: its icon and name.
	const icon = $<HTMLImageElement>('site-icon');
	if (tab.favIconUrl) {
		icon.src = tab.favIconUrl;
		icon.addEventListener('error', () => {
			icon.hidden = true;
			$('site-globe').removeAttribute('hidden'); // an SVG: no .hidden
		});
	} else {
		icon.hidden = true;
		$('site-globe').removeAttribute('hidden'); // an SVG: no .hidden
	}
	try {
		$('site-name').textContent = siteName(new URL(tab.url ?? '').hostname);
	} catch {
		// No address to show.
	}
	const { owners = [] } = (await chrome.storage.local.get('owners')) as { owners?: Owner[] };
	$('allow').addEventListener('click', async () => {
		stay();
		if (!(await chrome.permissions.request(ALL_SITES).catch(() => false))) return;
		$('allow').hidden = true;
		$('detail').hidden = true;
		await save(tab.id!, owners);
	});
	await save(tab.id, owners);
})();
