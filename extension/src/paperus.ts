/** The connection to paperus: its address, the extension's access token
 * (it may only add papers and see which one has), and the default owner. */
import type * as Api from '../../web/src/lib/api/generated/types.gen';

export type { Api };

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

/** One of paperus's API operations, from the types generated from its
 * OpenAPI schema (`web/src/lib/api/generated`, kept up to date by a server
 * test): a server change that breaks a call here fails the type check. */
interface Operation {
	url: string;
	path?: Record<string, string>;
	query?: Record<string, string | string[]>;
	body?: unknown;
}

/** A call to paperus's API with the token: the operation's address (with
 * its {placeholders} filled from `path`), JSON or a form in, JSON out. */
export async function call<O extends Operation, R = unknown>(
	url: O['url'],
	init: {
		method?: string;
		path?: O['path'];
		query?: O['query'];
		json?: O['body'];
		form?: FormData;
	} = {}
): Promise<{ status: number; data: R }> {
	const config = await settings();
	if (!config) throw new PaperusError('Not connected to paperus yet.');
	const filled = url.replace(/\{(\w+)\}/g, (_, name: string) =>
		encodeURIComponent((init.path as Record<string, string>)[name])
	);
	const address = new URL(filled, config.server);
	const query = (init.query ?? {}) as Record<string, string | string[]>;
	for (const [name, values] of Object.entries(query)) {
		for (const value of [values].flat()) address.searchParams.append(name, value);
	}
	const headers: Record<string, string> = { Authorization: `Bearer ${config.token}` };
	let body: BodyInit | undefined = init.form;
	if (init.json !== undefined) {
		headers['Content-Type'] = 'application/json';
		body = JSON.stringify(init.json);
	}
	let response: Response;
	try {
		response = await fetch(address, { method: init.method ?? 'GET', headers, body });
	} catch {
		throw new PaperusError(`paperus does not answer at ${config.server}.`);
	}
	if (response.status === 401) throw new PaperusError('The connection to paperus has ended; connect again.');
	const data = (await response.json().catch(() => null)) as R;
	if (!response.ok && response.status !== 404) {
		const detail = (data as { detail?: unknown } | null)?.detail;
		throw new PaperusError(typeof detail === 'string' ? detail : `paperus answered ${response.status}.`);
	}
	return { status: response.status, data };
}
