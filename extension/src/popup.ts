/** The popup under the paperus button (as Zotero's): opening it saves the
 * tab's paper to the default owner, showing each step, then the paper, its
 * PDF or why not, and a choice of owner that moves a paper just added. */
import type { Listed } from './extras';
import { settings } from './paperus';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const ALL_SITES = { origins: ['https://*/*', 'http://*/*'] };

interface Owner {
	id: string;
	name: string;
	default?: boolean;
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
		closing = setTimeout(() => {
			// The pointer on it after all (no event told): ask again shortly.
			if (document.documentElement.matches(':hover')) closeIn(1_500);
			else window.close();
		}, left);
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
// Over and out bubble (enter and leave do not, and Firefox's popup
// never sent them to the document): out to nothing is out of the popup.
document.addEventListener('pointerover', () => resting || pause());
document.addEventListener('pointerout', (event) => {
	if (!event.relatedTarget) go();
});
document.addEventListener('focusin', pause);
document.addEventListener('focusout', go);

type Survey =
	| { mode: 'paper'; listed: Listed[] }
	| { mode: 'list'; source: 'page' | 'scholar'; title: string; listed: Listed[] };
type ListedState = 'saving' | 'saved' | 'known' | 'failed' | 'too-large';

function megabytes(bytes: number): string {
	return `${Math.max(1, Math.round(bytes / 1024 / 1024))} MB`;
}

/** What a page lists, or a Scholar profile's papers, to tick and save:
 * each its own paper. One already in paperus is marked (and not ticked);
 * a file over 100 MB is left out until one asks again ("Save anyway"). */
function showList(
	tabId: number,
	title: string,
	source: 'page' | 'scholar',
	listed: Listed[],
	owners: Owner[],
	ownerId: string | undefined
): void {
	stay();
	for (const id of ['flow', 'state', 'title', 'detail', 'open', 'show-list', 'owner-field'])
		$(id).hidden = true;
	$('list').hidden = false;
	$('list-title').textContent = title;
	const boxes = new Map<string, HTMLInputElement>();
	const marks = new Map<string, HTMLElement>();
	const button = $<HTMLButtonElement>('save-listed');
	const what = source === 'scholar' ? 'papers' : 'files and papers';
	const known = listed.filter((entry) => entry.itemId).length;
	$('list-count').textContent = `${listed.length} ${what}${known ? `, ${known} in paperus` : ''}`;
	const count = () => {
		const chosen = [...boxes.values()].filter((box) => box.checked).length;
		button.textContent = `Save ${chosen}`;
		button.disabled = chosen === 0;
	};
	const mark = (key: string, state: ListedState, text = '', link?: string, size?: number) => {
		const shown = marks.get(key);
		if (!shown) return;
		shown.className = `mark ${state}`;
		shown.title = state === 'too-large' ? 'Over 100 MB: saved only when you ask' : text;
		shown.replaceChildren();
		const words: Record<ListedState, string> = {
			saving: 'Saving…',
			saved: '✓ Saved',
			known: 'In paperus',
			failed: '✕ Not saved',
			'too-large': megabytes(size ?? 0)
		};
		if (link && (state === 'saved' || state === 'known')) {
			const open = document.createElement('a');
			open.href = link;
			open.target = '_blank';
			open.textContent = words[state];
			shown.append(open);
		} else shown.append(words[state]);
		if (state === 'too-large') {
			const anyway = document.createElement('button');
			anyway.className = 'text';
			anyway.textContent = 'Save anyway';
			anyway.addEventListener('click', () => {
				const entry = listed.find((e) => e.key === key);
				if (entry) void send([entry], true);
			});
			shown.append(anyway);
		}
	};
	$('listed').replaceChildren(
		...listed.map((entry) => {
			const item = document.createElement('li');
			const label = document.createElement('label');
			const box = document.createElement('input');
			box.type = 'checkbox';
			box.checked = entry.chosen;
			box.addEventListener('change', count);
			boxes.set(entry.key, box);
			const name = document.createElement('span');
			name.className = 'name';
			const words = document.createElement('span');
			words.textContent = entry.name;
			words.title = entry.name;
			const detail = document.createElement('small');
			detail.textContent = entry.detail;
			name.append(words, detail);
			label.append(box, name);
			const shown = document.createElement('span');
			shown.className = 'mark';
			marks.set(entry.key, shown);
			item.append(label, shown);
			return item;
		})
	);
	for (const entry of listed) if (entry.itemId) mark(entry.key, 'known');
	$('all').onclick = () => {
		for (const box of boxes.values()) box.checked = true;
		count();
	};
	$('none').onclick = () => {
		for (const box of boxes.values()) box.checked = false;
		count();
	};
	const select = $<HTMLSelectElement>('list-owner');
	if (owners.length > 1) {
		// The settings' owner, else the default set in paperus (not the first).
		const chosen = ownerId ?? owners.find((owner) => owner.default)?.id;
		select.replaceChildren(
			...owners.map((owner) => new Option(owner.name, owner.id, false, owner.id === chosen))
		);
		$('list-owner-field').hidden = false;
	}
	chrome.runtime.onMessage.addListener((message) => {
		if (message?.type === 'listedState' && message.tabId === tabId)
			mark(message.key, message.state, message.text, message.link, message.size);
	});
	const send = async (chosen: Listed[], large = false) => {
		button.disabled = true;
		for (const box of boxes.values()) box.disabled = true;
		const counts = (await chrome.runtime.sendMessage({
			type: 'popupSaveListed',
			tabId,
			listed: chosen,
			ownerId: select.value || ownerId,
			large
		})) as Record<string, number>;
		const parts = [
			counts.saved && `${counts.saved} saved`,
			counts.known && `${counts.known} in paperus already`,
			counts.failed && `${counts.failed} not saved`,
			counts['too-large'] && `${counts['too-large']} over 100 MB`
		].filter(Boolean);
		$('list-count').textContent = parts.join(', ') || 'Nothing saved';
		button.textContent = 'Saved';
	};
	button.onclick = () =>
		void send(listed.filter((entry) => boxes.get(entry.key)?.checked));
	count();
}

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
	state('Reading the page…');
	stage('reading');
	const found = (await chrome.runtime.sendMessage({ type: 'popupSurvey', tabId: tab.id })) as
		| Survey
		| { ok: false };
	const config = await settings();
	if ('mode' in found && found.mode === 'list') {
		showList(tab.id, found.title, found.source, found.listed, owners, config?.owner);
		return;
	}
	await save(tab.id, owners);
	// A paper's page that links more papers or files: those on a click.
	const listed = 'listed' in found ? found.listed : [];
	if (listed.length >= 2) {
		const more = $('show-list');
		more.textContent = `${listed.length} more papers and files linked here…`;
		more.hidden = false;
		more.onclick = () =>
			showList(tab.id!, 'Linked on this page', 'page', listed, owners, config?.owner);
	}
})();
