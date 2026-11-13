import { type Api, call, saveSettings, settings } from './paperus';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const message = (text: string) => ($('message').textContent = text);

/** Plain HTTP to another machine: the token and papers unencrypted. */
function insecure(address: string): boolean {
	try {
		const { protocol, hostname } = new URL(address);
		const local = /^(localhost|127(\.\d+){3}|\[::1\])$|\.localhost$/.test(hostname);
		return protocol === 'http:' && !local;
	} catch {
		return false;
	}
}

const warn = (address: string) => ($('insecure').hidden = !insecure(address));

// The version installed (as the browser's extension list shows it).
$('version').textContent = `Version ${chrome.runtime.getManifest().version}`;

// The log (log.ts): newest first, as it grows.
interface Entry {
	at: string;
	level: string;
	message: string;
	context?: Record<string, string | number | boolean | null>;
}
const asText = (entry: Entry): string =>
	[
		`${entry.at.replace('T', ' ').slice(0, 19)} ${entry.level.toUpperCase()} ${entry.message}`,
		...Object.entries(entry.context ?? {}).map(([key, value]) => `    ${key}: ${value}`)
	].join('\n');

async function showLog(): Promise<void> {
	const { log = [] } = (await chrome.storage.local.get('log')) as { log?: Entry[] };
	const list = $('log');
	list.replaceChildren(
		...log
			.slice()
			.reverse()
			.map((entry) => {
				const item = document.createElement('li');
				item.className = entry.level;
				const head = document.createElement('div');
				const time = document.createElement('time');
				time.textContent = new Date(entry.at).toLocaleTimeString();
				head.append(time, ` ${entry.message}`);
				item.append(head);
				const details = Object.entries(entry.context ?? {});
				if (details.length) {
					const more = document.createElement('dl');
					for (const [key, value] of details) {
						const term = document.createElement('dt');
						term.textContent = key;
						const text = document.createElement('dd');
						text.textContent = String(value);
						more.append(term, text);
					}
					item.append(more);
				}
				return item;
			})
	);
	if (!log.length) {
		const empty = document.createElement('li');
		empty.className = 'muted';
		empty.textContent = 'Nothing yet.';
		list.append(empty);
	}
}
$('copy-log').addEventListener('click', async () => {
	const { log = [] } = (await chrome.storage.local.get('log')) as { log?: Entry[] };
	await navigator.clipboard.writeText(
		[`paperus extension ${chrome.runtime.getManifest().version}`, ...log.map(asText)].join('\n')
	);
	message('The log is copied.');
});
$('clear-log').addEventListener('click', async () => {
	await chrome.storage.local.set({ log: [] });
});
chrome.storage.onChanged.addListener((changes, area) => {
	if (area === 'local' && 'log' in changes) void showLog();
});
void showLog();

async function show(): Promise<void> {
	const config = await settings();
	warn(config ? config.server : $<HTMLInputElement>('server').value.trim());
	$('disconnected').hidden = !!config;
	$('connected').hidden = !config;
	if (!config) return;
	const link = $<HTMLAnchorElement>('server-link');
	link.href = config.server;
	link.textContent = config.server;
	const owner = $<HTMLSelectElement>('owner');
	owner.replaceChildren(new Option('My default owner (set in paperus)', ''));
	try {
		const { data } = await call<Api.ListLibrariesData, Api.ListLibrariesResponse>('/api/libraries');
		for (const library of (data ?? []).filter((l) => l.writable)) {
			owner.append(new Option(library.name, library.id, false, library.id === config.owner));
		}
	} catch (error) {
		message(String((error as Error).message));
	}
}

$('server').addEventListener('input', (event) => warn((event.target as HTMLInputElement).value.trim()));

$('connect').addEventListener('click', async () => {
	const input = $<HTMLInputElement>('server');
	let origin: string;
	try {
		origin = new URL(input.value.trim()).origin;
	} catch {
		message('Enter the address you open paperus at, e.g. https://papers.example.org.');
		return;
	}
	// Asked now, while the click counts as the person's: paperus itself (its
	// host, any port: Firefox's patterns have none), and arXiv for the
	// buttons there.
	const { protocol, hostname } = new URL(origin);
	const granted = await chrome.permissions.request({
		origins: [`${protocol}//${hostname}/*`, 'https://arxiv.org/*']
	});
	if (!granted) {
		message('The extension needs to reach your paperus to save papers there.');
		return;
	}
	message('Confirm in the paperus tab that just opened…');
	const result = await chrome.runtime.sendMessage({ type: 'connect', server: origin });
	message(result?.text ?? '');
	await show();
});

$('owner').addEventListener('change', async () => {
	const config = await settings();
	const select = $<HTMLSelectElement>('owner');
	if (!config) return;
	await saveSettings({
		...config,
		owner: select.value || undefined,
		ownerName: select.value ? select.selectedOptions[0].text : undefined
	});
	message(select.value ? `New papers belong to ${select.selectedOptions[0].text}.` : 'New papers go to your default owner.');
});

const saveSupplements = $<HTMLInputElement>('save-supplements');
void chrome.storage.local
	.get('saveSupplements')
	.then(({ saveSupplements: on }) => (saveSupplements.checked = on !== false));
saveSupplements.addEventListener('change', async () => {
	await chrome.storage.local.set({ saveSupplements: saveSupplements.checked });
	message(
		saveSupplements.checked
			? "A paper's supplementary files are saved with it."
			: 'Supplementary files are only listed in the popup, to add those you want.'
	);
});

const markPapers = $<HTMLInputElement>('mark-papers');
void chrome.storage.local
	.get('markPapers')
	.then(({ markPapers: on }) => (markPapers.checked = on !== false));
markPapers.addEventListener('change', async () => {
	await chrome.storage.local.set({ markPapers: markPapers.checked });
	message(
		markPapers.checked
			? 'The button shows whether you have the paper of a page you open.'
			: 'The button no longer looks up the papers of pages you open.'
	);
});

$('disconnect').addEventListener('click', async () => {
	await saveSettings(null);
	message('Disconnected. You can remove the extension’s access token in paperus (Settings → Access tokens).');
	await show();
});

chrome.storage.onChanged.addListener(() => show());
show();
