/** The connection to paperus: its address, the extension's access token
 * (it may only add papers and see which one has), and the default owner. */

export interface Settings {
	server: string;
	token: string;
	/** Library new papers belong to; the person's default if unset. */
	owner?: string;
	ownerName?: string;
}

export async function settings(): Promise<Settings | null> {
	const stored = (await chrome.storage.local.get('settings')) as { settings?: Settings };
	return stored.settings?.server && stored.settings.token ? stored.settings : null;
}

export async function saveSettings(next: Settings | null): Promise<void> {
	if (next) await chrome.storage.local.set({ settings: next });
	else await chrome.storage.local.remove('settings');
}

export class PaperusError extends Error {}

/** A call to paperus's API with the token; JSON in and out. */
export async function call<T>(
	path: string,
	init: { method?: string; json?: unknown; body?: BodyInit; query?: Record<string, string[]> } = {}
): Promise<{ status: number; data: T }> {
	const config = await settings();
	if (!config) throw new PaperusError('Not connected to paperus yet.');
	const url = new URL(path, config.server);
	for (const [name, values] of Object.entries(init.query ?? {})) {
		for (const value of values) url.searchParams.append(name, value);
	}
	const headers: Record<string, string> = { Authorization: `Bearer ${config.token}` };
	let body = init.body;
	if (init.json !== undefined) {
		headers['Content-Type'] = 'application/json';
		body = JSON.stringify(init.json);
	}
	let response: Response;
	try {
		response = await fetch(url, { method: init.method ?? 'GET', headers, body });
	} catch {
		throw new PaperusError(`paperus does not answer at ${config.server}.`);
	}
	if (response.status === 401) throw new PaperusError('The connection to paperus has ended; connect again.');
	const data = (await response.json().catch(() => null)) as T;
	if (!response.ok && response.status !== 404) {
		const detail = (data as { detail?: unknown } | null)?.detail;
		throw new PaperusError(typeof detail === 'string' ? detail : `paperus answered ${response.status}.`);
	}
	return { status: response.status, data };
}

export interface Library {
	id: string;
	name: string;
	writable: boolean;
}

export interface Item {
	id: string;
	title: string;
	library_id: string;
}
