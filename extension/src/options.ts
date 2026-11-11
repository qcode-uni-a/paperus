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

$('disconnect').addEventListener('click', async () => {
	await saveSettings(null);
	message('Disconnected. You can remove the extension’s access token in paperus (Settings → Access tokens).');
	await show();
});

chrome.storage.onChanged.addListener(() => show());
show();
