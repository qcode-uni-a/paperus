/**
 * Client for the paperus API, generated from its OpenAPI schema.
 *
 * ```ts
 * import { configure, search } from 'paperus';
 * configure({ baseUrl: 'https://paperus.example.org', token: '…' });
 * const { data } = await search({ query: { q: 'drought indices' } });
 * ```
 */
import { client } from './generated/client.gen.js';

export * from './generated/index.js';
export { client };

export interface Options {
	/** Address of the paperus server, e.g. "https://paperus.example.org". */
	baseUrl: string;
	/** A session token from `login`; sent as a bearer token. */
	token?: string;
}

/** Point the client at a server, optionally with a login token. */
export function configure({ baseUrl, token }: Options): void {
	client.setConfig({
		baseUrl: baseUrl.replace(/\/$/, ''),
		headers: token ? { Authorization: `Bearer ${token}` } : {}
	});
}
